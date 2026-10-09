from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from zog.host_discover.box_bridge import BoxBridge, REQUIRED_METHODS, check_control


def bridge(programs, status='observed'):
    result=object.__new__(BoxBridge)
    result.required=['server','refresh-scheduler']
    result.application='archive-mirror'
    result.control=Mock()
    result.control.observe_application_runtime.return_value={'status':status,'programs':programs}
    result.control.cancel_application_launch.return_value=SimpleNamespace(runtime_id='runtime-1')
    return result


def member(name, status='observed', active='active'):
    return {'program':name,'status':status,'observation':{'active_state':active} if status=='observed' else None}


def test_capability_gate_rejects_missing_cancellation_before_lifecycle():
    calls=[]
    control=SimpleNamespace(**{name:lambda: calls.append('called') for name in REQUIRED_METHODS if name!='cancel_application_launch'})
    with pytest.raises(ValueError,match='cancel_application_launch'):check_control(control)
    assert calls==[]
    control.cancel_application_launch=lambda:None
    check_control(control)


@pytest.mark.parametrize('status,active', [('unavailable','active'),('identity-unavailable','active'),('integrity-fault','active'),('observed','activating'),('observed','deactivating')])
def test_uncertainty_cannot_trigger_replacement_or_confirm_stop(status,active):
    b=bridge([member('server'),member('refresh-scheduler',status,active)])
    assert b.running('runtime-1') is None
    with pytest.raises(ValueError,match='Stop not confirmed'):b.stop('request-1','runtime-1')


def test_missing_and_duplicate_members_are_unknown():
    for programs in ([member('server')],[member('server'),member('server'),member('refresh-scheduler')]):
        b=bridge(programs)
        assert b.running('runtime-1') is None
        with pytest.raises(ValueError):b.stop('request-1','runtime-1')


@pytest.mark.parametrize('status,active', [('observed','inactive'),('observed','failed'),('absent','active'),('previous-boot','active')])
def test_confirmed_stopped_runtime_can_finish_withdrawal(status,active):
    b=bridge([member(n,status,active) for n in ['server','refresh-scheduler']])
    assert b.running('runtime-1') is False
    b.stop('request-1','runtime-1')
    b.control.terminate_application_runtime.assert_called_once_with('runtime-1')


def test_stop_resolves_crash_after_accepted_launch_without_new_launch():
    b=bridge([member(n,active='inactive') for n in ['server','refresh-scheduler']])
    b.stop('request-1','')
    b.control.launch_application.assert_not_called()
    b.control.terminate_application_runtime.assert_called_once_with('runtime-1')
    with pytest.raises(ValueError,match='identity mismatch'):b.stop('request-1','different-runtime')


@pytest.mark.parametrize('status', ['pending','uncertain','unknown'])
def test_structured_unresolved_cancellation_never_acknowledges_stop(status):
    b=bridge([member(n,active='inactive') for n in ['server','refresh-scheduler']])
    b.control.cancel_application_launch.return_value={'request_id':'request-1','application':'archive-mirror','status':status,'runtime_id':'runtime-1','operation_id':'operation-1'}
    with pytest.raises(ValueError,match='unresolved'):b.stop('request-1','runtime-1')
    b.control.terminate_application_runtime.assert_not_called()


def test_structured_accepted_cancellation_resolves_lost_launch_reply():
    b=bridge([member(n,active='inactive') for n in ['server','refresh-scheduler']])
    b.control.cancel_application_launch.return_value={'request_id':'request-1','application':'archive-mirror','status':'accepted','runtime_id':'runtime-1','operation_id':'operation-1'}
    b.stop('request-1','')
    b.control.terminate_application_runtime.assert_called_once_with('runtime-1')


def test_structured_cancelled_request_has_no_runtime_to_stop():
    b=bridge([])
    b.control.cancel_application_launch.return_value={'request_id':'request-1','application':'archive-mirror','status':'cancelled','runtime_id':None,'operation_id':None}
    b.stop('request-1','')
    b.control.terminate_application_runtime.assert_not_called()
    with pytest.raises(ValueError):b.stop('request-1','runtime-1')
