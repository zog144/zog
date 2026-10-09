"""Asynchronous, fixed-operation transport for station-access deployment jobs.

Submission is deliberately non-retrying. Persist the returned SSM ID; a lost reply
must be resolved through the remote receipt rather than submitting another apply.
"""
import base64
import json
from pathlib import Path
import re
import shlex
import zlib
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


class NotSubmitted(RuntimeError):
    """Validation failed before send_command was called."""


class StationDeployment:
    def __init__(self, target):
        self.target = target
        if not re.fullmatch(r'\d{12}', target['account_id']) or not re.fullmatch(r'i-[0-9a-f]{8,17}',target['instance_id']) or not re.fullmatch(r'[a-z]{2}(?:-[a-z]+)+-\d',target['region']):
            raise NotSubmitted('Invalid AWS target')
        session = boto3.Session(region_name=target['region'])
        options = Config(connect_timeout=5, read_timeout=15, retries={'total_max_attempts':1})
        self.ssm = session.client('ssm', config=options)
        self.ec2 = session.client('ec2', config=options)
        self.sts = session.client('sts', config=options)

    def submit(self, request):
        try:
            if request['target'] != self.target: raise ValueError('target')
            if self.sts.get_caller_identity()['Account'] != self.target['account_id']: raise ValueError('account')
            instance = self.ec2.describe_instances(InstanceIds=[self.target['instance_id']])['Reservations'][0]['Instances'][0]
            tags = {i['Key']:i['Value'] for i in instance.get('Tags',[])}
            if instance['InstanceId'] != self.target['instance_id'] or instance['State']['Name'] != 'running': raise ValueError('instance')
            if tags.get('ZogWorkspace') != self.target['workspace_id'] or not self.target['workspace_id']: raise ValueError('ownership')
            source = Path(__file__).with_name('station_remote.py').read_text()
            source += '\nmain('+repr(request)+')\n'
            payload = base64.b64encode(zlib.compress(source.encode(),9)).decode()
            command = 'python3 -c ' + shlex.quote('import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(payload)+')))')
            if len(command.encode()) > 22000: raise ValueError('payload-size')
        except Exception as error:
            raise NotSubmitted('AWS target or operation preflight failed') from error
        # Exceptions here can mean the command was accepted. Never automatically retry.
        result = self.ssm.send_command(InstanceIds=[self.target['instance_id']], DocumentName='AWS-RunShellScript',
            TimeoutSeconds=60, Parameters={'commands':[command], 'executionTimeout':['60']})
        return result['Command']['CommandId']

    def poll(self, command_id, job_id):
        try:
            result = self.ssm.get_command_invocation(CommandId=command_id,InstanceId=self.target['instance_id'])
        except ClientError as error:
            if error.response['Error']['Code']=='InvocationDoesNotExist': return None
            raise
        if result['Status'] in ('Pending','InProgress','Delayed'): return None
        if result['Status'] != 'Success': return {'status':'uncertain'}
        output = result.get('StandardOutputContent','')
        if len(output)>20000: raise ValueError('Oversized response')
        value = json.loads(output)
        if value.get('schema')!=1 or value.get('id')!=job_id or value.get('status') not in ('inspected','installed','blocked','uncertain','unavailable'):
            raise ValueError('Unrecognized deployment response')
        return value
