"""Optional box-control adapter. No shell, downloaded commands, or host-root fallback."""
import json
import ssl
import urllib.request
from pathlib import Path

REQUIRED_METHODS = (
    'issue_application_request_id', 'launch_application', 'cancel_application_launch',
    'terminate_application_runtime', 'observe_application_runtime',
)


def check_control(control):
    missing = [name for name in REQUIRED_METHODS if not callable(getattr(control, name, None))]
    if missing:
        raise ValueError('Unsupported box-control API: ' + ', '.join(missing))


class BoxBridge:
    def __init__(self,configuration):
        from zog.box_control.api import BoxControl
        from zog.box_control.project import Project
        if set(configuration)-{'project','application','required_programs','ca_file'}:raise ValueError('Invalid bridge configuration')
        path=Path(configuration['project'])
        if not path.is_absolute() or path==Path('/'):raise ValueError('Explicit project required')
        self.control=BoxControl(Project(path))
        check_control(self.control)
        self.application=configuration.get('application','archive-mirror')
        self.required=configuration.get('required_programs',['server','refresh-scheduler'])
        if not self.required or not all(isinstance(x,str) and x for x in self.required) or len(set(self.required))!=len(self.required):raise ValueError('Required programs missing')
        self.ca=configuration.get('ca_file')
    def available(self):
        from zog.box_control.specification import discover_applications
        return self.application in discover_applications(self.control.project.application_dir)
    def issue(self):return self.control.issue_application_request_id()
    def start(self,request_id):return self.control.launch_application(self.application,request_id=request_id).runtime_id
    def stop(self,request_id,runtime_id):
        result=self.control.cancel_application_launch(self.application,request_id=request_id)
        if isinstance(result,dict):
            if result.get('request_id')!=request_id or result.get('application')!=self.application:
                raise ValueError('Cancellation intent mismatch')
            state=result.get('status')
            if state not in {'cancelled','accepted','failed','abandoned'}:
                raise ValueError('Cancellation remains unresolved')
            resolved=result.get('runtime_id')
            if state=='accepted' and not resolved:
                raise ValueError('Accepted cancellation lacks runtime evidence')
            if (state=='cancelled' and resolved) or (runtime_id and not resolved):
                raise ValueError('Cancellation runtime evidence disagrees')
        else:
            # Compatibility with the earlier bundled controller return type.
            resolved=getattr(result,'runtime_id',None)
        if runtime_id and resolved and runtime_id!=resolved:raise ValueError('Runtime identity mismatch')
        target=runtime_id or resolved
        if target:
            self.control.terminate_application_runtime(target)
            observed=self.control.observe_application_runtime(target)
            members={p['program']:p for p in observed['programs']}
            if (observed['status']!='observed' or len(members)!=len(observed['programs'])
                or any(name not in members for name in self.required)
                or any(p['status'] not in ('absent','previous-boot') and
                       (p['status']!='observed' or p['observation']['active_state'] not in ('inactive','failed'))
                       for p in observed['programs'])):
                raise ValueError('Stop not confirmed')
    def running(self,runtime_id):
        result=self.control.observe_application_runtime(runtime_id)
        if result['status']!='observed':return None
        programs=result['programs']
        members={p['program']:p for p in programs}
        if len(members)!=len(programs) or any(name not in members for name in self.required):
            return None
        states=[]
        for name in self.required:
            member=members[name]
            if member['status'] in ('absent','previous-boot'):
                states.append(False)
            elif member['status']=='observed':
                active=member['observation']['active_state']
                if active in ('inactive','failed'):states.append(False)
                elif active=='active':states.append(True)
                else:return None  # Starting/stopping is not proof of failure.
            else:return None
        return all(states)
    def ready(self,endpoint,host_id,revision):
        from .daemon import NoRedirect
        from zog.host_identify.signatures import origin
        opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=self.ca)))
        with opener.open(origin(endpoint)+'/.well-known/zog/archive-mirror/ready',timeout=5) as r:
            raw=r.read(4097)
            if r.status!=200 or len(raw)>4096:return False
            value=json.loads(raw)
        return value=={'version':1,'host_id':host_id,'role_revision':revision,'serving':True,'scheduler_running':True}
