"""Bounded read-only canonical joins. Never invoke producer repair or byte verification."""
import json
import re
from .model import TraceError, fact, response, paginate, limit_value
from .source import Snapshot
from .provenance import library


def hex_id(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise TraceError('invalid-query', 'Expected a 64-character generation identity.')
    return value


class Reader:
    def __init__(self, trace):
        if trace.record_store is None or trace.record_project_id is None:
            raise TraceError('invalid-query', 'Provenance requires a trusted record store and project identity.')
        self.trace = trace
        self.lib = library()
        self.owner = Snapshot(trace.root, limits=trace.limits, json_loader=self.lib.loads)
        self.store = Snapshot(trace.record_store, limits=trace.provenance_limits, json_loader=self.lib.loads)

    def identity(self, value):
        from zog.build_record.model import digest
        try:
            digest(value)
        except self.lib.RecordError:
            raise TraceError('invalid-record', 'Invalid canonical record identity.') from None
        return value

    def graph(self, root):
        from zog.build_record.model import references, record_id
        records, missing, stack = {}, set(), [root]
        try:
            while stack:
                key = self.identity(stack.pop())
                if key in records or key in missing:
                    continue
                raw = self.store.read(key[7:] + '.json')
                if raw is None:
                    missing.add(key)
                    continue
                if record_id(raw) != key:
                    raise TraceError('integrity-error', 'Canonical record digest differs.')
                records[key] = raw
                stack.extend(target for target, _ in references(raw))
            bundle = dict(schema_version=1, roots=[root], records=records)
            report = self.lib.inspect(bundle)
            for record in records.values():
                data = record['data']
                if record['kind'] == 'attempt-start':
                    scope = json.loads(data['attempt_id'])
                    if (not isinstance(scope, list) or len(scope) != 4 or
                            scope[:2] != [self.trace.host_id, self.trace.record_project_id] or
                            not isinstance(scope[2], str) or not isinstance(scope[3], str) or
                            not self.trace._permitted('attempt:' + scope[2])):
                        raise TraceError('not-found', 'Provenance is outside the authorized scope.')
                if record['kind'] == 'generation':
                    scope = json.loads(data['generation_id'])
                    if (not isinstance(scope, list) or len(scope) != 3 or
                            scope[:2] != [self.trace.host_id, self.trace.record_project_id]):
                        raise TraceError('not-found', 'Generation is outside the authorized scope.')
                if record['kind'] == 'attempt-result':
                    for locator in data['traces']:
                        if locator['host_id'] != self.trace.host_id or not self.trace._permitted(locator['build_id']):
                            raise TraceError('not-found', 'Trace reference is outside the authorized scope.')
            # Missing records may conceal an unauthorized producing/dependency attempt.
            if missing and self.trace.allowed is not None:
                raise TraceError('not-found', 'Incomplete provenance cannot establish the authorized closure.')
            return bundle, report
        except self.lib.RecordError:
            raise TraceError('invalid-record', 'Canonical provenance is malformed or inconsistent.') from None

    def generation(self, generation):
        hex_id(generation)
        if not self.trace.root.is_dir():
            raise TraceError(
                'source-unavailable',
                'Generation-owner inspection requires the configured image-build state directory.')
        path = 'generations/' + generation + '/manifest.json'
        manifest = self.owner.read(path)
        if manifest is None:
            return None, None, None, path
        if type(manifest.get('schema')) is not int or manifest.get('schema') != 2 or manifest.get('generation') != generation:
            raise TraceError('integrity-error', 'Generation manifest identity differs.')
        pointer = manifest.get('build_record')
        if pointer is None:
            if self.trace.allowed is not None:
                raise TraceError('not-found', 'Legacy generation has no authorized canonical binding.')
            return None, None, None, path
        keys = {'schema','host_id','project_id','generation','build_id','prepared','inputs','record','result','output'}
        if not isinstance(pointer, dict) or set(pointer) != keys or type(pointer['schema']) is not int or pointer['schema'] != 1:
            raise TraceError('invalid-record', 'Unsupported generation owner pointer.')
        if pointer['host_id'] != self.trace.host_id or pointer['project_id'] != self.trace.record_project_id or not self.trace._permitted(pointer['build_id']):
            raise TraceError('not-found', 'Generation is outside the authorized scope.')
        if pointer['generation'] != generation:
            raise TraceError('integrity-error', 'Generation owner identity differs.')
        for name in ('record','prepared','inputs','result','output'):
            self.identity(pointer[name])
        bundle, report = self.graph(pointer['record'])
        records = bundle['records']
        expected = [('record', 'generation'), ('prepared','attempt-start'), ('inputs','build-inputs'),
                    ('result','attempt-result'), ('output','package-output')]
        for key, kind in expected:
            if pointer[key] in records and records[pointer[key]]['kind'] != kind:
                raise TraceError('integrity-error', 'Generation pointer record kind differs.')
        root = records.get(pointer['record'], {}).get('data')
        start = records.get(pointer['prepared'], {}).get('data')
        result = records.get(pointer['result'], {}).get('data')
        inputs = records.get(pointer['inputs'], {}).get('data')
        if root and (root['generation_id'] != json.dumps([self.trace.host_id,self.trace.record_project_id,generation], separators=(',',':')) or root['assembly_result'] != pointer['result']):
            raise TraceError('integrity-error', 'Generation root differs from owner pointer.')
        if start and (start['inputs'] != pointer['inputs'] or json.loads(start['attempt_id'])[3] != '@rootfs-assembly' or 'attempt:' + json.loads(start['attempt_id'])[2] != pointer['build_id']):
            raise TraceError('integrity-error', 'Assembly attempt differs from owner pointer.')
        if result and (result['attempt'] != pointer['prepared'] or result['outputs'] != [pointer['output']]):
            raise TraceError('integrity-error', 'Assembly result differs from owner pointer.')
        if inputs and (inputs['purpose'] != 'assembly' or inputs['options'].get('owner_generation') != generation):
            raise TraceError('integrity-error', 'Assembly inputs differ from generation.')
        return pointer, bundle, report, path

    def finish(self):
        self.owner.finish()
        self.store.finish()
        return dict(owner=self.owner.metrics(), records=self.store.metrics())


def projection(reader, kind, bundle, report, *, cursor, limit, scope, **values):
    rows = [dict(id=key, **value) for key,value in bundle['records'].items()]
    page = paginate(rows, scope=[reader.trace.scope, str(reader.trace.record_store), reader.trace.record_project_id, kind, scope, bundle['roots']], cursor=cursor, limit=limit)
    return response(kind, **values, roots=bundle['roots'], records=page,
        record_projection='redacted inspection; not a canonical record export',
        complete=report['complete'], missing_records=report['missing_records'][:100],
        missing_record_count=len(report['missing_records']), missing_records_truncated=len(report['missing_records'])>100,
        gap_count=len(report['gaps']), record_count=len(rows), artifact_verification='not-checked',
        authenticity='not-verified', evidence_availability='not-checked', inspection=reader.finish())


def generation_provenance(trace, generation, *, cursor=None, limit=20):
    limit_value(limit)
    reader = Reader(trace)
    pointer,bundle,report,path = reader.generation(generation)
    if pointer is None:
        return response('generation-provenance', generation=generation, availability='not-captured-or-unavailable', inspection=reader.finish())
    return projection(reader, 'generation-provenance', bundle, report, cursor=cursor, limit=limit,
                      scope=generation, generation=generation, binding=fact(pointer,path), availability='available')


def read_reused(reader, build_id, package):
    """Read an explicit reused output/result binding; never invent a producing attempt."""
    from .source import component
    trace = reader.trace
    kind, name = trace._identity(build_id)
    if kind != 'attempt':
        raise TraceError('invalid-query', 'Output provenance requires an attempt.')
    trace._attempt(reader.owner, name)
    folder = 'attempts/' + name + '/packages/' + component(package)
    if reader.owner.read(folder + '/provenance.json') is not None:
        raise TraceError('concurrent-change', 'Package provenance appeared during inspection.')
    path = folder + '/result.json'
    result = reader.owner.read(path)
    reference = (result or {}).get('provenance')
    if reference is None:
        return None, None, None, path
    if not isinstance(reference, dict) or set(reference) != {'output','result'}:
        raise TraceError('invalid-record', 'Unsupported reused output reference.')
    reader.identity(reference['output'])
    if reference['result'] is None:
        root = reference['output']
    else:
        root = reader.identity(reference['result'])
    bundle,report = reader.graph(root)
    records = bundle['records']
    output = records.get(reference['output'])
    result_record = records.get(reference['result'])
    if output and (output['kind'] != 'package-output' or output['data']['package'] != package):
        raise TraceError('integrity-error', 'Reused output package differs.')
    if result_record and (result_record['kind'] != 'attempt-result' or result_record['data']['outcome'] != 'succeeded' or reference['output'] not in result_record['data']['outputs']):
        raise TraceError('integrity-error', 'Reused output is not bound to a successful result.')
    if output and reference['result'] is None and output['data']['attempt'] is not None:
        raise TraceError('integrity-error', 'Known producing attempt has no result binding.')
    return reference, bundle, report, path


def reused_provenance(trace, build_id, package, *, cursor=None, limit=20):
    limit_value(limit)
    reader = Reader(trace)
    reference, bundle, report, path = read_reused(reader, build_id, package)
    if reference is None:
        return response('provenance', build_id=build_id, package=package, availability='not-captured', binding=fact(source=path), inspection=reader.finish())
    return projection(reader, 'provenance', bundle, report, cursor=cursor, limit=limit,
                      scope=[build_id,package,'retained-output'], build_id=build_id,package=package,
                      availability='available', binding=fact(reference,path), binding_kind='retained-output',
                      execution_claim='No execution by the inspecting attempt is implied.')


def member_relation(bundle, member):
    records = bundle['records']
    root = records[bundle['roots'][0]]['data']
    installed = {item['output'] for item in root['packages']}
    result = records[root['assembly_result']]['data']
    assembly = set(result['outputs']) | {result['attempt']}
    installed_starts = {records[key]['data']['attempt'] for key in installed}
    if member not in records or records[member]['kind'] not in ('package-output','attempt-start'):
        raise TraceError('integrity-error', 'Indexed member is absent from generation graph.')
    return 'assembly' if member in assembly else 'installed' if member in installed | installed_starts else 'dependency-or-history'


def generations(trace, *, output=None, attempt=None, cursor=None, limit=20):
    if (output is None) == (attempt is None):
        raise TraceError('invalid-query', 'Select exactly one output or attempt-start record ID.')
    limit_value(limit)
    reader = Reader(trace)
    member = reader.identity(output if output is not None else attempt)
    member_bundle, member_report = reader.graph(member)
    record = member_bundle['records'].get(member)
    expected_kind = 'package-output' if output is not None else 'attempt-start'
    if record is not None and record['kind'] != expected_kind:
        raise TraceError('invalid-query', 'Selected member has the wrong canonical record kind.')
    # Do not reveal reverse pointers when original membership scope cannot be established.
    if member_report['missing_records'] or record is None or (expected_kind == 'package-output' and record['data']['attempt'] is None):
        return response('generation-list', availability='member-scope-unavailable', member=member,
                        items=[],has_more=False,next_cursor=None, discovery_completeness='unknown',inspection=reader.finish())
    kind = 'outputs' if output is not None else 'attempts'
    directory = 'build-record/generation-members/' + kind + '/' + member[7:]
    names = reader.owner.names(directory)
    if any(not re.fullmatch('[0-9a-f]{64}\\.json', n) for n in names):
        raise TraceError('invalid-record', 'Malformed generation membership filename.')
    page = paginate([dict(id=n) for n in names], scope=[trace.scope,str(trace.record_store),trace.record_project_id,'generations',kind,member,names],cursor=cursor,limit=limit)
    rows = []
    for item in page['items']:
        value = reader.owner.read(directory + '/' + item['id'])
        if value is None:
            raise TraceError('concurrent-change', 'Generation index disappeared.')
        if value.get('host_id') != trace.host_id or value.get('project_id') != trace.record_project_id:
            raise TraceError('not-found', 'Generation index is outside the authorized scope.')
        if (set(value) != {'schema','host_id','project_id','generation','record','member','relation'} or
                type(value['schema']) is not int or value['schema'] != 1 or value['member'] != member or
                value['record'] != 'sha256:' + item['id'][:-5] or
                value['relation'] not in ('installed','assembly','dependency-or-history')):
            raise TraceError('integrity-error', 'Malformed generation membership binding.')
        pointer,bundle,report,_ = reader.generation(value.get('generation'))
        if pointer is None:
            rows.append(dict(record='sha256:'+item['id'][:-5], availability='generation-unavailable', membership_verified=False))
            continue
        if report['missing_records']:
            rows.append(dict(record=pointer['record'], availability='incomplete', membership_verified=False))
            continue
        relation = member_relation(bundle, member)
        expected = dict(schema=1,host_id=trace.host_id,project_id=trace.record_project_id,generation=pointer['generation'],record=pointer['record'],member=member,relation=relation)
        if value != expected or item['id'] != pointer['record'][7:]+'.json':
            raise TraceError('integrity-error', 'Index differs from canonical generation membership.')
        rows.append(dict(**value,availability='available',membership_verified=True,complete=report['complete'],gap_count=len(report['gaps'])))
    return response('generation-list',member=member,items=rows,has_more=page['has_more'],next_cursor=page['next_cursor'],
        discovery_completeness='unknown', interpretation='Only retained index entries; an empty page does not prove absence of other generations.',
        artifact_verification='not-checked',inspection=reader.finish())
