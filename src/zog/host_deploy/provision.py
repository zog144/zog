"""Provision one independently owned host per workspace, with a saved launch intent."""
import json
from pathlib import Path
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .workspace import locked, load, save


class Cloud:
    def __init__(self, workspace):
        self.workspace = workspace
        session = boto3.Session(profile_name=workspace.get('profile'), region_name=workspace['region'])
        options = Config(connect_timeout=10, read_timeout=30, retries={'mode':'standard','total_max_attempts':3})
        self.ec2 = session.client('ec2', config=options)
        self.sts = session.client('sts', config=options)

    def account(self):
        return self.sts.get_caller_identity()['Account']

    def owned(self, instance_id, account):
        if self.account() != account:
            raise RuntimeError('AWS account differs from the saved workspace host')
        values = self.ec2.describe_instances(InstanceIds=[instance_id])['Reservations']
        instances = [item for reservation in values for item in reservation['Instances']]
        if len(instances) != 1:
            raise RuntimeError('Expected exactly one instance')
        instance = instances[0]
        tags = {tag['Key']:tag['Value'] for tag in instance.get('Tags',[])}
        if tags.get('ManagedBy') != 'host-deploy' or tags.get('ZogWorkspace') != self.workspace['workspace_id']:
            raise RuntimeError('Refusing an instance owned by another workspace or tool')
        return instance


def deadline_script(minutes):
    # Installed by cloud-init on first boot; enabled for subsequent boots.
    return f'''#!/bin/bash
set -eu
cat > /etc/systemd/system/host-deploy-expiry.service <<'UNIT'
[Unit]
Description=Stop development host at its uptime limit
[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl poweroff
UNIT
cat > /etc/systemd/system/host-deploy-expiry.timer <<'UNIT'
[Unit]
Description=Development host uptime limit
[Timer]
OnBootSec={minutes}min
AccuracySec=1s
Unit=host-deploy-expiry.service
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now host-deploy-expiry.timer
'''


def make_request(workspace, specification, token):
    required = {'image_id','instance_type','subnet_id','security_group_id','instance_profile','root_device','volume_gib','maximum_uptime_minutes'}
    if set(specification) - {'lifetime'} != required:
        raise ValueError('Host specification keys must be: '+', '.join(sorted(required)))
    lifetime = specification.get('lifetime','temporary')
    if lifetime not in {'temporary','persistent'}:
        raise ValueError('lifetime must be temporary or persistent')
    if lifetime == 'persistent' and specification['maximum_uptime_minutes'] is not None:
        raise ValueError('Persistent hosts require maximum_uptime_minutes=null')
    ranges = [('volume_gib',8,1024)]
    if lifetime == 'temporary': ranges.append(('maximum_uptime_minutes',10,1440))
    for field, lower, upper in ranges:
        value = specification[field]
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError(field+' is out of range')
    tags = [{'Key':'ManagedBy','Value':'host-deploy'},
            {'Key':'ZogWorkspace','Value':workspace['workspace_id']},
            {'Key':'Project','Value':'Zog'},
            {'Key':'ZogLifetime','Value':lifetime},
            {'Key':'Name','Value':workspace['name'][:100]}]
    request = dict(ImageId=specification['image_id'],InstanceType=specification['instance_type'],MinCount=1,MaxCount=1,
        ClientToken=token,IamInstanceProfile={'Name':specification['instance_profile']},
        NetworkInterfaces=[{'DeviceIndex':0,'SubnetId':specification['subnet_id'],'Groups':[specification['security_group_id']],
                            'AssociatePublicIpAddress':True,'DeleteOnTermination':True}],
        BlockDeviceMappings=[{'DeviceName':specification['root_device'],'Ebs':{'VolumeSize':specification['volume_gib'],
            'VolumeType':'gp3','Encrypted':True,'DeleteOnTermination':True}}],
        MetadataOptions={'HttpTokens':'required','HttpEndpoint':'enabled','HttpPutResponseHopLimit':1},
        InstanceInitiatedShutdownBehavior='stop',
        TagSpecifications=[{'ResourceType':kind,'Tags':tags} for kind in ['instance','volume']],
        UserData=("#!/bin/bash\nset -eu\nprintf 'persistent\\n' > /etc/host-deploy-lifetime\n" if lifetime == 'persistent' else deadline_script(specification['maximum_uptime_minutes'])))
    if specification['instance_type'].split('.')[0] in {'t2','t3','t3a','t4g'}:
        request['CreditSpecification']={'CpuCredits':'standard'}
    return request


def create_host(directory, specification, dry_run=False):
    with locked(directory) as root:
        workspace = load(root)
        cloud = Cloud(workspace)
        account = cloud.account()
        path = root/'launch.json'
        if path.exists():
            intent = json.loads(path.read_text())
            if intent['account_id'] != account or intent['specification'] != specification:
                raise ValueError('Saved launch differs from this account or specification; use another workspace')
            if intent.get('phase') == 'terminated':
                raise RuntimeError('This workspace host was terminated; initialize a new workspace')
        else:
            intent = {'schema':1,'account_id':account,'specification':specification,
                'request':make_request(workspace,specification,uuid.uuid4().hex),'phase':'prepared'}
            save(path,intent)
        if dry_run:
            try:
                cloud.ec2.run_instances(**intent['request'],DryRun=True)
            except ClientError as error:
                if error.response['Error']['Code'] == 'DryRunOperation':
                    return {'dry_run':'authorized','workspace_id':workspace['workspace_id']}
                raise
            raise RuntimeError('Unexpected dry-run response')
        if not intent.get('instance_id'):
            # Discover a launch whose reply or local commit was lost. Never create
            # a new token implicitly, even after the host has been terminated.
            matches=[]
            for page in cloud.ec2.get_paginator('describe_instances').paginate(Filters=[{'Name':'client-token','Values':[intent['request']['ClientToken']]}]):
                matches.extend(item for reservation in page['Reservations'] for item in reservation['Instances'])
            if len(matches)>1:
                raise RuntimeError('More than one instance matches saved launch token')
            if matches:
                instance = matches[0]
                intent['instance_id'] = instance['InstanceId']
            else:
                if intent['phase'] != 'prepared':
                    raise RuntimeError('Launch outcome is unknown and discovery found nothing; refusing automatic replay')
                intent['phase']='submitting'
                save(path,intent)
                response=cloud.ec2.run_instances(**intent['request'])
                intent['instance_id']=response['Instances'][0]['InstanceId']
            intent['phase']='created'
            save(path,intent)
        instance=cloud.owned(intent['instance_id'],account)
        if instance['State']['Name'] in {'terminated','shutting-down'}:
            raise RuntimeError('Saved host is terminated; initialize a new workspace')
        configuration={'region':workspace['region'],'profile':workspace['profile'],'instance_id':intent['instance_id'],
                       'workspace_id':workspace['workspace_id'],'account_id':account}
        if 'lifetime' in specification:
            configuration['lifetime']=specification['lifetime']
        save(root/'host.json',configuration)
        return configuration


def configuration(directory):
    root=Path(directory)
    workspace=load(root)
    host=json.loads((root/'host.json').read_text())
    if host['workspace_id'] != workspace['workspace_id'] or host['region'] != workspace['region']:
        raise RuntimeError('Host description does not belong to this workspace')
    return workspace,host


def operate(directory, action, force=False):
    with locked(directory) as root:
        workspace,host=configuration(root)
        cloud=Cloud(workspace)
        instance=cloud.owned(host['instance_id'],host['account_id'])
        state=instance['State']['Name']
        if action == 'status':
            return {'instance_id':host['instance_id'],'state':state,'workspace_id':workspace['workspace_id'], 'public_dns':instance.get('PublicDnsName',''), 'public_ip':instance.get('PublicIpAddress',''), 'lifetime':host.get('lifetime','temporary')}
        if action == 'start':
            if state not in {'stopped','running','pending'}:
                raise RuntimeError('Host is not stopped, pending, or running')
            try:
                if state == 'stopped':
                    cloud.ec2.start_instances(InstanceIds=[host['instance_id']])
                cloud.ec2.get_waiter('instance_running').wait(InstanceIds=[host['instance_id']],WaiterConfig={'Delay':5,'MaxAttempts':60})
                from .runner import Host
                remote=Host(host)
                remote.online()
                lifetime_check = "test \"$(cat /etc/host-deploy-lifetime)\" = persistent" if host.get('lifetime') == 'persistent' else 'systemctl is-active --quiet host-deploy-expiry.timer'
                remote.command('set -eu\ntimeout 120 cloud-init status --wait\n'+lifetime_check+'\nflock -w 30 /run/host-deploy-control.lock rm -f /run/host-deploy-draining', seconds=150)
            except Exception:
                # Do not interrupt existing work merely because readiness inspection failed.
                if state != 'running':
                    cloud.owned(host['instance_id'],host['account_id'])
                    cloud.ec2.stop_instances(InstanceIds=[host['instance_id']])
                raise
            return {'instance_id':host['instance_id'],'state':'running','expiry_timer':'disabled' if host.get('lifetime')=='persistent' else 'active'}
        if action not in {'stop','terminate'}:
            raise ValueError('Unknown operation')
        if state in {'running', 'pending'} and not force:
            from .runner import Host
            from .jobs import serialized
            remote = Host(host)
            code = Path(__file__).with_name('remote_control.py').read_text().split("if __name__ == '__main__':")[0]
            remote.command(serialized(code + '\ndrain()'))
        if action == 'stop':
            cloud.ec2.stop_instances(InstanceIds=[host['instance_id']])
            target='stopped'
        else:
            cloud.ec2.terminate_instances(InstanceIds=[host['instance_id']])
            target='terminated'
        cloud.ec2.get_waiter('instance_'+target).wait(InstanceIds=[host['instance_id']],WaiterConfig={'Delay':5,'MaxAttempts':60})
        if action == 'terminate':
            intent=json.loads((root/'launch.json').read_text())
            intent['phase']='terminated'
            save(root/'launch.json',intent)
        return {'instance_id':host['instance_id'],'state':target}


def provision(directory, specification, dry_run=False, discovery=True, registry_configuration=None):
    from . import discovery as reporter
    options = registry_configuration or {}
    allowed = {'registry_directory', 'server', 'ca_file', 'configuration_file', 'system_ca', 'server_ready', 'python'}
    if set(options) - allowed:
        raise ValueError('Unknown registry configuration option')
    if discovery and not dry_run and not options.get('server_ready'):
        raise ValueError('Confirm pass3 server readiness in registry configuration before provisioning with discovery')
    if discovery and not dry_run:
        settings,server=reporter.installer_settings(options.get('configuration_file'),options.get('server'))
        if server is None and not settings.get('server'):
            raise ValueError('Explicit server or configuration_file with server required before provisioning with discovery')
    host = create_host(directory, specification, dry_run)
    if dry_run or not discovery:
        return host
    try:
        operate(directory, 'start')
        result = reporter.install(directory, **options)
    except Exception as error:
        # Persist a diagnostic without credentials or provider command output.
        with locked(directory) as root:
            save(root/'discovery-provision.json', {'state':'incomplete', 'instance_id':host['instance_id'],
                 'error_type':type(error).__name__})
        raise RuntimeError('Host '+host['instance_id']+' created; discovery incomplete. Retry provision with the same workspace/specification or install-discover. Cause: '+type(error).__name__) from error
    with locked(directory) as root:
        save(root/'discovery-provision.json', {'state':'installed', 'instance_id':host['instance_id'], 'host_id':result['host_id'], 'enrollment':result.get('enrollment','unknown')})
    return host | {'discovery':result}
