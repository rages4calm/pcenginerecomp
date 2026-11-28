"""Authored CD call/return candidates retain exact direct-copy provenance."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from pcerecomp import cd_loads as cd, declarations
from pcerecomp.emitter import emit_declarations
from pcerecomp.native_catalog import load_native_catalog, CD_LOADS_PRODUCER_CONTRACT
from pcerecomp.toc import Toc
from tests.test_cd_loads import MPR, load, digest


class CdLoadCallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def declare(self, raw, *, data_ranges=None, roots=None, mapping=None, **options):
        disc = self.root/'disc.iso'
        disc.write_bytes(bytes(2048) + raw + bytes((-len(raw)) % 2048))
        toc = self.root/'toc.txt'
        toc.write_text(Toc.from_image(disc).text(), encoding='ascii', newline='\n')
        self.images = dict(disc=disc, toc=toc)
        document = dict(format=cd.MAP_FORMAT, schema=1, coordinate=cd.COORDINATE, policy=cd.POLICY,
            media=dict(format='iso', image_sha256=Toc.from_image(disc).image_sha256,
                       toc_sha256=digest(toc.read_bytes())),
            groups=[dict(id='area', mpr=MPR.copy() if mapping is None else mapping,
                         loads=[load('body', 1, raw)], roots=roots or [0x4000])])
        self.document = document
        self.map = self.root/'map.json'
        self.map.write_text(json.dumps(document), encoding='utf-8')
        return cd.declare(self.map, self.root/'declared', **self.images,
                          analysis_policy=cd.ANALYSIS_POLICY, data_ranges=data_ranges, **options)

    def graph(self, admitted):
        return json.loads(admitted.path.read_text())['groups'][0]['analysis']

    def test_call_return_reaches_continuation_with_exact_byte_provenance(self):
        # JSR $4008; LDA #$22; BRA self; data; LDA #$11; RTS.
        admitted = self.declare(bytes.fromhex('200840a92280fe00a91160'),
                                data_ranges=[(0x100007, 1)])
        self.assertEqual({row['pc'] for row in admitted.instructions}, {0x4000,0x4003,0x4005,0x4008,0x400a})
        graph = self.graph(admitted)
        self.assertFalse(graph['unresolved'])
        self.assertEqual(admitted.static_reachability, 'candidates_only')
        self.assertFalse(admitted.source_metadata['routine_closure'])
        for node in graph['nodes']:
            for i, fetch in enumerate(node['fetch']):
                self.assertEqual(fetch, dict(load='body',offset=node['pc']-0x4000+i,
                    disc_byte_offset=2048+node['pc']-0x4000+i))
        self.assertEqual(self.map.read_bytes(), (admitted.path.parent/cd.MAP_NAME).read_bytes())
        self.assertEqual(cd.load(admitted.path,self.images).source_metadata, admitted.source_metadata)

    def test_data_write_is_permitted_but_data_is_never_decoded(self):
        admitted = self.declare(bytes.fromhex('a9018d0a4080fe00000000'),
                                data_ranges=[(0x10000a,1)])
        self.assertEqual({row['pc'] for row in admitted.instructions}, {0x4000,0x4002,0x4005})
        self.assertFalse(self.graph(admitted)['unresolved'])

    def test_code_write_stops_before_following_bytes(self):
        admitted = self.declare(bytes.fromhex('a9018d0540ea80fe'))
        self.assertEqual({row['pc'] for row in admitted.instructions}, {0x4000,0x4002})
        self.assertIn('possible_code_write', {r['reason'] for r in self.graph(admitted)['unresolved']})

    def test_unbound_callee_is_explicit_frontier_without_fake_continuation(self):
        admitted = self.declare(bytes.fromhex('200050a90180fe'))
        self.assertEqual([row['pc'] for row in admitted.instructions], [0x4000])
        self.assertTrue(self.graph(admitted)['unresolved'])

    def test_explicit_data_entry_rejects_before_output(self):
        with self.assertRaises(ValueError):
            self.declare(bytes.fromhex('ea80fe'), data_ranges=[(0x100000,1)])
        self.assertFalse((self.root/'declared').exists())

    def test_stack_edit_does_not_invent_return(self):
        # Even when declared data, stack writes inside a call invalidate proof.
        admitted = self.declare(bytes.fromhex('20064080fe008d002160'),
                                data_ranges=[(0x1f0100,256)])
        pcs = {row['pc'] for row in admitted.instructions}
        self.assertNotIn(0x4003, pcs)
        self.assertIn('stack_write_barrier', {r['reason'] for r in self.graph(admitted)['unresolved']})

    def test_tampered_graph_and_options_cannot_be_admitted(self):
        admitted = self.declare(bytes.fromhex('20064080fe0060'))
        original = admitted.path.read_bytes()
        document = json.loads(original)
        edits = [lambda d:d['analysis'].update(call_depth_limit=True),
                 lambda d:d['analysis'].update(policy='guess'),
                 lambda d:d['analysis'].update(data_ranges=[[0x100000,1]]),
                 lambda d:d['groups'][0]['analysis']['nodes'][0]['fetch'][0].update(offset=3),
                 lambda d:d['analysis'].update(unknown=True)]
        for edit in edits:
            changed = copy.deepcopy(document);edit(changed)
            admitted.path.write_text(json.dumps(changed),encoding='utf-8')
            with self.assertRaises(ValueError):cd.load(admitted.path,self.images)
        admitted.path.write_bytes(original)
        cd.load(admitted.path,self.images)

    def test_new_policy_native_catalog_remains_declared_not_observed(self):
        admitted = self.declare(bytes.fromhex('20064080fe0060'))
        compilation = declarations.load_compilation(admitted.path, source_images=self.images)
        self.assertFalse(compilation.observed_keys)
        self.assertEqual(len(compilation.instructions),3)
        emitted = self.root/'emitted'
        emit_declarations(admitted.path,None,emitted,source_images=self.images)
        # Emission itself re-admits and carries source graph into its catalog.
        catalog = load_native_catalog(emitted/'module.json',admitted.path,source_images=self.images,
                                      producer_contract=CD_LOADS_PRODUCER_CONTRACT)
        self.assertEqual(len(catalog.emitted), 3)

    def test_alternative_group_sources_do_not_leak_into_each_other(self):
        admitted = self.declare(bytes.fromhex('20064080fe0060'))
        document = copy.deepcopy(self.document)
        second = copy.deepcopy(document['groups'][0])
        second.update(id='second', roots=[0x4003])
        document['groups'].append(second)
        self.map.write_text(json.dumps(document),encoding='utf-8')
        alternative = cd.declare(self.map,self.root/'alternative',**self.images,
                                 analysis_policy=cd.ANALYSIS_POLICY)
        groups = json.loads(alternative.path.read_text())['groups']
        self.assertEqual({n['pc'] for n in groups[0]['analysis']['nodes']},{0x4000,0x4003,0x4006})
        self.assertEqual({n['pc'] for n in groups[1]['analysis']['nodes']},{0x4003})
        self.assertEqual({r['group'] for r in alternative.roots},{'area','second'})

    def test_state_limit_is_explicit_and_rederived(self):
        admitted = self.declare(bytes.fromhex('eaeaeaea80fe'),instruction_limit=2)
        self.assertEqual(len(admitted.instructions),2)
        self.assertIn('state_limit',{r['reason'] for r in self.graph(admitted)['unresolved']})
        self.assertEqual(len(cd.load(admitted.path,self.images).instructions),2)

    def test_mapping_change_does_not_fetch_unbound_resident_code(self):
        # A known TAM switches logical page 2 away from this group's loaded RAM.
        admitted = self.declare(bytes.fromhex('a9815304ea80fe'))
        self.assertEqual({row['pc'] for row in admitted.instructions},{0x4000,0x4002})
        self.assertTrue(self.graph(admitted)['unresolved'])

    def test_numeric_options_are_strict_even_without_policy(self):
        for options in (dict(instruction_limit=10000.0),dict(context_limit=256.0),
                        dict(instruction_limit=True),dict(context_limit=True)):
            with self.subTest(options=options),self.assertRaises(ValueError):
                cd.declare(self.root/'absent',self.root/'bad',disc='absent',toc='absent',**options)

    def test_options_require_explicit_policy(self):
        with self.assertRaises(ValueError):
            cd.declare(self.root/'absent',self.root/'bad',disc='absent',toc='absent',call_depth_limit=2)


if __name__ == '__main__':unittest.main()
