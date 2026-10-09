"""Starter-package CLI. Each independently initialized workspace owns one host."""
import argparse
import json
from pathlib import Path
import sys

from .workspace import initialize, load, locked
from .provision import Cloud, provision, operate, configuration


def main():
    parser=argparse.ArgumentParser()
    commands=parser.add_subparsers(dest='command',required=True)
    create=commands.add_parser('init')
    create.add_argument('--workspace',required=True)
    create.add_argument('--name',required=True)
    create.add_argument('--profile',default='zog-development')
    create.add_argument('--region',default='us-east-1')
    credentials=commands.add_parser('credentials-import')
    credentials.add_argument('--file',required=True)
    credentials.add_argument('--profile',default='zog-development')
    credentials.add_argument('--destination',default=str(Path.home()/'.aws/credentials'))
    for name in ['doctor','status','start','stop','terminate','provision','run','recover','storage-create','storage-delete','storage-attach','storage-results','storage-fetch','job-submit','job-status','job-collect','job-cancel','checkpoint-export','checkpoint-restore','reboot-submit','reboot-status','reboot-resume','reboot-collect','reboot-abandon','job-publish','install-discover','host-install','discover-status','discover-start','discover-stop']:
        command=commands.add_parser(name)
        command.add_argument('--workspace',required=True)
        if name in {'install-discover','host-install'}:
            command.add_argument('--server-ready',action='store_true',help='Confirm command center pass3 and database migration 0005 are deployed')
            command.add_argument('--python',default='python3.12',help='Target Python >=3.12 executable')
            command.add_argument('--source',help='Directory containing exact pinned host-discover and host-identify source checkouts')
            command.add_argument('--configuration-file',help='Explicit nonsecret daemon JSON configuration')
            command.add_argument('--registry-workspace',help='Explicit command-center workspace for migration identity checks')
            command.add_argument('--server', help='HTTPS command-center origin; otherwise use explicit configuration or preserve the installed server (no default)')
            trust=command.add_mutually_exclusive_group()
            trust.add_argument('--ca-file')
            trust.add_argument('--system-ca',action='store_true')
            command.add_argument('--migrate',action='store_true',help='Migrate an installed reporter within the same command center')
        if name == 'storage-fetch':
            command.add_argument('--id',required=True)
            command.add_argument('--output',required=True)
        if name.startswith('reboot-'):
            command.add_argument('--name', required=True)
        if name == 'reboot-submit':
            command.add_argument('--source', required=True)
            command.add_argument('--recipe', required=True)
        if name in {'reboot-submit','reboot-collect'}:
            command.add_argument('--transfer', choices=['ssm','s3'], default='ssm')
        if name == 'reboot-collect': command.add_argument('--output', required=True)
        if name == 'reboot-resume': command.add_argument('--wait-seconds', type=int, default=900)
        if name in {'job-submit','job-status','job-collect','job-cancel','job-publish'}:
            command.add_argument('--job',required=True)
        if name in {'job-submit','job-collect'}:
            command.add_argument('--transfer',choices=['ssm','s3'],default='ssm')
        if name == 'job-submit':
            command.add_argument('--source',required=True)
            command.add_argument('--recipe',required=True)
        if name == 'job-collect':
            command.add_argument('--output',required=True)
        if name == 'doctor':
            command.add_argument('--remote', action='store_true', help='Inspect tools on an already running host')
        if name in {'stop','terminate'}:
            command.add_argument('--force', action='store_true', help='Explicitly stop active jobs or a host that cannot be inspected')
        if name == 'checkpoint-export':
            command.add_argument('--output', required=True)
            command.add_argument('--handoff', action='store_true', help='Retire this workspace before publishing the checkpoint')
        if name == 'checkpoint-restore':
            command.add_argument('--archive', required=True)
        if name == 'provision':
            command.add_argument('--no-discovery', action='store_true')
            command.add_argument('--registry-configuration', help='JSON overrides for discovery enrollment')
            command.add_argument('--spec',required=True)
            command.add_argument('--dry-run',action='store_true')
        if name == 'terminate':
            command.add_argument('--instance-id',required=True,help='Exact owned instance to delete, including its disk')
        if name == 'run':
            command.add_argument('--source',required=True)
            command.add_argument('--output',required=True)
        if name == 'recover':
            command.add_argument('--manifest',required=True)
    for name in ['lane-prepare','lane-activate','lane-inspect','lane-retire','lane-command']:
        command=commands.add_parser(name)
        command.add_argument('--workspace',required=True)
        command.add_argument('--lane',required=True)
        if name=='lane-prepare':
            command.add_argument('--spec',required=True)
        if name=='lane-command':
            command.add_argument('--request-path',required=True)
    for name in ['artifact-init','artifact-publish','artifact-fetch','artifact-prune']:
        command=commands.add_parser(name)
        command.add_argument('--store',required=True)
        if name in {'artifact-publish','artifact-fetch'}: command.add_argument('--id',required=True)
        if name=='artifact-publish':
            command.add_argument('--source',required=True)
            command.add_argument('--retention-seconds',type=int,default=604800)
        if name=='artifact-fetch': command.add_argument('--output',required=True)
    arguments=parser.parse_args()
    if arguments.command.startswith('lane-'):
        from . import image_build_lanes
        if arguments.command=='lane-prepare':
            specification=json.loads(Path(arguments.spec).read_text())
            if specification.get('lane') != arguments.lane:
                raise ValueError('Lane name differs from specification')
            result=image_build_lanes.prepare(arguments.workspace,specification)
        elif arguments.command=='lane-activate':
            result=image_build_lanes.activate(arguments.workspace,arguments.lane)
        elif arguments.command=='lane-inspect':
            result=image_build_lanes.inspect(arguments.workspace,arguments.lane)
        elif arguments.command=='lane-retire':
            result=image_build_lanes.retire(arguments.workspace,arguments.lane)
        else:
            record=image_build_lanes.inspect(arguments.workspace,arguments.lane)
            result={'argv':image_build_lanes.remote_operation_argv(record,arguments.request_path)}
    elif arguments.command.startswith('artifact-'):
        from . import artifacts
        if arguments.command=='artifact-init':
            artifacts.initialize(arguments.store); result={'initialized':True}
        elif arguments.command=='artifact-publish': result=artifacts.publish(arguments.source,arguments.store,arguments.id,arguments.retention_seconds)
        elif arguments.command=='artifact-fetch': result=artifacts.fetch(arguments.store,arguments.id,arguments.output)
        else: result={'pruned':artifacts.prune(arguments.store)}
    elif arguments.command in {'install-discover','host-install'}:
        from . import discovery
        result=discovery.install(arguments.workspace,registry_directory=arguments.registry_workspace,server=arguments.server,ca_file=arguments.ca_file,configuration_file=arguments.configuration_file,migrate=arguments.migrate,system_ca=arguments.system_ca,server_ready=arguments.server_ready,python=arguments.python,source=arguments.source)
    elif arguments.command.startswith('discover-'):
        from . import discovery
        result=discovery.service(arguments.workspace,arguments.command.removeprefix('discover-'))
    elif arguments.command == 'init':
        result=initialize(arguments.workspace,arguments.name,arguments.profile,arguments.region)
    elif arguments.command == 'credentials-import':
        from .bootstrap import import_credentials
        import_credentials(arguments.file,arguments.destination,arguments.profile)
        result={'profile':arguments.profile,'imported':True}
    elif arguments.command == 'doctor':
        workspace=load(arguments.workspace)
        cloud=Cloud(workspace)
        result={'account_id':cloud.account(),'region':workspace['region'],'workspace_id':workspace['workspace_id']}
        cloud.ec2.describe_instances(MaxResults=5)
        result['ec2_read']='passed'
        from . import diagnostics
        result['local']=diagnostics.local()
        if arguments.remote:
            result['remote']=diagnostics.remote(arguments.workspace)
    elif arguments.command.startswith('reboot-'):
        from . import reboots
        if arguments.command == 'reboot-submit':
            result = reboots.submit(arguments.workspace, arguments.name, arguments.source, json.loads(Path(arguments.recipe).read_text()), arguments.transfer)
        elif arguments.command == 'reboot-resume':
            result = reboots.resume(arguments.workspace, arguments.name, arguments.wait_seconds)
        elif arguments.command == 'reboot-status':
            result = reboots.inspect(arguments.workspace, arguments.name)
        elif arguments.command == 'reboot-abandon':
            result = reboots.abandon(arguments.workspace, arguments.name)
        else:
            result = reboots.collect(arguments.workspace, arguments.name, arguments.output, arguments.transfer)
    elif arguments.command.startswith('checkpoint-'):
        from . import checkpoint
        result = checkpoint.export(arguments.workspace, arguments.output, arguments.handoff) if arguments.command == 'checkpoint-export' else checkpoint.restore(arguments.archive, arguments.workspace)
    elif arguments.command.startswith('job-'):
        from . import jobs
        if arguments.command == 'job-publish':
            result=jobs.publish(arguments.workspace,arguments.job)
        elif arguments.command == 'job-submit':
            result=jobs.submit(arguments.workspace,arguments.job,arguments.source,json.loads(Path(arguments.recipe).read_text()),arguments.transfer)
        elif arguments.command == 'job-cancel':
            result=jobs.cancel(arguments.workspace,arguments.job)
        elif arguments.command == 'job-status':
            result=jobs.inspect(arguments.workspace,arguments.job)
        else:
            result=jobs.collect(arguments.workspace,arguments.job,arguments.output,arguments.transfer)
    elif arguments.command.startswith('storage-'):
        from . import bulk
        with locked(arguments.workspace):
            if arguments.command=='storage-attach': result=bulk.attach(arguments.workspace)
            elif arguments.command=='storage-results': result=bulk.results(arguments.workspace)
            elif arguments.command=='storage-fetch': result=bulk.fetch(arguments.workspace,arguments.id,arguments.output)
            else: result=None
        if arguments.command=='storage-create': result=bulk.create(arguments.workspace)
        elif arguments.command=='storage-delete': result=bulk.delete(arguments.workspace)
    elif arguments.command == 'provision':
        result=provision(arguments.workspace,json.loads(Path(arguments.spec).read_text()),arguments.dry_run,discovery=not arguments.no_discovery,registry_configuration=json.loads(Path(arguments.registry_configuration).read_text()) if arguments.registry_configuration else None)
    elif arguments.command in {'status','start','stop','terminate'}:
        if arguments.command == 'terminate':
            _,host=configuration(arguments.workspace)
            if arguments.instance_id != host['instance_id']:
                raise ValueError('Requested instance does not match workspace host')
        result=operate(arguments.workspace,arguments.command,getattr(arguments,'force',False))
    else:
        # Keep the same local lock through the entire run/recovery operation.
        with locked(arguments.workspace):
            workspace,host=configuration(arguments.workspace)
            Cloud(workspace).owned(host['instance_id'],host['account_id'])
            from .runner import execute,recover
            if arguments.command == 'run':
                execute(host,arguments.source,arguments.output)
            else:
                manifest=json.loads(Path(arguments.manifest).read_text())
                if manifest['host'].get('workspace_id') != workspace['workspace_id']:
                    raise ValueError('Recovery manifest belongs to another workspace')
                recover(host,arguments.manifest)
            result={'completed':True}
    if arguments.command.startswith('reboot-'):
        result={key:result[key] for key in ['name','workflow_id','observed','connection_error','result_path','result_sha256'] if key in result}
    if arguments.command.startswith('job-'):
        result={key:result[key] for key in ['name','job_id','phase','observed','result_path','result_sha256','state','receipt','error'] if key in result}
    print(json.dumps(result,indent=2))

if __name__ == '__main__':
    main()
