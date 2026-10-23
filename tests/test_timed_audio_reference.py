"""Authored failure/plan checks; actual external execution is opt-in."""
import copy
import unittest
from scripts import timed_audio_reference as ref


class TimedAudioReferenceTests(unittest.TestCase):
    def test_plans_have_real_decoder_all_rates_and_monotone_events(self):
        groups=ref.plans()
        self.assertEqual(set(groups),{'psg','adpcm','mixed'})
        self.assertEqual({c['id'] for c in groups['adpcm'] if c['id'].startswith('decoder-rate-')},
                         {f'decoder-rate-{i}' for i in range(16)})
        for cases in groups.values():
            for case in cases:
                self.assertEqual(case['operations'][0],('r',))
                prior=0
                for op in case['operations'][1:]:
                    self.assertGreaterEqual(op[1],prior,case['id']);prior=op[1]
                    self.assertIn(op[0],('p','a','s'))
                    if op[0]=='a':self.assertIn(op[2],(8,9,13,14))

    def test_boundaries_and_source_write_interleaving(self):
        cases=ref.plans()['psg']
        silent=cases[0]['operations']
        self.assertTrue(all(('s',t) in silent for t in (486,487,488,489,974,975)))
        wave=next(c for c in cases if c['id']=='wave-0-127')
        self.assertTrue(any(op[:3]==('p',1464,6) for op in wave['operations']))
        dda=next(c for c in cases if c['id']=='dda-held-0-reg6-value31')
        self.assertIn(('p',487,6,31),dda['operations'])

    def test_serialized_spans_are_exact(self):
        for cases in ref.plans().values():
            text,spans=ref.serialize(cases)
            self.assertEqual(sum(s['checkpoints'] for s in spans),sum(line.startswith('s ') for line in text.splitlines()))
            for left,right in zip(spans,spans[1:]):self.assertEqual(left['start']+left['checkpoints'],right['start'])

    def test_overdue_vectors_are_explicit_and_separate(self):
        cases=ref.overdue_plans();self.assertEqual(len(cases),3)
        for case in cases:
            self.assertIn(('a',2501,14,15),case['operations'])
            self.assertIn(('s',2504),case['operations'])

    def row(self):
        return {'time':488,'pcm':[[100,-100]],'adpcm':dict.fromkeys((*ref.STATE_FIELDS,'phase'),0)}

    def test_count_mismatch_rejected(self):
        with self.assertRaises(ValueError):ref.compare([],[],[dict(id='x',start=0,checkpoints=1)])

    def test_first_pcm_difference_is_reported(self):
        a,b=self.row(),self.row();b['pcm'][0][1]=-99
        diff=ref.compare([a],[b],[dict(id='edge',start=0,checkpoints=1)])
        self.assertEqual(diff['case'],'edge');self.assertEqual(diff['first_difference'],0)

    def test_running_phase_is_compared(self):
        a,b=self.row(),self.row();a['adpcm']['playing']=b['adpcm']['playing']=True;b['adpcm']['phase']=3
        self.assertEqual(ref.compare([a],[b],[dict(id='x',start=0,checkpoints=1)])['field'],'adpcm.phase')

    def test_stopped_phase_is_explicitly_outside_equality(self):
        a,b=self.row(),self.row();b['adpcm']['phase']=3
        self.assertIsNone(ref.compare([a],[b],[dict(id='x',start=0,checkpoints=1)]))
        b=copy.deepcopy(a);b['adpcm']['predictor']=3
        self.assertEqual(ref.compare([a],[b],[dict(id='x',start=0,checkpoints=1)])['field'],'adpcm.predictor')

    def test_malformed_pcm_rejected(self):
        a=self.row();a['pcm']=[[40000,0]]
        with self.assertRaises(ValueError):ref.compare([a],[a],[dict(id='x',start=0,checkpoints=1)])


if __name__=='__main__':unittest.main()
