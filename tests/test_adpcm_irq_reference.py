"""Authored ADPCM source generation and independent CPU/IRQ/stack ledgers."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from tests import generate_adpcm_irq_fixture as fixture
from scripts import adpcm_irq_reference as reference
from pcerecomp.project import ABI


def admission(case):
    """Authored admission inputs only; this is not an emulator execution receipt."""
    outputs={};captures={}
    for tier in('gear','native','interpreter'):
        outputs[tier]=dict(case=case['id'],tier=tier,origin_ticks=sum(t for t,_ in reference.primer_clocks(case,tier=='gear')),
                           initial={k:copy.deepcopy(case['initial'][k])for k in('values','wram_sha256','irq_vector')},
                           rows=[{k:copy.deepcopy(r[k])for k in('values','wram_sha256','irq_vector')}for r in case['expected']],block_steps=case['block_steps'])
        total=case['primer_steps']+case['steps']
        if tier=='gear':outputs[tier]['original_instructions']=total
        else:
            outputs[tier].update(native=total if tier=='native'else 0,interpreted=0 if tier=='native'else total,guards=4 if tier=='native'else 0)
            observations=[dict(pc=r['pc'],mpr=copy.deepcopy(r['mpr']),physical=copy.deepcopy(r['physical']),data=copy.deepcopy(r['data']),
                               native_hits=r['hits']if tier=='native'else 0,interpreted_hits=0 if tier=='native'else r['hits'])for r in case['source_hits']]
            captures[tier]=dict(schema=1,runtime_abi=ABI,capacity=4096,dropped_instructions=0,unreadable_instructions=0,retired_instructions=total,complete=True,observations=observations)
    return dict(case=case,outputs=outputs,captures=captures,abi=ABI)


class AdpcmIrqFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.cases,cls.images,cls.sources=fixture.authored_fixture();cls.by_id={c['id']:c for c in cls.cases}

    def test_finite_48_case_matrix_has_full_independent_source_ledgers(self):
        self.assertEqual(len(self.cases),48);self.assertEqual(len(self.by_id),48)
        self.assertEqual(len(self.sources),228)
        self.assertEqual({c['speed']for c in self.cases},{3,12})
        for c in self.cases:
            self.assertEqual(len(c['expected']),48)
            self.assertEqual(sum(s['hits']for s in c['source_hits']),c['primer_steps']+48)
            self.assertEqual(c['expected'][-1]['values'][0],c['end_pc'])
            for s in c['source_hits']:
                self.assertEqual(len(s['mpr']),8)
                self.assertEqual([self.images[c['id']][p]for p in s['physical']],s['data'])

    def test_read_and_playback_half_thresholds_are_distinct(self):
        for label in('low','high'):
            def state(name):return dict(zip(fixture.COLUMNS,self.by_id[name+'-'+label]['initial']['values']))
            self.assertEqual((state('half-read')['length'],state('half-read')['half_irq']),(32767,1))
            self.assertEqual((state('half-play')['length'],state('half-play')['half_irq']),(32768,1))
            self.assertEqual((state('threshold-read')['length'],state('threshold-read')['half_irq']),(32768,0))
            self.assertEqual((state('end-read')['length'],state('end-read')['half_irq'],state('end-read')['end_irq']),(0,0,1))
            self.assertEqual((state('both-write')['length'],state('both-write')['half_irq'],state('both-write')['end_irq']),(1,1,1))

    def test_irq_order_masks_and_held_rti_have_independent_vectors(self):
        for label in('low','high'):
            vectors=lambda name:[r['irq_vector']for r in self.by_id[name+'-'+label]['expected']if r['irq_vector']]
            self.assertEqual(vectors('half-read'),[0xFFF6])
            self.assertEqual(vectors('end-read-held-rti'),[0xFFF6,0xFFF6])
            for name in('half-read-cpu-mask','half-read-cd-mask','half-read-i-mask','threshold-read'):self.assertEqual(vectors(name),[])
            for mask,wanted in enumerate(([0xFFF8,0xFFF6],[0xFFF8],[0xFFF6],[])):self.assertEqual(vectors('priority-mask'+str(mask)),wanted)
            for kind in('disable-retain','reset-retain','reload-retain'):self.assertEqual(vectors('end-read-'+kind),[0xFFF6])

    def test_primer_tii_stack_residue_is_independently_preserved(self):
        for name,value in(('half-play-high',32),('both-write-high',90),('priority-mask0-high',0)):
            ram=bytearray(8192);ram[510]=value
            self.assertEqual(self.by_id[name]['initial']['wram_sha256'],hashlib.sha256(ram).hexdigest())

    def test_wrapped_stack_delivery_pushes_real_return_pc(self):
        c=self.by_id['wrapped-stack-high'];row=c['expected'][1]
        self.assertEqual(row['irq_vector'],0xFFF6);self.assertEqual(row['values'][4],254)
        ram=bytearray(8192);ram[257]=0xE0;ram[256]=(c['marker']+4)&255
        self.assertEqual(row['wram_sha256'],hashlib.sha256(ram).hexdigest())

    def test_original_fast_prefix_difference_is_preserved(self):
        for c in self.cases:
            native=sum(t for t,_ in reference.primer_clocks(c,False));gear=sum(t for t,_ in reference.primer_clocks(c,True))
            self.assertEqual(native-gear,18 if c['speed']==3 else 0)

    def test_repeat_generation_preserves_all_bytes_and_timestamps(self):
        with tempfile.TemporaryDirectory()as temp:
            out=Path(temp);fixture.generate(out)
            before={p.name:p.read_bytes()for p in out.iterdir()if p.is_file()}
            for name in before:os.utime(out/name,ns=(1000000000,1000000000))
            fixture.generate(out)
            self.assertEqual(before,{p.name:p.read_bytes()for p in out.iterdir()if p.is_file()})
            self.assertTrue(all((out/name).stat().st_mtime_ns==1000000000 for name in before))

    def test_positive_execution_admission_and_manifest_source_plan(self):
        for c in self.cases:
            total,sources=reference.qualify_execution(**admission(c))
            self.assertEqual(total,c['primer_steps']+48);self.assertEqual(sum(sources.values()),total)

    def test_actual_state_counter_capture_and_origin_corruptions_are_rejected(self):
        original=admission(self.by_id['half-read-high'])
        for tier in('native','interpreter','gear'):
            for field in range(len(fixture.COLUMNS)):
                altered=copy.deepcopy(original);altered['outputs'][tier]['rows'][0]['values'][field]^=1
                with self.subTest(tier=tier,field=field),self.assertRaises(ValueError):reference.qualify_execution(**altered)
            altered=copy.deepcopy(original);altered['outputs'][tier]['origin_ticks']+=1
            with self.assertRaises(ValueError):reference.qualify_execution(**altered)
        for tier in('native','interpreter'):
            for field in('pc','mpr','physical','data','native_hits','interpreted_hits'):
                altered=copy.deepcopy(original);item=altered['captures'][tier]['observations'][0]
                if isinstance(item[field],list):item[field][0]^=1
                else:item[field]+=1
                with self.subTest(tier=tier,field=field),self.assertRaises(ValueError):reference.qualify_execution(**altered)

    def test_boolean_and_extra_actual_fields_are_not_accepted(self):
        original=admission(self.by_id['half-read-high'])
        for change in('bool-state','bool-work','extra-row','wrong-guard','loss'):
            altered=copy.deepcopy(original)
            if change=='bool-state':altered['outputs']['native']['rows'][0]['values'][19]=False
            elif change=='bool-work':altered['outputs']['native']['native']=True
            elif change=='extra-row':altered['outputs']['native']['initial']['extra']=1
            elif change=='wrong-guard':altered['outputs']['native']['guards']=0
            else:altered['captures']['native']['complete']=False;altered['captures']['native']['dropped_instructions']=1
            with self.subTest(change=change),self.assertRaises(ValueError):reference.qualify_execution(**altered)


if __name__=='__main__':unittest.main()


