"""Frozen source/patch presentation, ambiguity, scope, and bounded paging."""
import unittest
import json
import io
from contextlib import redirect_stdout
import test_provenance
import test_generations
from zog.build_trace import TraceError, InspectionLimits
from zog.build_trace.cli import main


@unittest.skipUnless(test_provenance.AVAILABLE,'requires build-record')
class MaterialTests(unittest.TestCase):
    setUp=test_provenance.ProvenanceTests.setUp
    reader=test_provenance.ProvenanceTests.reader
    asset=test_provenance.ProvenanceTests.asset
    put=test_provenance.ProvenanceTests.put
    create=test_provenance.ProvenanceTests.create
    generation=test_generations.GenerationTests.generation

    def captured(self,name,*,patches=None,combined=False,unknown=False,revision='2',source='source'):
        b,path=self.create(name,source=source)
        inputs=self.store.get(b['inputs'])
        src=self.store.get(inputs['data']['sources'][0]);src['data']['upstream'][0]['revision']=None if unknown else revision*40
        if unknown:src['gaps']=['Opaque or unknown revision retained only in recipe materials.']
        if combined:src['data']['archives'].append(self.asset('second','other'))
        selected=self.put('source-selection',src['data'],src['gaps'])
        inputs['data']['sources']=[selected]
        inputs['data']['patches']=patches or []
        iid=self.put('build-inputs',inputs['data'],['Additional transformations not classified.'])
        start=self.store.get(b['prepared']);start['data']['inputs']=iid
        prepared=self.put('attempt-start',start['data'])
        out=self.store.get(b['output']);out['data']['attempt']=prepared
        output=self.put('package-output',out['data'])
        result=self.store.get(b['result']);result['data'].update(attempt=prepared,outputs=[output])
        rid=self.put('attempt-result',result['data'])
        b.update(inputs=iid,prepared=prepared,output=output,result=rid);path.write_text(json.dumps(b))
        return b

    def test_inspection_pages_order_unknown_and_read_only(self):
        self.captured('one',patches=[self.asset('a.patch','a'),self.asset('b.patch','b')],unknown=True)
        before={str(p):p.read_bytes() for p in self.state.rglob('*') if p.is_file()}
        page=self.trace.materials('attempt:one','fixture',limit=1);all_rows=[]
        while True:
            all_rows+=page['items']['items']
            if not page['items']['has_more']:break
            page=self.trace.materials('attempt:one','fixture',limit=1,cursor=page['items']['next_cursor'])
        self.assertEqual([r['position'] for r in all_rows if r['kind']=='patch'],[1,2])
        source=next(r for r in all_rows if r['kind']=='source')
        self.assertIsNone(source['upstream'][0]['revision'])
        self.assertTrue(source['gaps']);self.assertTrue(page['input_gaps'])
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.state.rglob('*') if p.is_file()})

    def test_comparison_revision_hash_and_patch_order(self):
        a=self.asset('a.patch','a');b=self.asset('b.patch','b')
        self.captured('one',patches=[a,b])
        self.captured('two',patches=[b,self.asset('a.patch','changed')],revision='3',source='changed')
        result=self.trace.compare_materials('attempt:one','attempt:two','fixture')
        source=next(r for r in result['changes']['items'] if r['kind']=='source')
        self.assertIn('archives',source['changes']);self.assertIn('upstream',source['changes'])
        patches=[r for r in result['changes']['items'] if r['kind']=='patch']
        self.assertTrue(all('position' in r['changes'] for r in patches))
        self.assertTrue(any('digest' in r['changes'].get('descriptor_fields',[]) for r in patches))

    def test_combined_records_remain_unpaired(self):
        self.captured('one',combined=True);self.captured('two',combined=True,source='changed')
        result=self.trace.compare_materials('attempt:one','attempt:two','fixture')
        self.assertEqual({r['status'] for r in result['changes']['items']},{'added-declaration','removed-declaration'})
        self.assertEqual(self.trace.materials('attempt:one','fixture')['items']['items'][0]['association'],'combined-record-no-per-archive-mapping')

    def test_reuse_and_generation(self):
        b=self.captured('original',patches=[self.asset('a.patch','a')])
        path=self.state/'attempts/reuse/packages/fixture/result.json';path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(provenance=dict(output=b['output'],result=b['result']))))
        self.create=lambda _: (b,None)
        generation,_,_=self.generation(producer='original')
        result=self.trace.compare_materials('attempt:reuse','generation:'+generation,'fixture')
        self.assertEqual(result['change_count'],0)
        self.assertEqual(self.trace.materials('attempt:reuse','fixture')['inputs'],b['inputs'])
        with self.assertRaises(TraceError):self.reader(allowed_build_ids=['attempt:reuse']).materials('attempt:reuse','fixture')

    def test_missing_scope_and_budget(self):
        b=self.captured('one')
        with self.assertRaises(TraceError):self.reader(provenance_limits=InspectionLimits(source_bytes=10)).materials('attempt:one','fixture')
        (self.store.directory/(b['inputs'][7:]+'.json')).unlink()
        self.assertEqual(self.trace.materials('attempt:one','fixture')['availability'],'incomplete')
        with self.assertRaises(TraceError):self.reader(allowed_build_ids=['attempt:one']).materials('attempt:one','fixture')

    def test_cursor_scope_and_redaction(self):
        self.captured('one',patches=[self.asset('token=secretvalue','a')]);self.captured('two')
        first=self.trace.materials('attempt:one','fixture',limit=1)
        self.assertNotIn('secretvalue',json.dumps(first))
        with self.assertRaises(TraceError):self.trace.materials('attempt:two','fixture',cursor=first['items']['next_cursor'])
        with self.assertRaises(TraceError):self.trace.materials('attempt:one','fixture',limit=101)

    def test_empty_patches_and_cli(self):
        self.captured('one')
        view=self.trace.materials('attempt:one','fixture')
        self.assertEqual(view['patch_count'],0)
        self.assertIn('not establish',view['patch_classification'])
        for command in [['materials','attempt:one','fixture'],['compare-materials','attempt:one','attempt:one','fixture']]:
            out=io.StringIO()
            with redirect_stdout(out):
                code=main(['--project-root',str(self.root),'--host-id','host-a','--record-store',str(self.store.directory),'--record-project-id','project-a']+command)
            self.assertEqual(code,0)

    def test_duplicate_patch_names_are_ambiguous(self):
        from zog.build_trace.materials import changes
        old=[dict(id='patch:1',kind='patch',position=1,descriptor=self.asset('same','a'),inputs='x'),dict(id='patch:2',kind='patch',position=2,descriptor=self.asset('same','b'),inputs='x')]
        new=[dict(old[0],position=2),dict(old[1],position=1)]
        self.assertTrue(all(r['matching']=='unpaired-or-ambiguous' for r in changes(old,new)))

    def test_real_declared_source_and_patch_producer(self):
        import ast
        import hashlib
        import importlib.util
        from pathlib import Path
        from zog.build_trace import BuildTrace
        try:
            import zog.image_build as image_build
            from zog.image_build.metadata import identity
            from zog.image_build.provenance import Provenance
            from zog.image_build.source_provenance import NAME
        except ImportError:self.skipTest('requires producer fixtures')
        path=Path(image_build.__file__).resolve().parents[3]/'tests/test_provenance.py'
        if not path.exists():self.skipTest('requires producer source checkout')
        spec=importlib.util.spec_from_file_location('material_owner_fixture',path)
        fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)

        def read_literal(source):
            return ast.literal_eval(source.read_text())

        def declare(s, *, patches=0, kind='git', revision='a'*40):
            recipe=s.root/'package/fixture'
            sources=read_literal(recipe/'sources.py')
            declarations=[]
            for i in range(patches):
                patch=s.root/f'patch-{i}';patch.write_bytes(f'reviewed patch {i}'.encode())
                source=dict(url=patch.as_uri(),sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
                            destination=f'patches/{i}.patch',archive=False)
                sources.append(source)
                declarations.append(dict(
                    id=f'patch-{i}',order=i+1,source=source,
                    applies_to={'version':'1','stage':'final'},
                    files=[dict(path='file',before_sha256=str(i)*64,
                                after_sha256=str(i+1)*64)]))
            (recipe/'sources.py').write_text(repr(sources))
            (recipe/'integration.py').write_text(repr(
                dict(stage_id='final',patches=declarations,patches_complete=True)))
            if patches:
                (recipe/'license.py').write_text(repr(dict(
                    schema=1,package='fixture',version='1',
                    source={key:sources[0][key] for key in ('url','sha256')},
                    status='unresolved',expression=None,scope='Synthetic provenance fixture',
                    evidence=[],components=[],patches=[],
                    notes=['No licensing acceptance claimed.'])))
            value=dict(schema=1,sources=[
                dict(source=source,upstream=[dict(
                    repository='fixture:upstream',revision=revision,revision_type=kind)])
                for source in sources])
            (recipe/NAME).write_text(repr(value))
            monthly=read_literal(s.original)
            monthly['packages']['fixture']['recipes']['stage']=sources
            s.original.write_text(repr(monthly))
            selected=read_literal(recipe.parent/'commit-pin.py')
            selected['packages']['fixture']['sources']=sources
            selected['monthly_identity']=identity(monthly)
            (recipe.parent/'commit-pin.py').write_text(repr(selected))
            s.pin=Provenance.capture_pin(
                s.root/'state',s.original,repository='fixture:catalogue',
                revision='1'*40,repository_path='pins/2026-10-01/commit-pin.py')
            s.provenance=Provenance(
                s.root/'state',host_id='host-a',project_id='project-a',pin=s.pin)
            s.builder=s.reopen()

        s=fixture.Scenario(self.root/'real')
        declare(s,patches=2,kind='opaque',revision='opaque-id')
        generation=s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
        trace=BuildTrace(s.root,host_id='host-a',record_project_id='project-a',
                         record_store=s.provenance.store.directory)
        view=trace.materials('generation:'+generation.generation,'fixture')
        self.assertEqual(view['source_count'],3);self.assertEqual(view['patch_count'],2)
        sources=[r for r in view['items']['items'] if r['kind']=='source']
        self.assertTrue(all(r['upstream'][0]['revision'] is None for r in sources))
        self.assertNotIn('opaque-id',json.dumps(view))
        self.assertTrue(all(r['gaps'] for r in sources))
