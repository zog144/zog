import time
import uuid
import pytest
from zog.host_identify import storage,mirror_access
from test_archive_storage import grant,paths,save,ISSUER,AUDIENCE,MIRROR


def test_multiple_elected_mirrors_use_one_scoped_host_token(tmp_path,grant):
    _,shared=paths(tmp_path);key,host,data=grant;save(shared,host,data)
    roles={'desired':{'lease_expires_at':int(time.time())+900},'candidates':[
        {'host_id':str(uuid.uuid4()),'endpoint':'https://one.example.test','revision':1,'ready':True,'state':'ready'},
        {'host_id':str(uuid.uuid4()),'endpoint':'https://two.example.test','revision':1,'ready':False,'state':'assigned'}]}
    mirror_access.save_candidates(shared,host,roles)
    read=lambda operation='download':mirror_access.read_access(shared,{'one':key.public_key()},ISSUER,AUDIENCE,operation,'sources',MIRROR)
    result=read();assert result['endpoints']==['https://one.example.test'];assert result['token']==data['token']
    with pytest.raises(PermissionError):read('upload')
    roles['candidates'][0]['ready']=False;mirror_access.save_candidates(shared,host,roles)
    with pytest.raises(PermissionError):read()
    roles['candidates'][0]['ready']=True;roles['desired']['lease_expires_at']=int(time.time())-1
    mirror_access.save_candidates(shared,host,roles)
    with pytest.raises(PermissionError):read()
    roles['desired']['lease_expires_at']=int(time.time())+900
    mirror_access.save_candidates(shared,str(uuid.uuid4()),roles)
    with pytest.raises(PermissionError):read()
    storage.clear_credentials(shared)
    with pytest.raises(FileNotFoundError):read()
