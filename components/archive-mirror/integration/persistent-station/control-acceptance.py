import json,sys,os
from pathlib import Path
from dataclasses import asdict
from box_control.api import BoxControl
from box_control.project import Project
from box_control.images import ImageSelection
from box_control.runtime.root_control import RootControlSystemdTransport
project=Project(Path(os.environ.get('ZOG_ACCEPTANCE_PROJECT','/var/lib/zog-archive-acceptance/project')))
class FixtureProvider:
 def ensure(self,project):
  generation='archive-python-fixture-v2'
  return ImageSelection(generation,project.rootfs_dir/'generations'/generation/'root',{'fingerprint':generation,'packages':{}},reused=True)
 def preview(self,project):return self.ensure(project)
control=BoxControl(project,image_provider=FixtureProvider(),systemd_transport=RootControlSystemdTransport(Path('/run/zog-archive-acceptance/root-control.sock'),timeout_seconds=90))
operation=sys.argv[1]
if operation=='prepare':result=control.prepare_application('station-access')
elif operation=='refresh':result=control.refresh_application_preparation('station-access')
elif operation=='inspect':result=control.application_preparation('station-access')
elif operation=='launch':
 request=control.issue_application_request_id()
 result=asdict(control.launch_application('station-access',request_id=request))
elif operation=='observe':result=control.observe_application_runtime(sys.argv[2])
elif operation=='stop':result=asdict(control.terminate_application_runtime(sys.argv[2]))
elif operation=='queue-cancel':
 request=control.issue_application_request_id()
 control.request_application_launch('station-access',request_id=request)
 result=control.cancel_application_launch('station-access',request_id=request)
 assert result['status']=='cancelled' and result['runtime_id'] is None
elif operation=='cancel':result=control.cancel_application_launch('station-access',request_id=sys.argv[2])
else:raise SystemExit('Unknown operation')
print(json.dumps(result,default=str))
