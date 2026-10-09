"""Persistent role intent. Only a locally configured adapter can execute it."""
import fcntl
import json
import os
import time
import uuid
from pathlib import Path
from zog.host_identify import storage
from zog.host_identify.signatures import origin


def validate(value, now=None):
    now=time.time() if now is None else now
    if not isinstance(value,dict) or set(value)!={'desired','candidates'}:raise ValueError('Invalid roles')
    d=value['desired']
    if not isinstance(d,dict) or set(d)!={'version','revision','selected','endpoint','retain_archives','lease_expires_at'}:raise ValueError('Invalid intent')
    if d['version']!=1 or type(d['revision']) is not int or not 0<=d['revision']<=2**53-1 or type(d['selected']) is not bool or d['retain_archives'] is not True:raise ValueError('Invalid intent')
    if type(d['lease_expires_at']) is not int or not now<d['lease_expires_at']<=now+905:raise ValueError('Invalid lease')
    if d['selected']:origin(d['endpoint'])
    elif d['endpoint']!='':raise ValueError('Invalid inactive endpoint')
    candidates=value['candidates']
    if not isinstance(candidates,list) or len(candidates)>32:raise ValueError('Invalid candidates')
    seen=set();addresses=set()
    for c in candidates:
        if not isinstance(c,dict) or set(c)!={'host_id','endpoint','revision','ready','state'}:raise ValueError('Invalid candidate')
        if str(uuid.UUID(c['host_id']))!=c['host_id'] or c['host_id'] in seen or c['endpoint'] in addresses:raise ValueError('Duplicate candidate')
        origin(c['endpoint'])
        if type(c['ready']) is not bool or type(c['revision']) is not int or c['revision']<1 or c['state'] not in {'assigned','received','blocked','starting','running','ready','stopping','stopped','failed'}:raise ValueError('Invalid candidate status')
        if c['ready'] and c['state']!='ready':raise ValueError('Invalid readiness')
        seen.add(c['host_id']);addresses.add(c['endpoint'])
    return value


class Controller:
    def __init__(self,configuration,adapter=None):
        self.configuration=configuration
        self.root=storage.directory(configuration['identity_directory'])
        self.path=self.root/'mirror-role.json'
        self.adapter=adapter
    def save(self,state):storage.atomic(self.path,json.dumps(state).encode())
    def load(self):return json.loads(storage.read_owned(self.path,0o600)) if self.path.exists() else {}
    def status(self):
        s=self.load()
        return s.get('status',{'revision':0,'state':'stopped','reason':'','runtime_id':''})
    def tick(self,host_id=None,incoming=None,withdraw=False):
        # Independent invocations serialize intent changes, launches, and durable request IDs.
        lock=self.root/'mirror-role.lock'
        fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            storage.read_owned(lock,0o600)
            fcntl.flock(fd,fcntl.LOCK_EX)
            s=self.load()
            if incoming is not None:
                validate(incoming)
                desired=incoming['desired']
                old=s.get('desired')
                if s.get('host_id') not in (None,host_id):raise ValueError('Role belongs to another identity')
                if old and (desired['revision']<old['revision'] or (desired['revision']==old['revision'] and any(desired[k]!=old[k] for k in ('selected','endpoint')))):raise ValueError('Role revision rollback')
                s.update(host_id=host_id,desired=desired,candidates=incoming['candidates'])
                self.save(s)
            if not s:return self.status()
            d=s['desired'];selected=d['selected'] and d['lease_expires_at']>time.time() and not withdraw
            if withdraw:
                d['lease_expires_at']=0;self.save(s)
            def status(state,reason=''):
                s['status']={'revision':d['revision'],'state':state,'reason':reason,'runtime_id':s.get('runtime_id','')}
                self.save(s);return s['status']
            # Publish only accepted monotonic intent while holding the same role lock.
            # Retrying publication on every tick also closes a crash between state and export.
            try:
                from zog.host_identify.mirror_access import save_candidates
                save_candidates(self.configuration['credential_directory'],s['host_id'],{'desired':d,'candidates':s.get('candidates',[])})
            except Exception:
                if selected:return status('blocked','state-unavailable')
                # A failed export must not prevent attempting an already requested stop.
            adapter=self.adapter
            if adapter is None:
                bridge=self.configuration.get('mirror_box_control')
                if not bridge:return status('blocked' if selected or s.get('request_id') else 'stopped','bridge-unconfigured' if selected or s.get('request_id') else '')
                try:
                    from .box_bridge import BoxBridge
                    adapter=BoxBridge(bridge)
                except Exception:return status('blocked','configuration-invalid')
            try:
                if not selected:
                    if s.get('request_id'):
                        # Cancels unstarted work or resolves a crash after acceptance, without launching.
                        adapter.stop(s['request_id'],s.get('runtime_id',''))
                        s.pop('request_id',None);s.pop('runtime_id',None);s.pop('launch_revision',None)
                    return status('stopped','lease-withdrawn' if withdraw else 'lease-expired' if d['selected'] else '')
                if s.get('retry_after',0)>time.time():return status('failed','runtime-failed')
                if not adapter.available():return status('blocked','application-missing')
                # Reconfiguration terminates the exact owned runtime before a new start.
                if s.get('request_id') and s.get('launch_revision')!=d['revision']:
                    adapter.stop(s['request_id'],s.get('runtime_id',''))
                    s.pop('request_id',None);s.pop('runtime_id',None);self.save(s)
                if not s.get('request_id'):
                    s['request_id']=adapter.issue();s['launch_revision']=d['revision'];self.save(s)
                if not s.get('runtime_id'):
                    status('starting')
                    s['runtime_id']=adapter.start(s['request_id']);self.save(s)
                running=adapter.running(s['runtime_id'])
                if running is None:return status('blocked','runtime-unavailable')
                if not running:
                    adapter.stop(s['request_id'],s['runtime_id'])
                    s.pop('request_id',None);s.pop('runtime_id',None)
                    s['failures']=min(s.get('failures',0)+1,5)
                    s['retry_after']=time.time()+min(60*2**(s['failures']-1),900)
                    return status('failed','runtime-failed')
                if not adapter.ready(d['endpoint'],s['host_id'],d['revision']):return status('running','probe-failed')
                s['failures']=0;s.pop('retry_after',None)
                return status('ready')
            except Exception:
                # Never surface application output, private configuration, or arbitrary exception text.
                return status('failed','runtime-failed')
        finally:os.close(fd)
