"""Admission negative controls use independent authored scalar values."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from scripts.psg_phase_reference import audit_receipt, sha
import unittest
from scripts.psg_phase_reference import qualify

class PsgPhaseAdmissionTests(unittest.TestCase):
    def records(self):
        case=dict(name='sta-abs',pc=0xe100,size=3,cycles=5,old=0,new=31,data=[0x8d,6,8])
        base=dict(case='sta-abs',divisor=12,pc=0xe100,mpr=[255,248,248,248,248,255,248,0],physical=[256,257,258],bytes=[0x8d,6,8],start=440,end=500,final_pc=0xe103,dda=31)
        gear=dict(base,calls=1,writes=[[500,6,31]],pcm=[-5285,-5285,5293,5293])
        native=dict(base,native=1,interpreted=0,pcm=[-1761,-1761,1761,1761])
        interpreted=dict(native,native=0,interpreted=1)
        return case,gear,native,interpreted
    def test_exact_boundary_admitted_with_later_pcm_delta_retained(self):
        c,g,n,i=self.records();r=qualify(c,12,g,n,i)
        self.assertEqual(r['original_psg_writes'],1)
        self.assertEqual(r['later_pcm_differences'],[dict(sample=k,gear_raw=5293,gear_divided_by_three=1764,tool_mixed=1761)for k in (2,3)])
    def test_original_entry_phase_write_rejected(self):
        c,g,n,i=self.records();g['writes'][0][0]=440
        with self.assertRaisesRegex(ValueError,'pending-cycle phase'):qualify(c,12,g,n,i)
    def test_actual_old_tool_early_pcm_rejected(self):
        c,g,n,i=self.records();n['pcm'][:2]=[1761,1761];i['pcm'][:2]=[1761,1761]
        with self.assertRaisesRegex(ValueError,'First PCM'):qualify(c,12,g,n,i)
    def test_wrong_source_and_clock_rejected(self):
        for field,value in [('mpr',[255]*8),('physical',[0,1,2]),('bytes',[0xea,6,8]),('pc',0xe101),('end',501)]:
            c,g,n,i=self.records();n[field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'CPU/source'):qualify(c,12,g,n,i)
    def test_wrong_retirement_tier_rejected(self):
        c,g,n,i=self.records();n['native']=0;n['interpreted']=1
        with self.assertRaisesRegex(ValueError,'execution tiers'):qualify(c,12,g,n,i)
    def test_wrong_completion_extent_rejected(self):
        c,g,n,i=self.records();g['calls']=5
        with self.assertRaisesRegex(ValueError,'completion extent'):qualify(c,12,g,n,i)
    def test_wrong_psg_value_and_port_rejected(self):
        for at,value in ((1,7),(2,0)):
            c,g,n,i=self.records();g['writes'][0][at]=value
            with self.assertRaisesRegex(ValueError,'PSG trace'):qualify(c,12,g,n,i)
    def test_unknown_missing_and_boolean_fields_rejected(self):
        for change in ('extra','missing','boolean','arrayboolean','portboolean'):
            c,g,n,i=self.records()
            if change=='extra':n['fabricated']=0
            elif change=='missing':del n['dda']
            elif change=='boolean':n['native']=True
            elif change=='arrayboolean':n['mpr'][0]=True
            else:g['writes'][0][2]=True
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'Strict'):qualify(c,12,g,n,i)
    def receipt(self):
        scratch=TemporaryDirectory();self.addCleanup(scratch.cleanup);root=Path(scratch.name).resolve()
        c,g,n,i=self.records();groups={name:{}for name in ('inputs','tools','reference_raw_sources','reference_compile_sources','raw_outputs','external_libraries','gear_objects','gear_binary','authored_fixture','admissions')}
        def file(group,name,text='authored'):
            p=root/group/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);groups[group][str(p)]=sha(p);return p
        for name in ('psg_phase_reference.py','psg_phase_oracle_probe.cpp','geargrafx_psg_phase_probe.cpp','generate_psg_phase_fixture.py','runtime.hpp','runtime.cpp','block.cpp','pcm.cpp','emitter.py','data_ops.py','project.py'):file('inputs',name)
        for group in ('reference_raw_sources','reference_compile_sources'):
            for name in ('huc6280.cpp','huc6280_inline.h','huc6280_opcodes_inline.h','memory_inline.h','huc6280_psg.cpp','audio.cpp','geargrafx_core.cpp'):file(group,name)
        for group in ('tools','external_libraries','gear_objects','gear_binary'):file(group,'authored-marker')
        for name in ('module.cpp','module.json','psg_phase_fixture.hpp','authored.pce'):file('authored_fixture',name)
        rows=[]
        for speed in (3,12):
            values={tier:copy.deepcopy(row)for tier,row in [('gear',g),('native',n),('interpreted',i)]}
            for row in values.values():row.update(divisor=speed,start=488-4*speed,end=488+speed)
            values['gear']['writes'][0][0]=488+speed
            folder=root/(c['name']+'-'+str(speed));folder.mkdir();raw={}
            for tier,row in values.items():
                path=folder/(tier+'.stdout');path.write_text(json.dumps(row));groups['raw_outputs'][str(path)]=sha(path);raw[tier]=str(path)
                path=folder/(tier+'.stderr');path.write_text('');groups['raw_outputs'][str(path)]=sha(path)
            admission=folder/'admission.json';admission.write_text(json.dumps(dict(case=c,speed=speed,reports=values,raw_stdout=raw)));groups['admissions'][str(admission)]=sha(admission)
            rows.append(qualify(c,speed,**values))
        report=dict(result='pass',bindings=groups,cases=rows);path=root/'result.json';path.write_text(json.dumps(report));return path,report,c
    def test_written_receipt_reloaded_and_raw_sources_bound(self):
        path,report,c=self.receipt()
        with patch('scripts.psg_phase_reference.parse_fixture',return_value=[c]):self.assertEqual(audit_receipt(path)['raw_stdout'],6)
    def test_receipt_missing_group_source_key_or_matrix_rejected(self):
        for change in ('group','source','matrix'):
            path,report,c=self.receipt()
            if change=='group':del report['bindings']['gear_objects']
            elif change=='source':report['bindings']['inputs']={k:v for k,v in report['bindings']['inputs'].items()if Path(k).name!='runtime.cpp'}
            else:report['cases'].pop()
            path.write_text(json.dumps(report))
            with patch('scripts.psg_phase_reference.parse_fixture',return_value=[c]),self.subTest(change=change),self.assertRaises(ValueError):audit_receipt(path)
    def test_receipt_raw_case_association_cannot_be_swapped(self):
        path,report,c=self.receipt();admission=path.parent/'sta-abs-3/admission.json';payload=json.loads(admission.read_text());payload['raw_stdout']['gear']=str(path.parent/'sta-abs-12/gear.stdout');admission.write_text(json.dumps(payload));report['bindings']['admissions'][str(admission)]=sha(admission);path.write_text(json.dumps(report))
        with patch('scripts.psg_phase_reference.parse_fixture',return_value=[c]),self.assertRaisesRegex(ValueError,'case association'):audit_receipt(path)
    def test_receipt_raw_stdout_cannot_be_relabelled(self):
        path,report,c=self.receipt();raw=path.parent/'sta-abs-3/native.stdout';payload=json.loads(raw.read_text());payload['dda']=0;raw.write_text(json.dumps(payload));report['bindings']['raw_outputs'][str(raw)]=sha(raw);path.write_text(json.dumps(report))
        with patch('scripts.psg_phase_reference.parse_fixture',return_value=[c]),self.assertRaisesRegex(ValueError,'Raw stdout differs'):audit_receipt(path)
if __name__=='__main__':unittest.main()
