"""Read-only joins from scoped image-build pointers into a configured record store."""
import json
from .model import TraceError, fact, paginate, response
from .source import Snapshot, InspectionLimits, component

DEFAULT_LIMITS = InspectionLimits(source_bytes=32*1024*1024, file_bytes=1024*1024,
                                 records=10000, list_source_bytes=16*1024*1024, scan_builds=100)

def library():
    try:
        import zog.build_record as build_record
        return build_record
    except ImportError:
        raise TraceError('dependency-unavailable','Install build-record for provenance inspection.') from None


def binding(trace, snap, build_id, package):
    kind, name = trace._identity(build_id)
    if kind != 'attempt':
        raise TraceError('invalid-query','Package provenance requires an attempt build ID.')
    component(package)
    trace._attempt(snap,name)
    path='attempts/'+name+'/packages/'+package+'/provenance.json'
    raw=snap.read(path)
    if raw is None: return None,path
    if raw.get('schema') != 1:
        raise TraceError('unsupported-schema','Unsupported provenance owner binding.')
    if raw.get('host_id') != trace.host_id or raw.get('project_id') != trace.record_project_id:
        raise TraceError('not-found','Provenance is not available in this scope.')
    if raw.get('build_id') != build_id or raw.get('package') != package:
        raise TraceError('integrity-error','Provenance owner binding differs from requested build/package.')
    expected=json.dumps([trace.host_id,trace.record_project_id,name,package],separators=(',',':'))
    if raw.get('attempt_id') != expected:
        raise TraceError('integrity-error','Provenance attempt identity differs from scope.')
    return raw,path


def read_graph(trace, build_id, package):
    if trace.record_store is None or trace.record_project_id is None:
        raise TraceError('invalid-query','Provenance requires a trusted record store and project identity.')
    lib=library()
    from zog.build_record.model import references, digest, record_id
    source=trace._snapshot()
    owner,path=binding(trace,source,build_id,package)
    if owner is None:
        source.finish()
        return None,None,None,dict(owner=source.metrics()),path
    root=owner.get('result') or owner.get('prepared')
    store=Snapshot(trace.record_store,limits=trace.provenance_limits,json_loader=lib.loads)
    records,missing,stack={},set(),[root]
    try:
        for key in ('prepared','inputs'):
            digest(owner.get(key))
        for key in ('result','output'):
            if owner.get(key) is not None: digest(owner[key])
        if owner.get('result') is None and owner.get('output') is not None:
            raise TraceError('integrity-error','Unfinished provenance cannot bind an accepted output.')
        while stack:
            identity=stack.pop()
            digest(identity)
            if identity in records or identity in missing: continue
            raw=store.read(identity[7:]+'.json')
            if raw is None:
                missing.add(identity);continue
            if record_id(raw) != identity:
                raise TraceError('integrity-error','Provenance record digest mismatch.')
            records[identity]=raw
            stack.extend(target for target,_ in references(raw))
        bundle=dict(schema_version=1,roots=[root],records=records)
        report=lib.inspect(bundle)
        if report['missing_records'] and trace.allowed is not None:
            raise TraceError('not-found','Incomplete provenance cannot establish the authorized closure.')
        start=records.get(owner.get('prepared'))
        if start is not None and (start['kind'] != 'attempt-start' or start['data']['attempt_id'] != owner['attempt_id'] or start['data']['inputs'] != owner['inputs']):
            raise TraceError('integrity-error','Prepared provenance differs from owner binding.')
        inputs=records.get(owner.get('inputs'))
        if inputs is not None and (inputs['kind'] != 'build-inputs' or inputs['data']['package'] != package):
            raise TraceError('integrity-error','Provenance input package differs.')
        if owner.get('result') and root in records:
            result=records[root]
            if result['kind'] != 'attempt-result' or result['data']['attempt'] != owner['prepared'] or result['data']['outputs'] != ([owner['output']] if owner.get('output') else []):
                raise TraceError('integrity-error','Result provenance differs from owner binding.')
        # A closure can include retries/dependencies; narrowing permission must
        # apply to their captured trace locators too, never just the first root.
        for record in records.values():
            if record['kind']=='attempt-start':
                scope=json.loads(record['data']['attempt_id'])
                if (not isinstance(scope,list) or len(scope)!=4 or scope[:2]!=[trace.host_id,trace.record_project_id]
                        or not isinstance(scope[2],str) or not trace._permitted('attempt:'+scope[2])):
                    raise TraceError('not-found','Provenance attempt lies outside the authorized scope.')
            if record['kind']=='attempt-result':
                for locator in record['data']['traces']:
                    if locator['host_id']!=trace.host_id or not trace._permitted(locator['build_id']):
                        raise TraceError('not-found','Provenance closure includes evidence outside this scope.')
        source.finish();store.finish()
        return owner,bundle,report,dict(owner=source.metrics(),records=store.metrics()),path
    except lib.RecordError:
        raise TraceError('invalid-record','Provenance graph is malformed or inconsistent.') from None


def inspect_provenance(trace, build_id, package, *, cursor=None, limit=20):
    owner,bundle,report,metrics,path=read_graph(trace,build_id,package)
    if owner is None:
        from .generations import reused_provenance
        return reused_provenance(trace, build_id, package, cursor=cursor, limit=limit)
    records=bundle['records']
    rows=[dict(id=key,**value) for key,value in records.items()]
    page=paginate(rows,scope=[trace.scope,'provenance',str(trace.record_store),trace.record_project_id,
                             build_id,package,bundle['roots']],cursor=cursor,limit=limit)
    # Graph reports are summarized; full records/gaps are available by record page.
    return response('provenance',build_id=build_id,package=package,availability='available',
        binding=fact(owner,path),roots=bundle['roots'],records=page,record_projection='redacted inspection; not a canonical record export',inspection=metrics,
        record_count=len(records),missing_record_count=len(report['missing_records']),
        missing_records=report['missing_records'][:100],missing_records_truncated=len(report['missing_records'])>100,
        gap_count=len(report['gaps']),complete=report['complete'],
        artifact_count=len(report['artifacts']),artifact_verification='not-checked',authenticity='not-verified',
        evidence_availability='not-checked',
        interpretation='Metadata integrity/relationships checked; completeness is not success or byte verification.')


def comparison_graph(trace, build_id, package):
    owner,bundle,report,metrics,_ = read_graph(trace,build_id,package)
    if owner is not None:
        return owner,bundle,report,metrics,'prepared-pointer'
    from .generations import Reader, read_reused
    reader = Reader(trace)
    reference,bundle,report,_ = read_reused(reader,build_id,package)
    metrics = reader.finish()
    if reference is None:
        return None,None,None,metrics,'not-captured'
    output = bundle['records'].get(reference['output'])
    prepared = output['data']['attempt'] if output else None
    start = bundle['records'].get(prepared)
    owner = dict(reference,prepared=prepared,inputs=start['data']['inputs'] if start else None)
    return owner,bundle,report,metrics,'retained-output'


def compare_provenance(trace, before, after, package):
    left,a,ar,am,ak=comparison_graph(trace,before,package)
    right,b,br,bm,bk=comparison_graph(trace,after,package)
    if left is None or right is None:
        return response('provenance-comparison',before=before,after=after,package=package,
                        availability='not-captured',before_captured=left is not None,after_captured=right is not None)
    if ar['missing_records'] or br['missing_records']:
        return response('provenance-comparison',before=before,after=after,package=package,
                        availability='incomplete',before_missing=ar['missing_records'][:100],after_missing=br['missing_records'][:100])
    if left['inputs'] is None or right['inputs'] is None:
        return response('provenance-comparison',before=before,after=after,package=package,
                        availability='legacy-inputs-unavailable',before_binding=left,after_binding=right,
                        before_binding_kind=ak,after_binding_kind=bk,same_inputs=None,
                        same_output=(left['output']==right['output'] if left.get('output') and right.get('output') else None))
    x=a['records'][left['inputs']]['data'];y=b['records'][right['inputs']]['data']
    def selections(bundle, data):
        return [dict(id=i,**bundle['records'][i]['data']) for i in data['sources']]
    changes=[dict(field=k,before=x[k],after=y[k]) for k in sorted(x) if x[k]!=y[k]]
    return response('provenance-comparison',before=before,after=after,package=package,availability='available',
        same_inputs=left['inputs']==right['inputs'],different_attempt=left['prepared']!=right['prepared'],
        same_output=(left['output']==right['output'] if left.get('output') and right.get('output') else None),
        before_binding_kind=ak,after_binding_kind=bk,
        material_comparison=dict(operation='compare-materials',before=before,after=after,package=package),
        before_binding=left,after_binding=right,changes=changes,
        before_sources=selections(a,x),after_sources=selections(b,y),
        before_gap_count=len(ar['gaps']),after_gap_count=len(br['gaps']),
        inspection=dict(before=am,after=bm),artifact_verification='not-checked',authenticity='not-verified',
        interpretation='Captured producer identities and input differences; selected reuse attempts do not imply fresh execution. No reproducibility, causation or byte-equivalence claim.')
