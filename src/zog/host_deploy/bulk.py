"""Optional private S3 transfer. Presigned URLs are transient and never printed."""
import json
import hashlib
import os
import re
import tempfile
from pathlib import Path
import shlex

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from .workspace import load, locked, save
from .provision import Cloud


DEFAULT_BUCKET = 'zog-host-deploy-1'


def identifier(value):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', value):
        raise ValueError('Invalid storage identifier')
    return value


def attach(directory, bucket=DEFAULT_BUCKET):
    """Bind an existing bucket without changing its policy or lifecycle."""
    root = Path(directory)
    workspace = load(root)
    account = Cloud(workspace).account()
    s3 = boto3.Session(profile_name=workspace['profile'], region_name=workspace['region']).client('s3')
    response = s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=account)
    settings = {'bucket':bucket, 'account_id':account, 'phase':'ready', 'shared':True,
                'region':response.get('BucketRegion', workspace['region'])}
    path = root/'storage.json'
    if path.exists():
        existing = json.loads(path.read_text())
        if existing != settings:
            raise ValueError('Workspace already has storage settings; use a new workspace')
    save(path, settings)
    return settings


class Bulk:
    def __init__(self,directory):
        self.root=Path(directory)
        self.workspace=load(directory)
        if not (self.root/'storage.json').exists(): attach(self.root)
        self.settings=json.loads((self.root/'storage.json').read_text())
        if self.settings.get('phase') != 'ready': raise ValueError('Storage is not ready')
        session=boto3.Session(profile_name=self.workspace['profile'],region_name=self.settings.get('region',self.workspace['region']))
        self.s3=session.client('s3',config=Config(signature_version='s3v4',connect_timeout=10,read_timeout=60,retries={'total_max_attempts':3}))
        if Cloud(self.workspace).account()!=self.settings['account_id']: raise ValueError('Storage account mismatch')
        if not self.settings.get('shared'):
            tags=self.s3.get_bucket_tagging(Bucket=self.settings['bucket'],ExpectedBucketOwner=self.settings['account_id'])['TagSet']
            if {'Key':'ZogWorkspace','Value':self.workspace['workspace_id']} not in tags: raise ValueError('Storage ownership mismatch')
        self.bucket=self.settings['bucket']
        self.prefix=self.workspace['workspace_id']+'/'

    def send(self,host,path,remote,job_id):
        key=self.prefix+identifier(job_id)+'/source.zip'
        self.s3.upload_file(str(path),self.bucket,key)
        url=self.s3.generate_presigned_url('get_object',Params={'Bucket':self.bucket,'Key':key},ExpiresIn=900)
        # SSM history contains this narrowly scoped 15-minute bearer URL.
        script='import urllib.request,shutil; r=urllib.request.urlopen('+repr(url)+',timeout=60); f=open('+repr(remote)+',"wb"); shutil.copyfileobj(r,f); f.close()'
        host.command('python3 -c '+shlex.quote(script),seconds=300)

    def receive(self,host,remote,path,job_id,metadata=None):
        key=self.prefix+identifier(job_id)+'/results.tar.gz'
        url=self.s3.generate_presigned_url('put_object',Params={'Bucket':self.bucket,'Key':key},ExpiresIn=900)
        # curl streams the file; the URL is passed through a protected config
        # file rather than printed. No AWS keys are installed on the VM.
        code='import subprocess,tempfile,os; f=tempfile.NamedTemporaryFile(mode="w",delete=False); f.write("url = "+'+repr(json.dumps(url))+'+"\\n"); f.close(); r=subprocess.run(["curl","--fail","--silent","--show-error","--max-time","300","--config",f.name,"--upload-file",'+repr(remote)+']); os.unlink(f.name); raise SystemExit(r.returncode)'
        host.command('python3 -c '+shlex.quote(code),seconds=320)
        self.s3.download_file(self.bucket,key,str(path))
        if metadata is not None:
            actual = digest(path)
            if actual != {k:metadata[k] for k in ('bytes','sha256')}:
                raise ValueError('S3 result hash/length mismatch')
            receipt = actual | {'schema':1, 'key':key, 'job_id':job_id}
            self.s3.put_object(Bucket=self.bucket, Key=self.prefix+job_id+'/receipt.json',
                               Body=json.dumps(receipt).encode(), ExpectedBucketOwner=self.settings['account_id'])


    def remove_job_objects(self,job_id):
        for name in ['source.zip','results.tar.gz','receipt.json']:
            self.s3.delete_object(Bucket=self.bucket,Key=self.prefix+identifier(job_id)+'/'+name,ExpectedBucketOwner=self.settings['account_id'])


def create(directory):
    with locked(directory) as root:
        workspace=load(root)
        account=Cloud(workspace).account()
        name='zog-transfer-'+account+'-'+workspace['workspace_id']
        path=root/'storage.json'
        if path.exists():
            existing=json.loads(path.read_text())
            if existing.get('phase')=='ready':
                Bulk(root)
                return existing
            if existing.get('phase')!='denied':
                raise RuntimeError('Storage creation was interrupted; inspect the saved bucket before retrying')
        settings={'bucket':name,'account_id':account,'phase':'creating'}
        save(path,settings)
        session=boto3.Session(profile_name=workspace['profile'],region_name=workspace['region'])
        s3=session.client('s3',config=Config(connect_timeout=10,read_timeout=30,retries={'total_max_attempts':1}))
        arguments={'Bucket':name}
        if workspace['region']!='us-east-1': arguments['CreateBucketConfiguration']={'LocationConstraint':workspace['region']}
        try:
            s3.create_bucket(**arguments)
        except ClientError as error:
            if error.response['Error']['Code']=='AccessDenied':
                settings['phase']='denied'
                save(path,settings)
            raise
        s3.put_bucket_tagging(Bucket=name,Tagging={'TagSet':[{'Key':'ZogWorkspace','Value':workspace['workspace_id']},{'Key':'ManagedBy','Value':'host-deploy'}]})
        s3.put_public_access_block(Bucket=name,PublicAccessBlockConfiguration={k:True for k in ['BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets']})
        s3.put_bucket_encryption(Bucket=name,ServerSideEncryptionConfiguration={'Rules':[{'ApplyServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]})
        s3.put_bucket_lifecycle_configuration(Bucket=name,LifecycleConfiguration={'Rules':[{'ID':'expire-transfers','Status':'Enabled','Filter':{'Prefix':workspace['workspace_id']+'/'},'Expiration':{'Days':1},'AbortIncompleteMultipartUpload':{'DaysAfterInitiation':1}}]})
        settings['phase']='ready'
        save(path,settings)
        return settings


def delete(directory):
    with locked(directory) as root:
        settings=json.loads((root/'storage.json').read_text())
        if settings.get('phase')=='deleted': return settings
        bulk=Bulk(root)
        # Delete only this workspace prefix. Extra objects make bucket deletion fail.
        for page in bulk.s3.get_paginator('list_objects_v2').paginate(Bucket=bulk.bucket,Prefix=bulk.prefix):
            for item in page.get('Contents',[]):
                bulk.s3.delete_object(Bucket=bulk.bucket,Key=item['Key'],ExpectedBucketOwner=bulk.settings['account_id'])
        if not bulk.settings.get('shared'):
            bulk.s3.delete_bucket(Bucket=bulk.bucket,ExpectedBucketOwner=bulk.settings['account_id'])
        settings=bulk.settings|{'phase':'deleted'}
        save(root/'storage.json',settings)
        return settings


def digest(path):
    with Path(path).open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'bytes':Path(path).stat().st_size, 'sha256':checksum}


def results(directory):
    bulk = Bulk(directory)
    found = []
    for page in bulk.s3.get_paginator('list_objects_v2').paginate(
            Bucket=bulk.bucket, Prefix=bulk.prefix, ExpectedBucketOwner=bulk.settings['account_id']):
        for item in page.get('Contents', []):
            relative = item['Key'][len(bulk.prefix):]
            if relative.endswith('/receipt.json') and relative.count('/') == 1:
                found.append(relative.split('/')[0])
    return {'bucket':bulk.bucket, 'results':sorted(found)}


def fetch(directory, job_id, output):
    bulk = Bulk(directory)
    job_id = identifier(job_id)
    key = bulk.prefix+job_id+'/results.tar.gz'
    response = bulk.s3.get_object(Bucket=bulk.bucket, Key=bulk.prefix+job_id+'/receipt.json',
                                  ExpectedBucketOwner=bulk.settings['account_id'])
    with response['Body'] as body:
        receipt = json.loads(body.read(65537))
    if receipt.get('schema') != 1 or receipt.get('key') != key or receipt.get('job_id') != job_id:
        raise ValueError('Invalid result receipt')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.s3-result-', dir=output.parent)
    os.close(descriptor)
    try:
        bulk.s3.download_file(bulk.bucket,key,temporary)
        if digest(temporary) != {k:receipt[k] for k in ('bytes','sha256')}:
            raise ValueError('S3 result hash/length mismatch')
        with open(temporary,'rb') as stream: os.fsync(stream.fileno())
        os.link(temporary,output)
        descriptor = os.open(output.parent,os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        os.unlink(temporary)
    return receipt | {'output':str(output.resolve())}
