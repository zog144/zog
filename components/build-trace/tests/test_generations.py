"""Canonical fixture consumer checks, including hostile pointers and narrowed scope."""
import json
from pathlib import Path
from unittest.mock import patch
import test_provenance
import unittest
import importlib.util
from zog.build_trace import BuildTrace, TraceError, InspectionLimits
from zog.build_trace.cli import main
from contextlib import redirect_stdout
import io


@unittest.skipUnless(test_provenance.AVAILABLE, 'requires build-record')
class GenerationTests(unittest.TestCase):
    setUp = test_provenance.ProvenanceTests.setUp
    reader = test_provenance.ProvenanceTests.reader
    asset = test_provenance.ProvenanceTests.asset
    put = test_provenance.ProvenanceTests.put
    create = test_provenance.ProvenanceTests.create
    def generation(self, name='a', *, producer='package', assembly='assembly'):
        b,_ = self.create(producer)
        generation = name * 64
        dependencies = [dict(output=b['output'], result=b['result'])]
        inputs = self.put('build-inputs',dict(package='@rootfs-assembly',step='assemble',purpose='assembly',sources=[],recipe=self.asset('recipe','assembly'),patches=[],target='fixture',options={'owner_generation':generation},environment={},materials=[self.asset('assembler','code')],dependencies=dependencies))
        prepared = self.put('attempt-start',dict(attempt_id=json.dumps(['host-a','project-a',assembly,'@rootfs-assembly'],separators=(',',':')),inputs=inputs,prepared_at='2026-10-03T12:00:00Z',retry_of=None))
        artifact=self.asset('rootfs.tar','rootfs');content=self.asset('content.json','inventory')
        output=self.put('package-output',dict(package='@rootfs-assembly',attempt=prepared,artifacts=[artifact,content]))
        result=self.put('attempt-result',dict(attempt=prepared,outcome='succeeded',finished_at='2026-10-03T12:01:00Z',outputs=[output],jobs=[],traces=[dict(host_id='host-a',build_id='attempt:'+assembly)],summary='assembly'))
        record=self.put('generation',dict(generation_id=json.dumps(['host-a','project-a',generation],separators=(',',':')),assembly_result=result,packages=dependencies,artifact=artifact,content_manifest=content,verification=[]))
        pointer=dict(schema=1,host_id='host-a',project_id='project-a',generation=generation,build_id='attempt:'+assembly,prepared=prepared,inputs=inputs,record=record,result=result,output=output)
        path=self.state/'generations'/generation/'manifest.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(dict(schema=2,generation=generation,build_record=pointer)))
        for category,key,relation in [('outputs',b['output'],'installed'),('attempts',b['prepared'],'installed'),('attempts',prepared,'assembly')]:
            index=self.state/'build-record/generation-members'/category/key[7:]/(record[7:]+'.json');index.parent.mkdir(parents=True,exist_ok=True)
            index.write_text(json.dumps(dict(schema=1,host_id='host-a',project_id='project-a',generation=generation,record=record,member=key,relation=relation)))
        return generation,pointer,b

    def test_generation_navigation_and_read_only(self):
        generation,p,b=self.generation()
        before={str(p):p.read_bytes() for p in self.state.rglob('*') if p.is_file()}
        page=self.trace.generation_provenance(generation,limit=2);ids=[]
        while True:
            ids.extend(r['id'] for r in page['records']['items'])
            if not page['records']['has_more']:break
            page=self.trace.generation_provenance(generation,limit=2,cursor=page['records']['next_cursor'])
        self.assertEqual(len(ids),len(set(ids)));self.assertIn(p['record'],ids)
        listing=self.trace.generations(output=b['output'])
        self.assertEqual(listing['items'][0]['relation'],'installed')
        self.assertEqual(listing['discovery_completeness'],'unknown')
        self.assertEqual(self.trace.generations(attempt=p['prepared'])['items'][0]['relation'],'assembly')
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.state.rglob('*') if p.is_file()})
        out=io.StringIO()
        with redirect_stdout(out):
            code=main(['--project-root',str(self.root),'--host-id','host-a','--record-store',str(self.store.directory),'--record-project-id','project-a','generation-provenance',generation])
        self.assertEqual(code,0)

    def test_closure_scope_rejects_hidden_producer(self):
        g,p,b=self.generation()
        reader=self.reader(allowed_build_ids=['attempt:assembly'])
        with self.assertRaises(TraceError):reader.generation_provenance(g)
        with self.assertRaises(TraceError):reader.generations(attempt=p['prepared'])

    def test_missing_graph_and_restricted_scope(self):
        g,p,b=self.generation()
        (self.store.directory/(b['inputs'][7:]+'.json')).unlink()
        result=self.trace.generation_provenance(g)
        self.assertGreater(result['missing_record_count'],0)
        with self.assertRaises(TraceError):self.reader(allowed_build_ids=['attempt:assembly','attempt:package']).generation_provenance(g)

    def test_index_tampering_and_symlink(self):
        g,p,b=self.generation()
        path=self.state/'build-record/generation-members/outputs'/b['output'][7:]/(p['record'][7:]+'.json')
        value=json.loads(path.read_text());value['relation']='assembly';path.write_text(json.dumps(value))
        with self.assertRaises(TraceError):self.trace.generations(output=b['output'])
        path.unlink();path.symlink_to('/etc/passwd')
        with self.assertRaises(TraceError):self.trace.generations(output=b['output'])

    def test_reused_output_preserves_original_scope(self):
        b,_=self.create('original')
        path=self.state/'attempts/reuse/packages/fixture/result.json';path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(schema=1,provenance=dict(output=b['output'],result=b['result']))))
        result=self.trace.provenance('attempt:reuse','fixture')
        self.assertEqual(result['binding_kind'],'retained-output');self.assertEqual(result['roots'],[b['result']])
        with self.assertRaises(TraceError):self.reader(allowed_build_ids=['attempt:reuse']).provenance('attempt:reuse','fixture')

    def test_generation_budget_and_cursor_scope(self):
        g,p,b=self.generation()
        page=self.trace.generation_provenance(g,limit=1)
        restricted=self.reader(allowed_build_ids=['attempt:assembly','attempt:package'])
        with self.assertRaises(TraceError):restricted.generation_provenance(g,cursor=page['records']['next_cursor'])
        with self.assertRaises(TraceError):self.reader(provenance_limits=InspectionLimits(source_bytes=10)).generation_provenance(g)


    def test_multiple_generations_and_stale_cursor(self):
        g,p,b=self.generation()
        # A second generation uses the same original output, without a new producer.
        original_create=self.create
        self.create=lambda name: (b,None)
        g2,p2,_=self.generation('b',assembly='assembly-two')
        self.create=original_create
        first=self.trace.generations(output=b['output'],limit=1)
        second=self.trace.generations(output=b['output'],limit=1,cursor=first['next_cursor'])
        self.assertFalse(second['has_more'])
        self.assertEqual({r['generation'] for r in first['items']+second['items']},{g,g2})
        index=self.state/'build-record/generation-members/outputs'/b['output'][7:]/(p2['record'][7:]+'.json')
        index.unlink()
        with self.assertRaises(TraceError):self.trace.generations(output=b['output'],cursor=first['next_cursor'])

    def test_unavailable_generation_and_unknown_discovery(self):
        g,p,b=self.generation()
        (self.state/'generations'/g/'manifest.json').unlink()
        result=self.trace.generations(output=b['output'])
        self.assertEqual(result['items'][0]['availability'],'generation-unavailable')
        self.assertFalse(result['items'][0]['membership_verified'])
        path=self.state/'build-record/generation-members/outputs'/b['output'][7:]/(p['record'][7:]+'.json')
        path.unlink()
        self.assertEqual(self.trace.generations(output=b['output'])['discovery_completeness'],'unknown')

    def test_real_producer_with_build_only_dependency(self):
        try:
            import zog.image_build as image_build
            import pytest
        except ImportError:
            self.skipTest('requires image-build source and pytest')
        fixture_path=Path(image_build.__file__).resolve().parents[3]/'tests/test_provenance.py'
        if not fixture_path.exists():self.skipTest('requires image-build source fixtures')
        spec=importlib.util.spec_from_file_location('owner_provenance_fixture',fixture_path)
        fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        # Load the owner's generation fixture against its own Scenario, not our module.
        import sys
        generation_path=fixture_path.with_name('test_generation_provenance.py')
        spec=importlib.util.spec_from_file_location('owner_generation_fixture',generation_path)
        generation_fixture=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'test_provenance':fixture}):spec.loader.exec_module(generation_fixture)
        scenario=generation_fixture.pair(self.root/'real',runtime=False)
        selection=generation_fixture.run(scenario)
        trace=BuildTrace(scenario.root,host_id='host-a',record_project_id='project-a',record_store=scenario.provenance.store.directory)
        before={str(p):p.read_bytes() for p in scenario.provenance.root.rglob('*') if p.is_file()}
        view=trace.generation_provenance(selection.generation,limit=100)
        self.assertEqual(view['missing_record_count'],0);self.assertFalse(view['complete'])
        dependency=next(r for r in view['records']['items'] if r['kind']=='package-output' and r['data']['package']=='dependency')
        self.assertEqual(trace.generations(output=dependency['id'])['items'][0]['relation'],'dependency-or-history')
        self.assertEqual(before,{str(p):p.read_bytes() for p in scenario.provenance.root.rglob('*') if p.is_file()})


    def test_pointer_swap_and_digest_tamper(self):
        g,p,b=self.generation()
        path=self.state/'generations'/g/'manifest.json'
        manifest=json.loads(path.read_text());manifest['build_record']['prepared']=b['prepared'];path.write_text(json.dumps(manifest))
        with self.assertRaises(TraceError):self.trace.generation_provenance(g)
        manifest['build_record']=p;path.write_text(json.dumps(manifest))
        record_path=self.store.directory/(p['result'][7:]+'.json')
        record=json.loads(record_path.read_text());record['data']['summary']='tampered';record_path.write_text(json.dumps(record))
        with self.assertRaises(TraceError):self.trace.generation_provenance(g)

    def test_reuse_swapped_result_rejected(self):
        b,_=self.create('original');other,_=self.create('other',source='other')
        path=self.state/'attempts/reuse/packages/fixture/result.json';path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(schema=1,provenance=dict(output=b['output'],result=other['result']))))
        with self.assertRaises(TraceError):self.trace.provenance('attempt:reuse','fixture')

    def test_legacy_and_invalid_query(self):
        g='f'*64
        path=self.state/'generations'/g/'manifest.json';path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(schema=2,generation=g)))
        self.assertEqual(self.trace.generation_provenance(g)['availability'],'not-captured-or-unavailable')
        with self.assertRaises(TraceError):self.reader(allowed_build_ids=[]).generation_provenance(g)
        with self.assertRaises(TraceError):self.trace.generations()
        with self.assertRaises(TraceError):self.trace.generation_provenance('../escape')
        with self.assertRaises(TraceError):self.trace.generation_provenance(g,limit=101)

    def test_generation_retry_history_remains_authorized(self):
        failed,_=self.create('failed',outcome='failed')
        accepted,_=self.create('accepted',previous=failed['result'])
        self.create=lambda name:(accepted,None)
        g,p,b=self.generation(producer='accepted')
        with self.assertRaises(TraceError):
            self.reader(allowed_build_ids=['attempt:accepted','attempt:assembly']).generation_provenance(g)
        full=self.reader(allowed_build_ids=['attempt:failed','attempt:accepted','attempt:assembly']).generation_provenance(g,limit=100)
        self.assertIn(failed['result'],[r['id'] for r in full['records']['items']])
