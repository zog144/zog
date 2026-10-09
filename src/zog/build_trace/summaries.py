"""Ephemeral generation summaries and comparisons of canonical owner graphs."""
import json
from .generations import Reader
from .model import response, paginate, limit_value


def package_rows(bundle, pointer):
    records = bundle['records']
    rows = []
    for binding in records[pointer['record']]['data']['packages']:
        output = records[binding['output']]['data']
        prepared = output['attempt']
        start = records[prepared]['data'] if prepared else None
        inputs = records[start['inputs']]['data'] if start else None
        producer = 'attempt:' + json.loads(start['attempt_id'])[2] if start else None
        rows.append(dict(id=output['package'], package=output['package'], output=binding['output'],
            result=binding['result'], prepared=prepared, inputs=start['inputs'] if start else None,
            producer_build_id=producer,
            relationship_to_assembly=('unknown' if producer is None else
                                      'same-attempt' if producer == pointer['build_id'] else 'different-attempt'),
            source_selections=inputs['sources'] if inputs else None,
            patch_count=len(inputs['patches']) if inputs else None,
            material_details=dict(operation='materials',subject='generation:'+pointer['generation'],package=output['package']),
            recipe=inputs['recipe'] if inputs else None,
            provenance_availability='captured' if start else 'legacy',
            inspection=dict(build_id=producer, package=output['package'])))
    return sorted(rows, key=lambda row: row['id'])


def coverage(report):
    return dict(complete=report['complete'], gap_count=len(report['gaps']),
                gaps=report['gaps'][:20], gaps_truncated=len(report['gaps']) > 20,
                missing_record_count=len(report['missing_records']),
                missing_records=report['missing_records'][:100],
                missing_records_truncated=len(report['missing_records']) > 100)


def summary(trace, generation, *, cursor=None, limit=20):
    limit_value(limit)
    reader = Reader(trace)
    pointer,bundle,report,path = reader.generation(generation)
    if pointer is None:
        return response('generation-summary',generation=generation,availability='not-captured-or-unavailable',inspection=reader.finish())
    if report['missing_records']:
        return response('generation-summary',generation=generation,availability='incomplete',
                        coverage=coverage(report),inspection=reader.finish())
    rows = package_rows(bundle,pointer)
    page = paginate(rows,scope=[trace.scope,str(trace.record_store),trace.record_project_id,
                               'generation-summary',generation,pointer['record']],cursor=cursor,limit=limit)
    root = bundle['records'][pointer['record']]['data']
    return response('generation-summary',generation=generation,record=pointer['record'],availability='available',
        assembly={k:pointer[k] for k in ('build_id','prepared','inputs','output','result')},
        artifact=root['artifact'],content_manifest=root['content_manifest'],
        package_count=len(rows),packages=page,coverage=coverage(report),
        detail=dict(operation='generation-provenance',generation=generation),
        artifact_verification='not-checked',authenticity='not-verified',inspection=reader.finish(),
        interpretation='Installed packages only; different-attempt identifies the original producer, not a new execution or chronological claim.')


def compare(trace, before, after, *, cursor=None, limit=20):
    limit_value(limit)
    reader = Reader(trace)
    left,a,ar,_ = reader.generation(before)
    right,b,br,_ = reader.generation(after)
    if left is None or right is None:
        return response('generation-comparison',before=before,after=after,availability='not-captured-or-unavailable',
                        before_captured=left is not None,after_captured=right is not None,inspection=reader.finish())
    if ar['missing_records'] or br['missing_records']:
        return response('generation-comparison',before=before,after=after,availability='incomplete',
                        before_coverage=coverage(ar),after_coverage=coverage(br),inspection=reader.finish())
    canonical = reader.lib.compare(a,b)
    old = {r['package']:r for r in package_rows(a,left)}
    new = {r['package']:r for r in package_rows(b,right)}
    changed = {r['package']:r for r in canonical['packages']}
    rows=[]
    for name in sorted(old.keys() | new.keys()):
        x,y=old.get(name),new.get(name)
        if x is None: status='added'
        elif y is None: status='removed'
        elif x['output']==y['output']: status='same-output'
        elif x['inputs'] is None or y['inputs'] is None: status='different-output-inputs-unknown'
        elif x['inputs']==y['inputs']: status='same-inputs-different-output'
        else: status='changed-inputs'
        rows.append(dict(id=name,package=name,status=status,before=x,after=y,
                         material_comparison=(dict(operation='compare-materials',before='generation:'+before,after='generation:'+after,package=name) if x and y else None),
                         different_producer=(x['prepared']!=y['prepared'] if x and y and x['prepared'] and y['prepared'] else None),
                         changed_input_fields=changed.get(name,{}).get('changed_input_fields',[])))
    page=paginate(rows,scope=[trace.scope,str(trace.record_store),trace.record_project_id,
                             'generation-comparison',before,after,left['record'],right['record']],cursor=cursor,limit=limit)
    return response('generation-comparison',before=before,after=after,availability='available',
        before_record=left['record'],after_record=right['record'],packages=page,
        package_count=len(rows),changed_package_count=len(canonical['packages']),
        assembly_inputs_changed=canonical['assembly_inputs_changed'],
        before_coverage=coverage(ar),after_coverage=coverage(br),
        artifact_verification='not-checked',authenticity='not-verified',inspection=reader.finish(),
        interpretation='Canonical identity comparison, not byte equivalence, reproducibility, chronological order or causation.')
