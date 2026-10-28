"""Independent admission controls for the executed stable-layout fixture."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import stable_context_reference as reference
from generate_context_fixture import firmware, generate, expected_rows
from pcerecomp.emitter import emit_capture
from pcerecomp.project import ABI


def capture(native):
    rows = [dict(pc=pc,mpr=list(mpr),physical=list(physical),data=list(data),
                 native_hits=hits if native else 0,interpreted_hits=0 if native else hits)
            for (pc,mpr,physical,data),hits in reference.expected_sources().items()]
    return dict(schema=1,runtime_abi=ABI,capacity=1024,dropped_instructions=0,
                unreadable_instructions=0,retired_instructions=80,complete=True,observations=rows)


def arguments():
    raw=json.dumps([dict(kind='cpu',values=row)for divisor in (3,12)
                    for row in expected_rows(divisor,spread=True)])
    bootstrap,native=capture(False),capture(True)
    digest=hashlib.sha256(json.dumps(bootstrap).encode()).hexdigest()
    with tempfile.TemporaryDirectory() as directory:
        manifest=emit_capture(bootstrap,Path(directory)/'module',digest,partition_layout='stable')
    return dict(gear_raw=raw,bootstrap_raw=raw,native_raw=raw,
                bootstrap_capture=bootstrap,native_capture=native,manifest=manifest,
                bootstrap_capture_sha256=digest)


class StableContextReferenceTests(unittest.TestCase):
    def test_original_default_firmware_bytes_are_preserved(self):
        self.assertEqual(hashlib.sha256(firmware()).hexdigest(),
                         '5be5bed7ba16b56090bacd93e824536b6ac9e9a24f3a9f14cf9dd6f70612b6c1')
        self.assertNotEqual(firmware(),firmware(spread=True))

    def test_spread_fixture_has_three_pages_six_full_mappings(self):
        keys=reference.expected_sources()
        self.assertEqual(len(keys),26)
        self.assertEqual(sum(keys.values()),80)
        self.assertEqual({pc>>8 for pc,_,_,_ in keys},{0xE0,0xE3,0xE5})
        self.assertEqual(len({mpr for _,mpr,_,_ in keys}),6)
        self.assertGreater(len({mpr for pc,mpr,_,_ in keys if pc==0xE300}),1)
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);generate(out,spread=True)
            self.assertEqual((out/'authored.pce').read_bytes(),firmware(spread=True))
            graph=json.loads((out/'analysis.json').read_text())
            self.assertFalse(graph['unresolved'])
            self.assertEqual({row['pc']>>8 for row in graph['instructions']},{0xE0,0xE3,0xE5})

    def test_full_positive_admission_uses_every_emitted_part(self):
        result=reference.qualify(**arguments())
        self.assertEqual(result['records'],80)
        self.assertEqual(result['literal_checks'],4800)
        self.assertEqual(result['native'],dict(native=80,interpreted=0,source_identities=26))
        self.assertEqual(result['logical_pc_buckets'],3)
        self.assertEqual(result['full_mpr_contexts'],6)
        self.assertGreaterEqual(result['executed_parts'],6)

    def test_independent_trace_cpu_mapping_clock_and_ram_negatives(self):
        original=arguments()
        for source in ('gear_raw','bootstrap_raw','native_raw'):
            for field in (0,1,5,7,8,15,17,19):
                with self.subTest(source=source,field=field):
                    changed=copy.deepcopy(original);rows=json.loads(changed[source])
                    rows[0]['values'][field]^=1;changed[source]=json.dumps(rows)
                    with self.assertRaises(ValueError):reference.qualify(**changed)

    def test_actual_capture_identity_work_and_completeness_negatives(self):
        original=arguments()
        for source in ('bootstrap_capture','native_capture'):
            for kind in ('pc','mpr','physical','data','native_hits','interpreted_hits','loss','abi','retired','bool'):
                with self.subTest(source=source,kind=kind):
                    changed=copy.deepcopy(original);cap=changed[source];row=cap['observations'][0]
                    if kind in ('mpr','physical','data'):row[kind][0]^=1
                    elif kind=='loss':cap['dropped_instructions']=1;cap['complete']=False
                    elif kind=='abi':cap['runtime_abi']=ABI-1
                    elif kind=='retired':cap['retired_instructions']+=1
                    elif kind=='bool':row['pc']=True
                    else:row[kind]+=1
                    with self.assertRaises(ValueError):reference.qualify(**changed)

    def test_stable_manifest_layout_bucket_source_coverage_negatives(self):
        original=arguments()
        for key,value in (('partition_layout','balanced'),('pc_bucket_size',512),
                          ('partition_identity','pc_only'),('unsupported_observations',1),
                          ('excluded_observations',1),('native_instructions_emitted',27),
                          ('code_capture_sha256','0'*64),('runtime_abi',ABI-1),('capture_runtime_abi',ABI-1)):
            with self.subTest(key=key):
                changed=copy.deepcopy(original);changed['manifest'][key]=value
                with self.assertRaises(ValueError):reference.qualify(**changed)
        for action in ('missing','extra','wrong_mapping','duplicate','hash'):
            changed=copy.deepcopy(original);units=changed['manifest']['translation_units']
            if action=='missing':units.pop()
            elif action=='extra':units.append(dict(file='module_unexecuted.cpp',sha256='0'*64))
            elif action=='duplicate':units.append(copy.deepcopy(units[-1]))
            elif action=='hash':units[-1]['sha256']='x'*64
            else:units[-1]['file']='module_m0000000000000000_p0000.cpp'
            with self.assertRaises(ValueError):reference.qualify(**changed)


if __name__=='__main__':unittest.main()
