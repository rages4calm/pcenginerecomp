"""Authored symbolic return-word transfers, never caller-declared summaries."""
import unittest
from unittest.mock import patch

from pcerecomp import ram_cd_analysis as analysis
from tests.test_ram_cd_analysis import Source, MPR, canonical


def run(source, *, entries=None, mapping=MPR, depth=8, limit=200, contexts=16, far=True):
    return analysis.derive([0x4000] if entries is None else entries, mapping,
        fetch=source.fetch, is_code=source.code, is_ram=source.ram,
        canonical=canonical,
        instruction_limit=limit,context_limit=contexts,call_depth_limit=depth,far_calls=far)


def pcs(result):return {row['pc'] for row in result[1]}
def reasons(result):return {row['reason'] for row in result[0]['unresolved']}


class FarCallTests(unittest.TestCase):
    def far_source(self, thunk='7A FA DA 5A A9 82 53 08 A9 5F 48 A9 FF 48 60'):
        return Source([(0x100000,'20 10 40 A9 77 80 FE'),
            (0x100010,thunk),(0x104000,'A9 99 60')])

    def test_actual_popped_return_word_and_synthesized_banked_transfer(self):
        source=self.far_source();result=run(source)
        self.assertIn(0x6000,pcs(result));self.assertIn(0x4003,pcs(result))
        self.assertFalse(result[0]['unresolved'])
        transfers=[edge for edge in result[0]['edges'] if 'return_word' in edge]
        self.assertEqual([(e['kind'],e['target']['pc']) for e in transfers],
            [('reconstructed_return',0x6000),('return',0x4003)])
        first,last=transfers
        self.assertFalse(first['return_word']['matched_call'])
        self.assertEqual(first['return_word']['high']['value'],0x5F)
        self.assertEqual(first['return_word']['low']['value'],0xFF)
        self.assertEqual(first['return_word']['low']['origin']['kind'],'immediate')
        self.assertEqual(last['return_word']['low']['origin']['kind'],'return-low')
        self.assertEqual(last['return_word']['low']['origin']['data'],[0x20,0x10,0x40])
        self.assertTrue(last['return_word']['matched_call'])
        self.assertEqual(last['target']['mpr'][3],0x82)
        self.assertEqual(last['target']['registers'][0],0x99)
        self.assertEqual(result,run(source))

    def test_legacy_saved_word_pop_barrier_is_unchanged(self):
        source=self.far_source();result=run(source,far=False)
        self.assertEqual(pcs(result),{0x4000,0x4010})
        self.assertEqual(reasons(result),{'stack_return_word_pop'})
        kwargs=dict(fetch=source.fetch,is_code=source.code,is_ram=source.ram,
            canonical=canonical,
            instruction_limit=200,context_limit=16,call_depth_limit=8)
        self.assertEqual(result,analysis._derive_plain([0x4000],MPR,**kwargs))

    def test_known_stack_word_without_call_is_reconstructed_only(self):
        result=run(Source([(0x100000,'A9 40 48 A9 0F 48 60'),(0x100010,'80 FE')]))
        edge=next(e for e in result[0]['edges'] if e['kind']=='reconstructed_return')
        self.assertFalse(edge['return_word']['matched_call']);self.assertEqual(edge['target']['pc'],0x4010)
        self.assertEqual(edge['target']['frames'],[])

    def test_equal_numeric_overwrite_does_not_preserve_call_word_origin(self):
        for caller,thunk,continuation,kind in (
                (0x40FE,'68 62 48 60',0x4101,'clear'),
                (0x40FD,'68 43 01 48 60',0x4100,'mapping-read')):
            source=Source([(0x100000+(caller-0x4000),'20 10 41'),
                (0x100110,thunk),(0x100000+(continuation-0x4000),'80 FE')])
            result=run(source,entries=[caller]);edge=next(e for e in result[0]['edges'] if 'return_word' in e)
            self.assertEqual(edge['target']['pc'],continuation)
            self.assertEqual(edge['kind'],'reconstructed_return')
            self.assertFalse(edge['return_word']['matched_call'])
            self.assertEqual(edge['return_word']['low']['origin']['kind'],kind)

    def test_unknown_stack_bytes_and_unbound_destination_stop(self):
        for code,reason in [('48 48 60','unknown_return_word'),('60','unproven_return_word'),('68','unproven_stack_pop')]:
            with self.subTest(code=code):self.assertIn(reason,reasons(run(Source([(0x100000,code)]))))
        source=Source([(0x100000,'A9 60 48 A9 10 48 60')]);result=run(source)
        self.assertIn('outside_allowed_code',reasons(result));self.assertNotIn(0x6011,pcs(result))

    def test_mapping_unknown_or_stack_mapping_incompatible_stops(self):
        self.assertIn('unknown_mapping_value',reasons(run(self.far_source('A5 40 53 08 60'))))
        self.assertIn('unsupported_stack_mapping',reasons(run(self.far_source('A9 80 53 02 60'))))

    def test_wram_stack_alias_mapping_preserves_real_saved_bytes(self):
        result=run(self.far_source('A9 F9 53 02 60'))
        edge=next(e for e in result[0]['edges'] if e['kind']=='return')
        self.assertEqual(edge['target']['pc'],0x4003)
        self.assertEqual(edge['target']['mpr'][1],0xF9)

    def test_changed_source_recomputes_far_target_and_origin(self):
        chunks=[(0x101000,'80 FE'),(0x102000,'80 FE')]
        first=run(Source([(0x100000,'A9 4F 48 A9 FF 48 60')]+chunks))
        second=run(Source([(0x100000,'A9 5F 48 A9 FF 48 60')]+chunks))
        self.assertIn(0x5000,pcs(first));self.assertNotIn(0x6000,pcs(first))
        self.assertIn(0x6000,pcs(second));self.assertNotIn(0x5000,pcs(second))
        for result,value in ((first,0x4F),(second,0x5F)):
            edge=next(e for e in result[0]['edges'] if 'return_word' in e)
            self.assertEqual(edge['return_word']['high']['origin']['data'],[0xA9,value])

    def test_direct_and_mirrored_stack_stores_remain_barriers(self):
        for thunk in ('8D 00 21 60','A9 F8 53 10 8D 00 81 60'):
            with self.subTest(thunk=thunk):
                self.assertIn('stack_write_barrier',reasons(run(self.far_source(thunk))))
        self.assertIn('stack_pointer_write_barrier',reasons(run(self.far_source('A2 FF 9A 60'))))

    def test_source_code_store_and_unknown_indirect_write_remain_barriers(self):
        self.assertIn('possible_code_write',reasons(run(self.far_source('8D 00 40 60'))))
        self.assertIn('unknown_write_target',reasons(run(self.far_source('91 40 60'))))

    def test_absolute_stack_load_requires_analyzed_txs_and_live_known_cell(self):
        # Establish SP=$FF, push caller word $4005, read the actual low cell via
        # TSX/$2101,X, then use that known cell to select an authenticated bank.
        source=Source([(0x100000,'A2 FF 9A 20 10 40 80 FE'),
            (0x100010,'BA BD 01 21 AA 60')])
        result=run(source);node=next(n for n in result[0]['nodes'] if n['pc']==0x4006)
        self.assertEqual(node['registers'][0],0x05);self.assertEqual(node['registers'][1],0x05)
        self.assertEqual(node['stack_pointer'],255)
        without=run(Source([(0x100000,'20 10 40 80 FE'),(0x100010,'BA BD 01 21 60')]))
        node=next(n for n in without[0]['nodes'] if n['pc']==0x4003)
        self.assertIsNone(node['registers'][0]);self.assertIsNone(node['registers'][1])

    def test_page_crossed_or_unowned_stack_read_does_not_read_snapshot_constants(self):
        # Root SP=0; stack writes wrap, but absolute indexed addresses do not.
        source=Source([(0x100000,'A2 00 9A 20 10 40 80 FE'),
            (0x100010,'BA BD 02 21 60'),(0x1F0200,'99')])
        result=run(source);node=next(n for n in result[0]['nodes'] if n['pc']==0x4006)
        self.assertIsNone(node['registers'][0])
        wrapped=run(Source([(0x100000,'A2 00 9A 20 10 40 80 FE'),(0x100010,'BA BD 01 21 60')]))
        node=next(n for n in wrapped[0]['nodes'] if n['pc']==0x4006)
        self.assertEqual(node['registers'][0],0x05);self.assertEqual(node['stack_pointer'],0)

    def test_stack_capacity_is_a_real_bound_even_without_calls(self):
        source=Source([(0x100000,('A9 44 '+'48 '*257))])
        result=run(source,limit=300)
        self.assertIn('stack_depth_limit',reasons(result))
        self.assertEqual(max(n['stack_depth'] for n in result[0]['nodes']),256)

    def test_aggregate_stack_fact_bound_covers_queued_and_serialized_cells(self):
        source=self.far_source()
        with patch.object(analysis,'MAX_STACK_PROOF_CELLS',3):
            result=run(source)
            self.assertEqual(pcs(result),{0x4000})
            self.assertEqual(reasons(result),{'stack_fact_limit'})
            self.assertEqual(result[0]['edges'],[])
            legacy=run(source,far=False)
        self.assertEqual(legacy,run(source,far=False))
        with patch.object(analysis,'MAX_STACK_PROOF_CELLS',6):
            result=run(source)
            self.assertEqual(pcs(result),{0x4000,0x4010})
            self.assertEqual(reasons(result),{'stack_fact_limit'})

    def test_bounds_boolean_and_depth_are_strict(self):
        source=self.far_source()
        for kwargs in (dict(far=1),dict(depth=None),dict(depth=True),dict(depth=65)):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):run(source,**kwargs)
        recursion=Source([(0x100000,'20 00 40')])
        self.assertIn('call_depth_limit',reasons(run(recursion,depth=2)))
        self.assertIn('context_limit',reasons(run(source,contexts=1)))
        self.assertIn('state_limit',reasons(run(source,limit=3)))


if __name__=='__main__':unittest.main()
