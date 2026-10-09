import pytest
from unittest.mock import patch
from zog.host_discover.daemon import validate_configuration, collect, NoRedirect

def configuration():
    return {'server':'https://registry.example.test','host_id':'7379d8d3-257e-4f96-a1ef-7db62c814a81','token':'s'*43,'provider':'generic'}
@pytest.mark.parametrize('server',['http://example.test','https://user:password@example.test','https://example.test/path','https://example.test/?query=1'])
def test_rejects_unsafe_origins(server):
    with pytest.raises(ValueError):validate_configuration(configuration()|{'server':server})
def test_cloud_metadata_must_match_enrollment():
    with patch('zog.host_discover.daemon.metadata',return_value={'cloud':{'instance_id':'other'}}):
        with pytest.raises(ValueError,match='different EC2'):collect(configuration()|{'provider':'aws','cloud':{'instance_id':'original'}})
def test_generic_host_needs_no_cloud_metadata():
    with patch('zog.host_discover.daemon.metadata',side_effect=AssertionError('should not call')):
        assert collect(configuration())['version']==1
def test_redirects_cannot_leak_host_credential():
    with pytest.raises(ValueError,match='Redirects'):NoRedirect().redirect_request(None,None,None,None,None,None)
