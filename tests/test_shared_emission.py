"""Exact guarded-part reuse; full source identities remain distinct."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pcerecomp.cli import main
from pcerecomp.emitter import emit_capture, emit_history, emit_observation_profile
from pcerecomp.history import compose_history
from pcerecomp.observations import compose_observation_profile
from pcerecomp.native_catalog import load_native_catalog
from tests.test_capture import MPR, capture, observation


def shared_rows():
    other=MPR.copy();other[3]=130
    rows=[]
    for mapping in (MPR,other):
        rows += [observation(0x4001,(0xE8,),mpr=mapping),observation(0x4002,(0xC8,),mpr=mapping),
                 observation(0x4010,(0xAD,0,0x60),mpr=mapping),
                 observation(0x4020,(0xA9,1 if mapping==MPR else 2),mpr=mapping),
                 observation(0x4030,(0x43,8),mpr=mapping),observation(0x4040,(0x53,8),mpr=mapping),
                 observation(0x5FFF,(0xA9,0x23),mpr=mapping)]
    rows.append(observation(0x4000,(0xEA,),mpr=other))
    return rows


def emit(root,rows,**options):
    value=capture(rows,capacity=max(64,len(rows)));value['runtime_abi']=29
    source=root/'original.json';source.write_text(json.dumps(value),encoding='utf-8')
    manifest=emit_capture(value,root/'module',hashlib.sha256(source.read_bytes()).hexdigest(),
                          partition_layout='shared',**options)
    return manifest,source


class SharedEmissionTests(unittest.TestCase):
    def test_whole_parts_share_but_catalogue_preserves_each_complete_identity(self):
        rows=[]
        for i in range(4):
            mapping=MPR.copy();mapping[7]=i
            rows += [observation(0x4000,(0xA9,42),mpr=mapping),observation(0x4002,(0xE8,),mpr=mapping)]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest,source=emit(root,rows)
            self.assertEqual(manifest['native_instructions_emitted'],8)
            self.assertEqual(manifest['native_contexts'],4)
            self.assertEqual(manifest['translated_body_count'],2)
            self.assertEqual(manifest['unshared_partition_count'],4)
            self.assertEqual(len(manifest['translation_units']),2)
            catalog=load_native_catalog(root/'module/module.json',source)
            self.assertEqual(len(catalog.emitted),8)
            self.assertEqual(catalog.observed,catalog.emitted)
            self.assertFalse(catalog.provenance['execution_evidence'])
            code=(root/'module/module_part_0000.cpp').read_text()
            self.assertIn('s.a=42;',code);self.assertNotIn('interpret_step',code)
            for artifact in manifest['translation_units']+manifest['generated_headers']:
                self.assertEqual(hashlib.sha256((root/'module'/artifact['file']).read_bytes()).hexdigest(),artifact['sha256'])

    def test_reused_indices_dispatch_in_pc_order_not_helper_id_order(self):
        rows=shared_rows()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest,source=emit(root,rows,partition_size=1)
            self.assertEqual(manifest['unshared_partition_count'],15)
            self.assertEqual(len(manifest['translation_units']),11)
            self.assertEqual(len(load_native_catalog(root/'module/module.json',source).emitted),15)
            mapping=MPR.copy();mapping[3]=130
            packed=sum(value<<(8*i) for i,value in enumerate(mapping))
            code=(root/'module/module.cpp').read_text().split(f'case {packed}ULL:')[1]
            self.assertLess(code.index('s.pc <= 16384'),code.index('s.pc <= 16385'))

    def test_physical_operands_opcode_and_whole_membership_prevent_sharing(self):
        mapping=MPR.copy();mapping[3]=130
        cases=[
            [observation(0x5FFF,(0xA9,7)),observation(0x5FFF,(0xA9,7),mpr=mapping)],
            [observation(),observation(raw=(0xA9,43),mpr=mapping)],
            [observation(raw=(0xE8,)),observation(raw=(0xC8,),mpr=mapping)],
            [observation(),observation(0x4002,(0xEA,)),observation(mpr=mapping)],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for index,rows in enumerate(cases):
                root=Path(tmp)/str(index);root.mkdir();manifest,_=emit(root,rows)
                self.assertEqual(len(manifest['translation_units']),3)

    def test_empty_unsupported_and_excluded_selections_remain_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index,rows,options in ((0,[],{}),(1,[observation(raw=(0x0B,))],{}),
                                      (2,[observation()],dict(exclude_ranges=[(0x100001,1)]))):
                root=Path(tmp)/str(index);root.mkdir();manifest,source=emit(root,rows,**options)
                self.assertEqual(manifest['native_instructions_emitted'],0)
                self.assertEqual(manifest['unshared_partition_count'],0)
                self.assertEqual(len(manifest['translation_units']),1)
                self.assertEqual(manifest['translated_body_count'],0)
                self.assertFalse(load_native_catalog(root/'module/module.json',source).emitted)

    def test_catalogue_rederives_part_membership_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original,source=emit(root,shared_rows(),partition_size=1)
            path=root/'module/module.json'
            for changes in ({'unshared_partition_count':True},{'unshared_partition_count':14},
                            {'unshared_partition_count':-1},{'partition_identity':'guessed'},
                            {'partitioned':False},{'pc_bucket_size':256},{'native_span':{}},
                            {'partition_layout':'balanced'},{'runtime_abi':28}):
                changed=copy.deepcopy(original);changed.update(changes)
                path.write_text(json.dumps(changed),encoding='utf-8')
                with self.subTest(changes=changes),self.assertRaises(ValueError):load_native_catalog(path,source)

    def test_shared_rejects_single_unit_and_span_before_output_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index,options in enumerate((dict(single_unit=True),dict(native_span=True),dict(partition_size=0))):
                target=Path(tmp)/str(index)
                with self.assertRaises(ValueError):emit_capture(capture(),target,partition_layout='shared',**options)
                self.assertFalse(target.exists())

    def test_profile_and_history_keep_original_provenance_with_shared_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original,source=emit(root,shared_rows(),partition_size=1)
            profile=compose_observation_profile([source]);profile_path=root/'profile.json'
            profile_path.write_text(json.dumps(profile),encoding='utf-8')
            manifest=emit_observation_profile(profile,root/'profile-module',hashlib.sha256(profile_path.read_bytes()).hexdigest(),partition_layout='shared',partition_size=1)
            history=compose_history([source],root/'history')
            history_manifest=emit_history(root/'history/history.json',root/'history-module',partition_layout='shared',partition_size=1)
            for name,path in (('profile-module',profile_path),('history-module',root/'history/history.json')):
                catalog=load_native_catalog(root/name/'module.json',path)
                self.assertEqual(len(catalog.emitted),15)
                self.assertEqual(catalog.observed,catalog.emitted)
                for p in (root/'module').iterdir():
                    if p.suffix in ('.cpp','.hpp'):self.assertEqual(p.read_bytes(),(root/name/p.name).read_bytes())
            self.assertEqual(manifest['observation_inputs'][0]['runtime_abi'],29)
            self.assertEqual(history_manifest['observation_history_sha256'],history.index_sha256)

    def test_shared_cli_is_explicit_and_original_order_is_not_a_sharing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rows=shared_rows();manifest,source=emit(root,rows,partition_size=1)
            self.assertEqual(main(['emit-capture',str(source),'--out',str(root/'cli'),
                                   '--partition-layout','shared','--partition-size','1']),0)
            for p in (root/'module').iterdir():
                self.assertEqual(p.read_bytes(),(root/'cli'/p.name).read_bytes())
            value=json.loads(source.read_text());value['observations'].reverse()
            reversed_manifest=emit_capture(value,root/'reversed',partition_layout='shared',partition_size=1)
            for p in (root/'module').iterdir():
                if p.suffix in ('.cpp','.hpp'):self.assertEqual(p.read_bytes(),(root/'reversed'/p.name).read_bytes())


if __name__=='__main__':unittest.main()
