"""User-facing summaries retain canonical identities, scope, and explicit unknowns."""
import unittest
import json
import io
from contextlib import redirect_stdout
import test_generations
import test_provenance
from zog.build_trace import TraceError, InspectionLimits
from zog.build_trace.cli import main


@unittest.skipUnless(test_provenance.AVAILABLE,'requires build-record')
class SummaryTests(unittest.TestCase):
    setUp=test_generations.GenerationTests.setUp
    reader=test_generations.GenerationTests.reader
    asset=test_generations.GenerationTests.asset
    put=test_generations.GenerationTests.put
    create=test_generations.GenerationTests.create
    generation=test_generations.GenerationTests.generation

    def second(self,b,*,producer='package'):
        self.create=lambda _: (b,None)
        return self.generation('b',producer=producer,assembly='assembly-two')

    def reused(self,b,name='reuse'):
        path=self.state/'attempts'/name/'packages/fixture/result.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(provenance=dict(output=b['output'],result=b['result']))))

    def test_summary_preserves_identity_without_writes(self):
        g,p,b=self.generation()
        before={str(p):p.read_bytes() for p in self.state.rglob('*') if p.is_file()}
        view=self.trace.generation_summary(g)
        self.assertEqual(view['package_count'],1)
        row=view['packages']['items'][0]
        self.assertEqual(row['prepared'],b['prepared'])
        self.assertEqual(row['producer_build_id'],'attempt:package')
        self.assertEqual(row['relationship_to_assembly'],'different-attempt')
        self.assertEqual(row['output'],b['output'])
        self.assertEqual(view['assembly']['prepared'],p['prepared'])
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.state.rglob('*') if p.is_file()})

    def test_shared_output_comparison(self):
        g,p,b=self.generation();g2,_,_=self.second(b)
        view=self.trace.compare_generations(g,g2)
        self.assertEqual(view['packages']['items'][0]['status'],'same-output')
        self.assertEqual(view['changed_package_count'],0)
        self.assertTrue(view['assembly_inputs_changed'])

    def test_same_inputs_different_producer(self):
        g,p,b=self.generation();other,_=self.create('other')
        g2,_,_=self.second(other,producer='other')
        row=self.trace.compare_generations(g,g2)['packages']['items'][0]
        self.assertEqual(row['status'],'same-inputs-different-output')
        self.assertTrue(row['different_producer'])
        self.assertEqual(row['changed_input_fields'],[])

    def test_changed_recipe_uses_canonical_comparison(self):
        g,p,b=self.generation();other,_=self.create('other',recipe='different')
        g2,_,_=self.second(other,producer='other')
        row=self.trace.compare_generations(g,g2)['packages']['items'][0]
        self.assertEqual(row['status'],'changed-inputs')
        self.assertEqual(row['changed_input_fields'],['recipe'])

    def test_original_to_reused_and_reused_to_reused(self):
        b,_=self.create('original');self.reused(b);self.reused(b,'reuse-two')
        for left,right in [('original','reuse'),('reuse','reuse-two')]:
            view=self.trace.compare_provenance('attempt:'+left,'attempt:'+right,'fixture')
            self.assertTrue(view['same_output']);self.assertTrue(view['same_inputs'])
            self.assertFalse(view['different_attempt'])
            self.assertEqual(view['after_binding_kind'],'retained-output')

    def test_scope_missing_and_budget(self):
        g,p,b=self.generation();g2,_,_=self.second(b)
        with self.assertRaises(TraceError):self.reader(allowed_build_ids=['attempt:assembly']).generation_summary(g)
        with self.assertRaises(TraceError):self.reader(allowed_build_ids=['attempt:package','attempt:assembly']).compare_generations(g,g2)
        with self.assertRaises(TraceError):self.reader(provenance_limits=InspectionLimits(source_bytes=10)).compare_generations(g,g2)
        (self.store.directory/(b['inputs'][7:]+'.json')).unlink()
        self.assertEqual(self.trace.generation_summary(g)['availability'],'incomplete')
        self.assertEqual(self.trace.compare_generations(g,g2)['availability'],'incomplete')

    def test_reused_producer_permissions(self):
        b,_=self.create('original');self.reused(b);self.reused(b,'reuse-two')
        reader=self.reader(allowed_build_ids=['attempt:reuse','attempt:reuse-two'])
        with self.assertRaises(TraceError):reader.compare_provenance('attempt:reuse','attempt:reuse-two','fixture')

    def test_cli_summary_and_compare(self):
        g,p,b=self.generation()
        for command in [['generation-summary',g],['compare-generations',g,g]]:
            output=io.StringIO()
            with redirect_stdout(output):
                status=main(['--project-root',str(self.root),'--host-id','host-a','--record-store',str(self.store.directory),'--record-project-id','project-a']+command)
            self.assertEqual(status,0)
            self.assertIn('packages',json.loads(output.getvalue()))

    def test_legacy_and_missing_reuse_are_not_equal_inputs(self):
        g,p,b=self.generation()
        output=self.put('package-output',dict(package='fixture',attempt=None,artifacts=[self.asset('legacy','bytes')]),gaps=['Unknown original producer'])
        legacy=dict(output=output,result=None)
        self.reused(legacy)
        view=self.trace.compare_provenance('attempt:package','attempt:reuse','fixture')
        self.assertEqual(view['availability'],'legacy-inputs-unavailable')
        self.assertIsNone(view['same_inputs'])
        (self.store.directory/(output[7:]+'.json')).unlink()
        self.assertEqual(self.trace.compare_provenance('attempt:package','attempt:reuse','fixture')['availability'],'incomplete')

    def test_real_multi_package_paging_and_add_remove(self):
        import importlib.util
        import sys
        from pathlib import Path
        from unittest.mock import patch
        from zog.build_trace import BuildTrace
        try:
            import zog.image_build as image_build
            import pytest
        except ImportError:self.skipTest('requires producer fixtures and pytest')
        path=Path(image_build.__file__).resolve().parents[3]/'tests/test_provenance.py'
        if not path.exists():self.skipTest('requires producer source fixtures')
        spec=importlib.util.spec_from_file_location('summary_owner_fixture',path)
        fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        spec=importlib.util.spec_from_file_location('summary_generation_fixture',path.with_name('test_generation_provenance.py'))
        gen=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'test_provenance':fixture}):spec.loader.exec_module(gen)
        scenario=gen.pair(self.root/'multi',runtime=True)
        first=gen.run(scenario)
        second=gen.run(scenario,['dependency'])
        trace=BuildTrace(scenario.root,host_id='host-a',record_project_id='project-a',record_store=scenario.provenance.store.directory)
        page=trace.generation_summary(first.generation,limit=1)
        self.assertEqual(page['package_count'],2)
        next_page=trace.generation_summary(first.generation,limit=1,cursor=page['packages']['next_cursor'])
        self.assertFalse(next_page['packages']['has_more'])
        self.assertNotEqual(page['packages']['items'][0]['id'],next_page['packages']['items'][0]['id'])
        with self.assertRaises(TraceError):trace.generation_summary(second.generation,cursor=page['packages']['next_cursor'])
        comparison=trace.compare_generations(first.generation,second.generation,limit=1)
        comparison2=trace.compare_generations(first.generation,second.generation,limit=1,cursor=comparison['packages']['next_cursor'])
        self.assertEqual({r['status'] for r in comparison['packages']['items']+comparison2['packages']['items']},{'same-inputs-different-output','removed'})
        reverse=trace.compare_generations(second.generation,first.generation)
        self.assertIn('added',[r['status'] for r in reverse['packages']['items']])
        with self.assertRaises(TraceError):trace.compare_generations(second.generation,first.generation,cursor=comparison['packages']['next_cursor'])
        self.assertFalse(page['coverage']['complete'])
        self.assertGreater(page['coverage']['gap_count'],0)
