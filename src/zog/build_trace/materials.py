"""Source/patch presentation from frozen canonical graphs, never recipe files."""
from collections import Counter
from .model import TraceError, response, paginate, limit_value
from .generations import Reader
from .provenance import comparison_graph
from .summaries import coverage


def resolve(trace, subject, package):
    if isinstance(subject,str) and subject.startswith('generation:'):
        reader=Reader(trace)
        pointer,bundle,report,_=reader.generation(subject[len('generation:'):])
        if pointer is None:
            return None,None,None,reader.finish()
        if report['missing_records']:
            return None,bundle,report,reader.finish()
        records=bundle['records']
        bindings=records[pointer['record']]['data']['packages']
        match=next((b for b in bindings if records[b['output']]['data']['package']==package),None)
        if match is None:
            raise TraceError('not-found','Package is not installed in this generation.')
        prepared=records[match['output']]['data']['attempt']
        inputs=records[prepared]['data']['inputs'] if prepared else None
        return inputs,bundle,report,reader.finish()
    owner,bundle,report,metrics,_=comparison_graph(trace,subject,package)
    return owner.get('inputs') if owner else None,bundle,report,metrics


def availability(inputs,bundle,report):
    if bundle is None:return 'not-captured-or-unavailable'
    if report['missing_records']:return 'incomplete'
    if inputs is None:return 'legacy-inputs-unavailable'
    return 'available'


def rows(bundle, inputs):
    records=bundle['records'];data=records[inputs]['data'];result=[]
    for index,key in enumerate(data['sources']):
        record=records[key];source=record['data']
        result.append(dict(id='source:'+str(index).zfill(8),kind='source',record=key,
            pin=source['pin'],archives=source['archives'],upstream=source['upstream'],
            association=('single-archive-declaration' if len(source['archives'])==1 else 'combined-record-no-per-archive-mapping'),
            gaps=record['gaps']))
    for index,descriptor in enumerate(data['patches']):
        result.append(dict(id='patch:'+str(index).zfill(8),kind='patch',position=index+1,
                           descriptor=descriptor,inputs=inputs))
    return result


def scope(trace,operation,*parts):
    return [trace.scope,str(trace.record_store),trace.record_project_id,operation,*parts]


def inspect_materials(trace,subject,package,*,cursor=None,limit=20):
    limit_value(limit)
    inputs,bundle,report,metrics=resolve(trace,subject,package)
    state=availability(inputs,bundle,report)
    if state!='available':
        return response('materials',subject=subject,package=package,availability=state,
                        coverage=coverage(report) if report else None,inspection=metrics)
    data=bundle['records'][inputs]['data'];items=rows(bundle,inputs)
    page=paginate(items,scope=scope(trace,'materials',subject,package,inputs,bundle['roots']),cursor=cursor,limit=limit)
    return response('materials',subject=subject,package=package,availability=state,inputs=inputs,
        items=page,source_count=len(data['sources']),patch_count=len(data['patches']),
        input_gaps=bundle['records'][inputs]['gaps'],coverage=coverage(report),
        patch_classification='See declared input gaps; descriptors alone do not establish completeness or application.',
        artifact_verification='not-checked',authenticity='not-verified',inspection=metrics,
        interpretation='Frozen declarations; null revisions remain unknown. Archive hashes do not authenticate upstream relationships.')


def changes(left,right):
    """Match only unique declaration labels. Never zip combined archives/upstreams."""
    result=[]
    for kind in ('source','patch'):
        a=[r for r in left if r['kind']==kind];b=[r for r in right if r['kind']==kind]
        def label(row):
            if kind=='patch':return row['descriptor']['name']
            return row['archives'][0]['name'] if len(row['archives'])==1 else None
        ac=Counter(label(r) for r in a);bc=Counter(label(r) for r in b)
        if kind=='patch' and [(r['descriptor'],r['position']) for r in a]==[(r['descriptor'],r['position']) for r in b]:
            continue
        matched=set()
        for x in a:
            name=label(x)
            candidates=[(i,y) for i,y in enumerate(b) if i not in matched and
                        ((kind=='source' and x['record']==y['record']) or
                         (name is not None and ac[name]==1 and bc[name]==1 and label(y)==name))]
            if len(candidates)==1:
                i,y=candidates[0];matched.add(i)
                fields=('pin','archives','upstream','gaps') if kind=='source' else ('descriptor','position')
                diff=[k for k in fields if x[k]!=y[k]]
                if diff:
                    detail={k:dict(before=x[k],after=y[k]) for k in diff}
                    if kind=='patch' and x['descriptor']!=y['descriptor']:
                        detail['descriptor_fields']=[k for k in sorted(x['descriptor'].keys()|y['descriptor'].keys()) if x['descriptor'].get(k)!=y['descriptor'].get(k)]
                    result.append(dict(kind=kind,status='changed',matching='same-record' if kind=='source' and x['record']==y['record'] else 'unique-declared-name',before=x,after=y,changes=detail))
            else:
                result.append(dict(kind=kind,status='removed-declaration',matching='unpaired-or-ambiguous',before=x,after=None))
        for i,y in enumerate(b):
            if i not in matched:
                result.append(dict(kind=kind,status='added-declaration',matching='unpaired-or-ambiguous',before=None,after=y))
    for i,row in enumerate(result):row['id']=str(i).zfill(8)
    return result


def compare_materials(trace,before,after,package,*,cursor=None,limit=20):
    limit_value(limit)
    ai,a,ar,am=resolve(trace,before,package);bi,b,br,bm=resolve(trace,after,package)
    av=availability(ai,a,ar);bv=availability(bi,b,br)
    if av!='available' or bv!='available':
        return response('material-comparison',before=before,after=after,package=package,
            availability='unavailable',before_availability=av,after_availability=bv,
            before_coverage=coverage(ar) if ar else None,after_coverage=coverage(br) if br else None,
            inspection=dict(before=am,after=bm))
    diff=changes(rows(a,ai),rows(b,bi))
    page=paginate(diff,scope=scope(trace,'compare-materials',before,after,package,ai,bi,a['roots'],b['roots']),cursor=cursor,limit=limit)
    return response('material-comparison',before=before,after=after,package=package,availability='available',
        before_inputs=ai,after_inputs=bi,changes=page,change_count=len(diff),
        before_input_gaps=a['records'][ai]['gaps'],after_input_gaps=b['records'][bi]['gaps'],
        before_coverage=coverage(ar),after_coverage=coverage(br),
        artifact_verification='not-checked',authenticity='not-verified',inspection=dict(before=am,after=bm),
        interpretation='Unique names align declarations for presentation only; ambiguous groups stay unpaired. Positions are declared patch order, not application evidence.')
