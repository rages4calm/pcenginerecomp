"""Authored admission controls, independent of any emulator output files."""
from copy import deepcopy
import hashlib
import unittest

from generate_vdc_scroll_fixture import fixture
from scripts.vdc_scroll_reference import expected,qualify
from pcerecomp.project import ABI


def authored_reports():
    c=fixture()[0][0]
    pixels=[1 if ((((c['x']+i)//8)&1)^(c['y']&1))==0 else 2 for i in range(16)]
    state=dict(x=c['x'],y=c['y'],counter=c['counter'],pending=int(c['pending']),x_clock=56,y_clock=48,lsb_clock=-1,bxr_before=1,pixels=pixels)
    def guest(profile):return dict(pc=c[profile]['end_pc'],ticks=c['sample_ticks'],a=0,x=0,y=0,sp=0,p=6,mpr=[255,248,0,0,0,1,0,0],wram_sha256=hashlib.sha256(bytes(8192)).hexdigest())
    def actions(profile):
        return [dict(step=a['index'],entry_ticks=a['effect_ticks']-6,after_ticks=a['effect_ticks']+9,effect_ticks=a['effect_ticks'],port=2,value=8,before=deepcopy(state),after=deepcopy(state))for a in c[profile]['actions']]
    native=dict(schema=1,case=c['id'],guest=guest('runtime'),native_steps=c['runtime']['steps'],interpreter_steps=0,block_steps=12,guard_misses=0,scroll=deepcopy(state),actions=actions('runtime'))
    interpreted=deepcopy(native);interpreted['interpreter_steps']=interpreted['native_steps'];interpreted['native_steps']=0
    gear=dict(schema=1,case=c['id'],guest=guest('gear'),ticks=c['sample_ticks'],wram_sha256=guest('gear')['wram_sha256'],scroll=deepcopy(state),actions=actions('gear'))
    for a in gear['actions']:a['original_writes']=[dict(ticks=a['effect_ticks'],register=7,value=8,raw=8,high=0)]
    captures={}
    for tier in ('native','interpreter'):
        observations=[dict(deepcopy(s),native_hits=int(tier=='native'),interpreted_hits=int(tier=='interpreter'))for s in c['runtime']['sources']]
        captures[tier]=dict(runtime_abi=ABI,complete=True,dropped_instructions=0,unreadable_instructions=0,retired_instructions=c['runtime']['steps'],observations=observations)
    return c,native,interpreted,gear,captures


class ScrollReferenceAdmissionTests(unittest.TestCase):
    def test_authored_positive_is_accepted(self):
        c,n,i,g,caps=authored_reports();r=qualify(c,n,i,g,caps)
        self.assertEqual(r['native'],c['runtime']['steps'])

    def test_bad_type_shape_and_independent_pixel_are_rejected(self):
        for mutation in ('bool','missing','pixel','counter'):
            c,n,i,g,caps=authored_reports()
            if mutation=='bool':n['scroll']['x']=True
            if mutation=='missing':n['scroll'].pop('x_clock')
            if mutation=='pixel':n['scroll']['pixels'][0]^=1
            if mutation=='counter':n['scroll']['counter']+=1
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):expected(c,n)

    def test_wrong_physical_mapping_bytes_or_per_key_hits_are_rejected(self):
        for mutation in ('physical','mpr','bytes','hits','abi','loss'):
            c,n,i,g,caps=authored_reports();record=caps['native']['observations'][0]
            if mutation=='physical':record['physical'][0]^=8192
            if mutation=='mpr':record['mpr'][3]^=1
            if mutation=='bytes':record['data'][0]^=1
            if mutation=='hits':record['native_hits']=0;record['interpreted_hits']=1
            if mutation=='abi':caps['native']['runtime_abi']=ABI-1
            if mutation=='loss':caps['native']['dropped_instructions']=1
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):qualify(c,n,i,g,caps)

    def test_actual_original_callback_and_intermediate_history_are_required(self):
        for mutation in ('event','clock','history','cpu','wram'):
            c,n,i,g,caps=authored_reports()
            if mutation=='event':g['actions'][0]['original_writes']=[]
            if mutation=='clock':g['actions'][0]['original_writes'][0]['ticks']+=3
            if mutation=='history':g['actions'][0]['after']['lsb_clock']=0
            if mutation=='cpu':g['guest']['p']^=4
            if mutation=='wram':g['wram_sha256']='0'*64
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):qualify(c,n,i,g,caps)

    def test_native_fallback_is_rejected_even_when_retirement_total_matches(self):
        c,n,i,g,caps=authored_reports();n['native_steps']-=1;n['interpreter_steps']=1
        with self.assertRaises(ValueError):qualify(c,n,i,g,caps)


if __name__=='__main__':unittest.main()
