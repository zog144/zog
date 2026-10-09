"""Retained installed-test reports; commands and logs stay with execution owners."""
import json
import hashlib
from pathlib import Path

from .errors import ImageBuildError
from .filesystem import inventory
from .metadata import identity

CONTRACT = 'image-build-installed-verification-v1'
NAME = 'installed-verification.json'


def _read(path):
    if path.is_symlink():
        raise ImageBuildError('installed verification evidence must not be a symlink')
    return json.loads(path.read_bytes())


def _require(condition, message):
    if not condition:
        raise ImageBuildError(message)


def _subject(p, binding, root, owner_inputs):
    _require(owner_inputs.get('verification_report_contract') == CONTRACT,
             'installed verification report contract was not frozen')
    _require(identity(owner_inputs) == binding['generation'],
             'installed verification owner inputs differ')
    return dict(schema=1, kind=CONTRACT,
        generation_id=json.dumps([p.host_id, p.project_id, binding['generation']], separators=(',', ':')),
        assembly_attempt=binding['prepared'], check=owner_inputs.get('verification_check', 'installed-trust'),
        root_inventory_digest='sha256:'+identity(inventory(root)),
        commands_digest='sha256:'+identity([['/bin/bash','-eu','-c',owner_inputs['verification_command']]]),
        policy_digest='sha256:'+identity(owner_inputs['execution_policy']))


def _execution(value):
    _require(type(value.get('exit_code')) is int and value['exit_code'] == 0
             and value.get('cleanup_complete') is True,
             'installed verification lacks successful cleaned-up completion')
    for key in ('runtime_id', 'invocation_id', 'journal_reference'):
        _require(isinstance(value.get(key), str) and bool(value[key]),
                 'installed verification lacks execution identity')
    return {key:value[key] for key in ('runtime_id','invocation_id','journal_reference',
                                      'exit_code','cleanup_complete')}


def capture(p, binding, root, owner_inputs, verification_attempt, execution):
    """Capture only completed evidence for exactly the candidate that was tested."""
    folder = Path(verification_attempt)
    subject = _subject(p, binding, root, owner_inputs)
    prepared = _read(folder/'prepared.json')
    completed = _read(folder/'verification.json')
    checkpoint = _read(folder/'command-0.execution.json')
    commands = [['/bin/bash','-eu','-c',owner_inputs['verification_command']]]
    _require(prepared == dict(root=inventory(root), binding=owner_inputs, commands=commands),
             'installed verification candidate or frozen inputs changed')
    _require(completed == dict(outputs=inventory(folder/'output'), policy=owner_inputs['execution_policy']),
             'installed verification outputs or policy changed')
    _require(checkpoint == execution and execution.get('policy') == (owner_inputs['execution_policy'] or {}).get('controller'),
             'installed verification completion differs')
    request = execution.get('request', {})
    _require(request.get('command') == commands[0]
             and request.get('root') == str((folder/'root').resolve())
             and request.get('source') == str((folder/'source').resolve())
             and request.get('output') == str((folder/'output').resolve())
             and request.get('read_only_root') is True
             and request.get('network_access') is False
             and request.get('timeout_seconds') == owner_inputs['execution_policy']['execution_timeout_seconds'],
             'installed verification request differs')
    report = dict(subject, outcome='succeeded', execution=dict(host_id=p.host_id, **_execution(execution)),
                  trace=dict(host_id=p.host_id, build_id='attempt:'+folder.name),
                  request_digest='sha256:'+identity(request))
    return p._bytes(NAME, report)


def validate(p, binding, root, owner_inputs, reports, *, execution=None):
    """Producer semantics layered over build-record's artifact/hash validation."""
    contract = owner_inputs.get('verification_report_contract')
    if contract is None:
        _require(not reports, 'cannot retrofit installed verification onto a legacy assembly')
        return
    _require(contract == CONTRACT and len(reports) == 1,
             'frozen installed verification report is required')
    descriptor = reports[0]
    _require(descriptor.get('name') == NAME, 'installed verification report descriptor differs')
    # The caller verifies descriptor bytes through canonical build-record before
    # accepting a generation. Reading here never follows a report-supplied locator.
    from zog.build_record.model import artifact
    artifact(descriptor)
    path = p.root/'artifacts'/descriptor['digest'][7:]
    _require(not path.is_symlink(), 'installed verification report must not be a symlink')
    with path.open('rb') as stream:
        raw = stream.read(65537)
    _require(len(raw) <= 65536 and len(raw) == descriptor['size']
             and 'sha256:'+hashlib.sha256(raw).hexdigest() == descriptor['digest'],
             'installed verification report bytes differ')
    report = json.loads(raw)
    subject = _subject(p, binding, root, owner_inputs)
    _require(set(report) == set(subject) | {'outcome','execution','trace','request_digest'}
             and all(report.get(k) == v for k,v in subject.items())
             and report['outcome'] == 'succeeded',
             'installed verification report subject differs')
    evidence = report['execution']
    _require(isinstance(evidence, dict) and set(evidence) ==
             {'host_id','runtime_id','invocation_id','journal_reference','exit_code','cleanup_complete'}
             and evidence['host_id'] == p.host_id, 'installed verification execution scope differs')
    _execution(evidence)
    trace = report['trace']
    _require(isinstance(trace,dict) and set(trace) == {'host_id','build_id'}
             and trace['host_id'] == p.host_id and isinstance(trace['build_id'],str)
             and trace['build_id'].startswith('attempt:') and len(trace['build_id']) > 8,
             'installed verification trace scope differs')
    from zog.build_record.model import digest
    digest(report['request_digest'])
    if execution is not None:
        _require(evidence == dict(host_id=p.host_id, **_execution(execution))
                 and report['request_digest'] == 'sha256:'+identity(execution.get('request'))
                 and execution.get('policy') == owner_inputs['execution_policy'].get('controller'),
                 'installed verification owner execution differs')
