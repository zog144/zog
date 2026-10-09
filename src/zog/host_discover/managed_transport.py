"""Experimental managed transport integration. Local fixtures only; production disabled."""
import copy
import json
import ssl
import time
import urllib.request
import uuid
from zog.host_install.state_contract import StateError, require, canonical, decode
from zog.host_identify import signatures, managed as protocol
from . import admission
from .retry import RetryableTransport
from .managed import ManagedState
from .daemon import NoRedirect, collect


class Transport:
    def post(self,*args,**kwargs):
        # Full component capability gating and joint live acceptance are pending.
        # Tests inject a local fixture; no production network path is enabled.
        raise StateError('managed-transport-disabled','Narrow identity diagnostic only')


class Runtime:
    def __init__(self,state):
        self.state=state;self.journal=None;self.key=None;self.sessions={};self.saved=None;self.resuming=set()

    def guard(self):
        self.state.check()
        require(admission.observe(self.state.context)['receipt']==self.observation['receipt'],'admission-changed','Coordinator evidence withdrawn or changed')

    def fail(self,error):
        self.key=None;self.sessions.clear()
        self.state.fail(getattr(error,'code','managed-admission-failed'))

    def open(self,prepare=False):
        try:
            b=self.state.context.bundle['bootstrap'];self.bootstrap=b
            require(b['mode'] in ('fresh','existing'),'recovery-required','Migration/recovery requires explicit reconciliation')
            self.observation=admission.verify_existing(self.state)
            self.key=self.state._key
            self.journal=admission.Journal(self.state.context)
            self.journal.acquire(prepare)
            binding=dict(installation_id=b['installation_id'],state_volume_id=b['state']['state_volume_id'],fingerprint=self.observation['receipt']['fingerprint'])
            if prepare:
                require(set(__import__('os').listdir(self.journal.fd))=={'managed.lock'},'managed-state-exists','Preparation never adopts existing control state')
                self.journal.write(dict(schema=1,kind='zog-managed-journal',**binding,registries={},replay=[]))
            self.saved=self.journal.read()
            require(all(self.saved[k]==v for k,v in binding.items()),'managed-binding-conflict','Journal is for another identity')
            self.resuming={rid for rid,row in self.saved['registries'].items() if row['pending'] is not None}
            configured={r['registry_id']:r for r in b['registries']}
            for name,row in self.saved['registries'].items():
                require(name in configured and row['origin']==configured[name]['origin'] and row['role']==configured[name]['role'],'managed-registry-conflict','Registry transition requires approval')
            self.guard()
            return self
        except Exception as exc:
            self.close();self.fail(exc)

    def close(self):
        self.key=None;self.sessions.clear()
        if self.journal:self.journal.close();self.journal=None

    def commit(self,value):
        try:
            self.guard();self.journal.write(value);self.saved=copy.deepcopy(value);self.guard()
        except Exception as exc:self.fail(exc)

    def ca(self,registry):
        # Re-read via host-install's root-controlled loader; it validates raw CA
        # digests and protected paths. Do not subsequently reopen an unverified path.
        if registry['ca'] is None:return None
        from zog.host_install.state_inspect import directory,read_at,metadata
        import os,hashlib
        fd=directory('/etc/zog/host-install/ca')
        try:
            metadata(fd,0,0,0o755)
            raw=read_at(fd,registry['registry_id']+'.pem')
        finally:os.close(fd)
        require(hashlib.sha256(raw).hexdigest()==registry['ca']['sha256'],'ca-digest','CA changed')
        return raw

    def post(self,transport,reg,path,payload,subject):
        self.guard()
        ca=self.ca(reg)
        self.guard()
        result=transport.post(reg['origin'].rstrip('/')+path,payload,self.key,subject,ca)
        self.guard()
        return result

    def transport_failure(self,error):
        self.fail(error)

    def tick(self,transport=None,report=None):
        transport=transport or Transport()
        try:
            self.guard()
            if report is None:
                report=collect({'provider':'generic'})
                boot=self.state.context.bundle['installation']['installer_recorded']['foreign_boot_bundle']
                if boot and boot['provider']=='amazon-linux-2023':
                    from .daemon import metadata
                    report.update(metadata())  # Failure must not enroll a generic duplicate.
                from zog.host_install.state_inspect import host_generation_report
                report['host_generation']=host_generation_report(self.state.context)
            for reg in self.bootstrap['registries']:
                self.registry(transport,reg,report)
        except RetryableTransport as exc:self.transport_failure(exc)
        except Exception as exc:self.fail(exc)

    def registry(self,transport,reg,report):
        rid=reg['registry_id'];data=copy.deepcopy(self.saved)
        row=data['registries'].setdefault(rid,dict(origin=reg['origin'],role=reg['role'],host_id=None,
            public_key=None,previous=None,pending=None))
        if not row['host_id']:
            response=self.post(transport,reg,'/api/hosts/enrollment/',dict(public_key=signatures.public_text(self.key.public_key()),claimed_host_id='',report=report),'pending')
            if response.get('status')=='pending':return
            require(response.get('status')=='approved' and response.get('fingerprint')==self.saved['fingerprint'],'managed-enrollment-denied','Explicit fingerprint approval required')
            row['host_id']=protocol.identifier(response['host_id']);self.commit(data)
        host=row['host_id']
        session=self.sessions.get(rid)
        if not session or time.time()>=session['exp']-60:
            if row['pending'] is None:
                row['pending']=dict(version=1,installation_id=data['installation_id'],state_volume_id=data['state_volume_id'],
                    authority_id=self.bootstrap['control_authority']['authority_id'],registry_id=rid,
                    challenge=str(uuid.uuid4()),previous=row['previous'],boot_id=self.observation['bindings']['boot_id'])
                self.commit(data)  # durable retry identity before station advances
            response=self.post(transport,reg,f'/api/hosts/{host}/managed-session/',row['pending'],host)
            require(set(response)=={'version','public_key','session'} and response['version']==1,'managed-session-response','Unsupported response')
            key=signatures.public_key(response['public_key'])
            require(row['public_key'] is None or row['public_key']==response['public_key'],'station-key-conflict','Explicit key transition required')
            expected=dict(iss=reg['origin'].rstrip('/'),aud=self.bootstrap['control_authority']['authority_id'],sub=host,
                fingerprint=data['fingerprint'],installation_id=data['installation_id'],state_volume_id=data['state_volume_id'],
                registry_id=rid,challenge=row['pending']['challenge'],previous=row['previous'],boot_id=row['pending']['boot_id'])
            session=protocol.session(response['session'],key,expected)
            require(session['epoch']==(row['previous']['epoch']+1 if row['previous'] else 1),'managed-epoch-conflict','Epoch must advance exactly once')
            row['public_key']=response['public_key'];row['previous']={k:session[k] for k in ('epoch','checkpoint')};row['pending']=None
            self.commit(data)
            if rid in self.resuming:
                # Reconcile a lost response, then obtain a new process session.
                self.resuming.remove(rid)
                return self.registry(transport,reg,report)
            self.sessions[rid]=session
        response=self.post(transport,reg,f'/api/hosts/{host}/heartbeat/',dict(report,managed_session=session['jti']),host)
        require(response.get('version')==2 and response.get('host_id')==host and response.get('managed_session')==session['jti'],'managed-heartbeat-response','Response binding mismatch')
        # Archive delivery and mirror role execution are intentionally not bridged
        # into legacy path-based writers. No credentials are persisted by this pass.

    def inspect_command(self,registry_id,token,gateway=None):
        """Restricted read-only control, only within a current control session."""
        try:
            self.guard()
            reg=next(r for r in self.bootstrap['registries'] if r['registry_id']==registry_id)
            require(reg['role']=='control','observer-control-denied','Observation registry cannot issue commands')
            session=self.sessions[registry_id]
            key=signatures.public_key(self.saved['registries'][registry_id]['public_key'])
            cmd=protocol.command(token,key,session)
            data=copy.deepcopy(self.saved)
            data['replay']=[r for r in data['replay'] if r['expires']>time.time()]
            require(not any(r['id']==cmd['jti'] for r in data['replay']),'command-replay','Request was already admitted')
            require(len(data['replay'])<128,'command-capacity','Replay journal is full')
            data['replay'].append(dict(id=cmd['jti'],expires=cmd['exp'],status='prepared'))
            self.commit(data)  # Never repeat an uncertain request after interruption.
            self.guard()
            if gateway is None:
                from .gateway import Gateway
                gateway=Gateway()
            result=gateway.inspect(cmd['jti'],cmd['runtime_id'])
            self.guard()
            now=int(time.time())
            require(now<session['exp'],'session-expired','Session expired during inspection')
            return protocol.sign(dict(iss=data['fingerprint'],aud=session['iss'],sub=session['sub'],iat=now,
                exp=min(now+60,session['exp']),jti=cmd['jti'],session_id=session['jti'],result=result),self.key,protocol.RESULT_TYPE)
        except Exception as exc:self.fail(exc)

