"""Explicit expired-session recovery. Root never loads a host private key."""
import argparse
import copy
import json
import os
import time
from contextlib import contextmanager
from zog.host_identify import signatures, recovery as proof
from zog.host_install.state_contract import canonical, decode, fields, require, StateError
from zog.host_install.state_inspect import inspect_live, read_at, metadata
from . import supervisor, admission, beacon_state
from .beacon import HTTPS, Beacon, digest
from .managed import ManagedState
from .managed_transport import Runtime


def selected(context, saved):
    beacon_state.validate(saved)
    b=context.bundle['bootstrap']
    require(b['mode'] in ('fresh','existing') and len(b['registries'])==1,'recovery-profile','Single registry required')
    reg=b['registries'][0];rid=reg['registry_id'];row=saved['registries'].get(rid)
    require(reg['role']=='control' and rid==b['control_authority']['registry_id'] and row is not None and row['pending'] is not None,
            'recovery-pending','A pending control request is required')
    require(row['origin']==reg['origin'] and row['role']==reg['role'] and row['pending']['authority_id']==b['control_authority']['authority_id'],
            'recovery-binding','Configuration changed')
    expected=b['initialization']['expected_host_uuid']
    require(expected is None or row['host_id']==expected,'recovery-binding','Host UUID differs')
    return reg,row


def evidence(state, operation, transport=None):
    """UID970 read-only command: fresh identity/admission, no supervisor reset."""
    supervisor.identifier(operation)
    state._protected_uuid_pending=True
    runtime=Runtime(state)
    try:
        runtime.open();reg,row=selected(state.context,runtime.saved)
        payload=dict(version=1,operation_id=operation,journal_sha256=digest(runtime.saved),pending=row['pending'])
        return runtime.post(transport or HTTPS(),reg,f"/api/hosts/{row['host_id']}/managed-recovery/",payload,row['host_id'])
    finally:runtime.close()


def replacement(context, old, response, operation, station_fingerprint=None, now=None):
    reg,row=selected(context,old)
    fields(response,'version public_key evidence')
    require(type(response['version']) is int and response['version']==1,'recovery-evidence','Wrong evidence version')
    key=signatures.public_key(response['public_key'])
    if row['public_key'] is not None:
        require(response['public_key']==row['public_key'],'station-key-conflict','Pinned station key differs')
        require(station_fingerprint is None,'recovery-trust','No override of existing trust')
    else:
        require(station_fingerprint==signatures.fingerprint(key),'recovery-trust','First-session recovery requires independently confirmed station key fingerprint')
    expected=dict(iss=reg['origin'].rstrip('/'),aud=context.bundle['bootstrap']['control_authority']['authority_id'],
        sub=row['host_id'],operation_id=operation,journal_sha256=digest(old),request_sha256=proof.digest(row['pending']),
        **{k:old[k] for k in ('fingerprint','installation_id','state_volume_id')},registry_id=reg['registry_id'])
    claims=proof.verify(response['evidence'],key,expected,now=now)
    require(claims['jti']==operation and claims['epoch']==(row['previous']['epoch']+1 if row['previous'] else 1),
            'recovery-epoch','Evidence must advance exactly one accepted checkpoint')
    new=copy.deepcopy(old);target=new['registries'][reg['registry_id']]
    target['public_key']=response['public_key'];target['previous']={k:claims[k] for k in ('epoch','checkpoint')};target['pending']=None
    return beacon_state.validate(new)


def healthy(context, journal, binding):
    journal.recheck()
    observation=supervisor.wire.observe(context)
    require(not observation['recovery_hold'] and supervisor.fixed(context,observation)==binding,'recovery-admission','Identity changed or installer hold')
    # Same reserved-directory checks as ordinary beacon startup, no key loading.
    holder=type('Holder',(),{'context':context})()
    Beacon(holder).unused_state()


@contextmanager
def locked(context):
    require(os.geteuid()==0,'root-required','Explicit root recovery only')
    journal=admission.Journal(context)
    try:
        journal.acquire()
        with supervisor.ledger(context,recovery=True) as pair:yield journal,*pair
    finally:journal.close()


def atomic(fd, name, value, temporary, uid, gid):
    """Only called after a durable root recovery record authorizes these bytes."""
    if temporary in os.listdir(fd):
        # A partial temporary write may be discarded; the root record is authority.
        f=os.open(temporary,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        try:
            # Creation precedes chown: a crash may leave this recovery-owned
            # temporary file root-owned. Its bytes are never adopted.
            owner=os.fstat(f)
            if uid!=0 and owner.st_uid==0 and owner.st_gid==0:metadata(f,0,0,0o600,False)
            else:metadata(f,uid,gid,0o600,False)
        finally:os.close(f)
        os.unlink(temporary,dir_fd=fd);os.fsync(fd)
    f=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
    try:
        os.fchown(f,uid,gid)
        view=memoryview(canonical(value))
        while view:
            n=os.write(f,view);require(n>0,'state-io-failure','Short write');view=view[n:]
        os.fsync(f)
    finally:os.close(f)
    os.fsync(fd);os.replace(temporary,name,src_dir_fd=fd,dst_dir_fd=fd);os.fsync(fd)


def finish(context,journal,fd,current,record):
    fields(record,'schema kind operation_id accepted_at reason station_fingerprint response old_journal old_ledger new_journal new_ledger')
    require(record['schema']==1 and record['kind']=='zog-session-recovery','recovery-record','Invalid recovery record')
    supervisor.identifier(record['operation_id'])
    require(type(record['accepted_at']) is int,'recovery-record','Invalid evidence acceptance time')
    new=replacement(context,record['old_journal'],record['response'],record['operation_id'],record['station_fingerprint'],record['accepted_at'])
    require(new==record['new_journal'],'recovery-record','Changed recovery target')
    old=record['old_ledger'];expected=copy.deepcopy(old);expected['journal_sha256']=digest(new);expected['revision']+=1
    require(expected==record['new_ledger'] and old['journal_sha256']==digest(record['old_journal']), 'recovery-record','Changed checkpoint transition')
    healthy(context,journal,old['binding'])
    require(current in (old,expected),'recovery-conflict','Supervisor changed during recovery')
    require(set(os.listdir(journal.fd))<={'managed.lock','managed.json','managed.recovery'},'recovery-files','Unknown journal publication')
    saved=journal.read()
    require(saved in (record['old_journal'],new),'recovery-conflict','Journal changed during recovery')
    require(current==old or saved==new,'recovery-conflict','Checkpoint advanced before journal')
    os.fsync(fd)  # Make a recovered marker rename durable before further effects.
    if saved!=new or 'managed.recovery' in os.listdir(journal.fd):
        atomic(journal.fd,'managed.json',new,'managed.recovery',970,970)
    os.fsync(journal.fd)  # Also complete a prior rename whose fsync was interrupted.
    healthy(context,journal,old['binding'])
    if current!=expected or 'ledger.recovery' in os.listdir(fd):
        atomic(fd,'ledger.json',expected,'ledger.recovery',0,0)
    healthy(context,journal,old['binding'])
    require(journal.read()==new,'recovery-conflict','Journal changed before completion')
    os.fsync(fd)  # Complete a prior ledger rename before marking recovery done.
    # The immutable receipt remains root-only. Normal begin/reset stay blocked
    # until this last rename is durable; fault/run were never cleared.
    os.replace('recovery.json','last-recovery.json',src_dir_fd=fd,dst_dir_fd=fd);os.fsync(fd)
    return dict(status='session-reconciled',operation_id=record['operation_id'],revision=expected['revision'],
                reset_required=expected['run'] is not None,remote_control_enabled=False)


def apply(context,revision,run_id,operation,response,reason,station_fingerprint=None):
    supervisor.identifier(operation);supervisor.identifier(run_id)
    require(type(reason) is str and 1<=len(reason)<=256 and all(ord(c)>=32 for c in reason),'recovery-reason','Bounded operator reason required')
    with locked(context) as (journal,fd,value):
        require('recovery.json' not in os.listdir(fd) and 'ledger.recovery' not in os.listdir(fd),'recovery-in-progress','Use explicit resume')
        require(type(revision) is int and value['revision']==revision and value['run'] is not None and value['run']['id']==run_id,
                'recovery-conflict','Inspect exact revision and run')
        old=journal.read();healthy(context,journal,value['binding'])
        require(set(os.listdir(journal.fd))=={'managed.json','managed.lock'},'recovery-files','Interrupted ordinary writes need separate recovery')
        require(digest(old)==value['journal_sha256'] and all(old[k]==v for k,v in value['binding'].items()),'recovery-checkpoint','Local checkpoint mismatch')
        if 'last-recovery.json' in os.listdir(fd):
            last=decode(read_at(fd,'last-recovery.json',0,0,0o600))
            require(last['operation_id']!=operation,'recovery-replay','Use a new recovery identity')
        now=int(time.time());new=replacement(context,old,response,operation,station_fingerprint,now)
        target=copy.deepcopy(value);target['revision']+=1;target['journal_sha256']=digest(new)
        record=dict(schema=1,kind='zog-session-recovery',operation_id=operation,accepted_at=now,reason=reason,
                    station_fingerprint=station_fingerprint,response=response,old_journal=old,old_ledger=value,new_journal=new,new_ledger=target)
        require(len(canonical(record))<=65536,'recovery-capacity','Recovery record exceeds capacity')
        # A partial staging file is safe to replace only after revalidating all
        # original state and a fresh signed response above. No effects precede it.
        atomic(fd,'recovery.json',record,'recovery.stage',0,0)
        return finish(context,journal,fd,value,record)


def resume(context,operation):
    supervisor.identifier(operation)
    with locked(context) as (journal,fd,value):
        name='recovery.json' if 'recovery.json' in os.listdir(fd) else 'last-recovery.json'
        record=decode(read_at(fd,name,0,0,0o600))
        require(record['operation_id']==operation,'recovery-conflict','Wrong recovery operation')
        if name=='last-recovery.json':
            healthy(context,journal,value['binding'])
            require(value==record['new_ledger'] and journal.read()==record['new_journal'] and
                    set(os.listdir(fd))=={'lock','ledger.json','last-recovery.json'},'recovery-conflict','Completed recovery has since changed')
            return dict(status='session-reconciled',operation_id=operation,revision=value['revision'],reset_required=value['run'] is not None,remote_control_enabled=False)
        require('recovery.stage' not in os.listdir(fd),'recovery-files','Unexpected staging file')
        return finish(context,journal,fd,value,record)


def inspect_recovery(context):
    with locked(context) as (journal,fd,value):
        healthy(context,journal,value['binding'])
        names=set(os.listdir(fd))
        name='recovery.json' if 'recovery.json' in names else 'last-recovery.json' if 'last-recovery.json' in names else None
        record=decode(read_at(fd,name,0,0,0o600)) if name else None
        return dict(status='recovery-in-progress' if 'recovery.json' in names else 'recovery-staged' if 'recovery.stage' in names else 'recovery-complete' if name else 'no-recovery',
            operation_id=record['operation_id'] if record else None,revision=value['revision'],
            run_id=value['run']['id'] if value['run'] else None,journal_sha256=value['journal_sha256'],
            remote_control_enabled=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('inspect')
    p=sub.add_parser('evidence');p.add_argument('--operation-id',required=True)
    p=sub.add_parser('apply');p.add_argument('--operation-id',required=True);p.add_argument('--revision',type=int,required=True)
    p.add_argument('--run-id',required=True);p.add_argument('--reason',required=True);p.add_argument('--evidence-file',required=True);p.add_argument('--station-key-fingerprint')
    p=sub.add_parser('resume');p.add_argument('--operation-id',required=True)
    a=parser.parse_args()
    try:
        if a.command=='evidence':
            with ManagedState() as state:result=evidence(state,a.operation_id)
        else:
            require(os.geteuid()==0,'root-required','Root recovery only')
            with inspect_live() as context:
                if a.command=='inspect':result=inspect_recovery(context)
                elif a.command=='resume':result=resume(context,a.operation_id)
                else:
                    f=os.open(a.evidence_file,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
                    try:
                        import stat
                        require(stat.S_ISREG(os.fstat(f).st_mode),'recovery-evidence','Regular evidence file required')
                        raw=os.read(f,65537);require(len(raw)<=65536,'recovery-evidence','Evidence too large')
                        response=decode(raw)
                    finally:os.close(f)
                    result=apply(context,a.revision,a.run_id,a.operation_id,response,a.reason,a.station_key_fingerprint)
        print(json.dumps(result,sort_keys=True))
    except (StateError,OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps(dict(status='blocked',code=getattr(exc,'code','recovery-refused'),remote_control_enabled=False)))
        raise SystemExit(2) from None

if __name__=='__main__':main()
