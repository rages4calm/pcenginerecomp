"""Authored numeric counterexamples and strict signal-domain admission."""
import copy
import unittest
from unittest.mock import patch
from scripts.psg_pipeline_reference import FRAMES,MASTER,independent_samples,qualify,trace,match,validate_tool_identity

class PsgPipelineTests(unittest.TestCase):
    def test_source_revision_is_part_of_exact_tool_identity(self):
        identity=dict(revision='1'*40,source_sha256='2'*64,source_files=78)
        report=dict(tool_source='authored-tool-root',tool=copy.deepcopy(identity))
        with patch('scripts.psg_pipeline_reference.project.source_identity',return_value=identity):
            self.assertEqual(validate_tool_identity(report),identity)
            report['tool']['revision']='3'*40
            with self.assertRaisesRegex(ValueError,'revision'):validate_tool_identity(report)
    def case(self):return dict(name='sta-abs',pc=0xe100,size=3,cycles=5,old=0,new=31,data=[0x8d,6,8])
    def records(self):
        c=self.case();source,raw,hpf=independent_samples(c)
        base=dict(case='sta-abs',divisor=3,pc=0xe100,mpr=[255,248,248,248,248,255,248,0],physical=[256,257,258],bytes=[141,6,8],start=476,end=491,final_pc=0xe103,dda=31,frames=2048,continuation_end=997405,partition_end_frames=[512,1024,1536,2048],source_ticks=[(i*MASTER+44099)//44100 for i in range(1,FRAMES+1)])
        last=base['source_ticks'][-1];base['continuation_end']=491+(last-491+2)//3*3
        r={'gear':dict(base,calls=1,writes=[[491,6,31]],source_sums=source,hpf=hpf)}
        for tier in('native','interpreted'):
            for profile in('raw','filtered'):
                r[tier+'-'+profile]=dict(base,native=int(tier=='native'),interpreted=int(tier=='interpreted'),profile=profile,rate=44100,observed_source_first_frame=2,observed_source_sums=source[1:],pcm=[[int(v/3)for v in row]for row in hpf]if profile=='filtered'else raw)
        return c,r
    def test_independent_half_gain_and_hpf_counterexample(self):
        sums,raw,hpf=independent_samples(self.case())
        self.assertEqual(sums[:2],[[-10571,-10571],[10571,10571]])
        self.assertEqual(raw[:2],[[-1761,-1761],[1761,1761]])
        self.assertEqual(hpf[:2],[[-5285,-5285],[5293,5293]])
        self.assertEqual(len(hpf),2048)
    def test_full_authored_stages_qualified(self):
        c,r=self.records();out=qualify(c,3,r);self.assertEqual(out['unexplained_differences'],0);self.assertEqual(out['tool_pcm_scalar_checks'],16384)
    def test_changed_output_profile_refused(self):
        c,r=self.records();r=copy.deepcopy(r);r['native-raw']['profile']='filtered'
        with self.assertRaisesRegex(ValueError,'profile'):qualify(c,3,r)
    def test_raw_in_filtered_domain_refused(self):
        c,r=self.records();r=copy.deepcopy(r);r['native-filtered']['pcm']=r['native-raw']['pcm']
        with self.assertRaisesRegex(ValueError,'pcm'):qualify(c,3,r)
    def test_filter_history_across_drain_required(self):
        c,r=self.records();r=copy.deepcopy(r);r['gear']['hpf'][512]=r['gear']['hpf'][0]
        with self.assertRaisesRegex(ValueError,'hpf'):qualify(c,3,r)
    def test_no_invented_first_tool_source_observation(self):
        c,r=self.records();r=copy.deepcopy(r);r['native-raw']['observed_source_first_frame']=1
        with self.assertRaisesRegex(ValueError,'observed_source_first_frame'):qualify(c,3,r)
    def test_source_identity_phase_and_counts_required(self):
        for key,value in [('mpr',[255]*8),('physical',[0,1,2]),('bytes',[234,6,8]),('end',490),('native',0),('frames',2047),('partition_end_frames',[2048])]:
            c,r=self.records();r=copy.deepcopy(r);r['native-raw'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):qualify(c,3,r)
    def test_boolean_unknown_missing_rejected(self):
        for kind in('boolean','unknown','missing'):
            c,r=self.records();r=copy.deepcopy(r)
            if kind=='boolean':r['native-raw']['native']=True
            elif kind=='unknown':r['native-raw']['guessed']=0
            else:del r['native-raw']['dda']
            with self.subTest(kind=kind),self.assertRaises(ValueError):qualify(c,3,r)
    def test_cross_domain_refused_despite_identical_values(self):
        engine=dict(name='authored',revision='1'*40,source_sha256='2'*64,binary_sha256='3'*64)
        a=trace(self.case(),3,'psg-raw',[[1,1]],engine,'4'*64);b=copy.deepcopy(a);b['domain']['stage']='psg-hpf'
        with self.assertRaises(ValueError):match(a,b)
    def test_changed_first_frame_refused_despite_identical_values(self):
        engine=dict(name='authored',revision='1'*40,source_sha256='2'*64,binary_sha256='3'*64)
        a=trace(self.case(),3,'psg-raw',[[1,1]],engine,'4'*64);b=copy.deepcopy(a);b['first_frame']=2
        with self.assertRaises(ValueError):match(a,b)

if __name__=='__main__':unittest.main()
