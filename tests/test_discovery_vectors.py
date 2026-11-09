"""Independent authored ROM-vector expectations, not observed guest work."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pcerecomp import discovery
from test_discovery import seed


class VectorDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.image, self.seeds = self.root/'card.pce', self.root/'seeds.json'

    def inputs(self, patches, roots=None, *, size=8192, profile='base', header=False, reverse=False):
        rom = bytearray([0xEA]*size)
        for offset, data in patches:
            rom[offset:offset+len(data)] = data
        raw = bytes(rom)
        if reverse:
            raw = bytes(int(f'{x:08b}'[::-1], 2) for x in raw)
        if header:
            raw = bytes(512) + raw
        self.image.write_bytes(raw)
        self.seeds.write_text(json.dumps(dict(format='pce-declared-roots-1', schema=1,
            execution_evidence=False, kind='declared',
            image=dict(sha256=hashlib.sha256(raw).hexdigest(), profile=profile,
                       header='copier512' if header else 'none',
                       encoding='bit-reversed' if reverse else 'linear'),
            roots=roots if roots is not None else [seed(size=3)])), encoding='utf-8')

    def discover(self, code=((0, 3), (0x40, 1)), vectors=((0x100, 2),), name='graph', **options):
        return discovery.discover_roots(self.seeds, self.image, self.root/name,
            rom_ranges=code, rom_vector_ranges=vectors, **options)

    def pcs(self, result):
        return {row['pc'] for row in result.declarations.roots}

    def reasons(self, result):
        return {row['reason'] for row in result.report['unresolved']}

    def test_pointer_data_is_separate_from_code_and_report_is_rederived(self):
        self.inputs([(0, bytes.fromhex('6C 00 E1')), (0x100, bytes.fromhex('40 E0')), (0x40, b'\x60')])
        before = {p:p.read_bytes() for p in (self.image,self.seeds)}
        result = self.discover()
        self.assertEqual(self.pcs(result), {0xE000,0xE040})
        self.assertEqual(result.report['analysis_policy'], discovery.VECTOR_POLICY)
        self.assertEqual(result.report['summary']['resolved_vectors'], 1)
        self.assertEqual(result.report['nodes'][0]['rom_vector'], dict(base=0xE100,index=0,
            logical_addresses=[0xE100,0xE101],rom_offsets=[0x100,0x101],target=0xE040))
        self.assertEqual(result.report['edges'], [dict(from_id=0,to_id=1,kind='rom_vector')])
        self.assertEqual(self.reasons(result), {'dynamic_return'})
        self.assertNotIn(0xE100,self.pcs(result))
        self.assertIs(result.report['execution_evidence'],False)
        self.assertEqual(discovery.load_discovery(result.report_path,self.image).sha256,result.sha256)
        self.assertEqual({p:p.read_bytes() for p in before},before)

    def test_default_policy_and_bytes_remain_legacy(self):
        self.inputs([(0, bytes.fromhex('6C 00 E1')), (0x100, bytes.fromhex('40 E0'))])
        result=self.discover(vectors=None)
        self.assertEqual(self.pcs(result),{0xE000})
        self.assertEqual(self.reasons(result),{'indirect_jump'})
        self.assertEqual(result.report['analysis_policy'],discovery.POLICY)
        self.assertEqual(set(result.report['options']),{'rom_ranges','instruction_limit','context_limit'})
        self.assertNotIn('resolved_vectors',result.report['summary'])
        self.assertNotIn('rom_vector',result.report['nodes'][0])

    def test_page_crossing_does_not_use_6502_wrap_bug(self):
        self.inputs([(0,bytes.fromhex('6C FF E1')),(0x1FF,b'\x40'),(0x200,b'\xE0'),
                     (0x100,b'\x12'),(0x40,b'\x60')])
        result=self.discover(vectors=[(0x1FF,2)])
        self.assertEqual(self.pcs(result),{0xE000,0xE040})
        self.assertEqual(result.report['nodes'][0]['rom_vector']['rom_offsets'],[0x1FF,0x200])

    def test_full_16bit_wrap_and_each_mpr_page_are_independent(self):
        mapping=[1,0,0,0,0,0,0,0]
        self.inputs([(0x20,bytes.fromhex('6C FF FF')),(0x1FFF,b'\x40'),
                     (0x2000,b'\xE0'),(0x40,b'\x60')],
                    [seed(pc=0xE020,mpr=mapping,offsets=[0x20,0x21,0x22])],size=16384)
        result=self.discover(code=[(0x20,3),(0x40,1)],vectors=[(0x1FFF,2)])
        self.assertEqual(self.pcs(result),{0xE020,0xE040})
        vector=result.report['nodes'][0]['rom_vector']
        self.assertEqual(vector['logical_addresses'],[65535,0])
        self.assertEqual(vector['rom_offsets'],[8191,8192])

    def test_known_index_wraps_pointer_and_does_not_enumerate_table(self):
        self.inputs([(0x20,bytes.fromhex('A2 02 7C FE FF')),(0,b'\x40\xE0'),(0x40,b'\x60')],
                    [seed(offset=0x20,size=2)])
        result=self.discover(code=[(0x20,5),(0x40,1)],vectors=[(0,2)])
        self.assertEqual(self.pcs(result),{0xE020,0xE022,0xE040})
        vector=result.report['nodes'][1]['rom_vector']
        self.assertEqual((vector['base'],vector['index'],vector['logical_addresses']),(65534,2,[0,1]))

    def test_known_tam_changes_vector_view_without_changing_code_page(self):
        self.inputs([(0,bytes.fromhex('A9 01 53 04 6C 00 40')),
                     (0x2000,b'\x40\xE0'),(0x40,b'\x60')],
                    [seed(size=2)],size=16384)
        result=self.discover(code=[(0,7),(0x40,1)],vectors=[(0x2000,2)])
        node=next(n for n in result.report['nodes'] if n['pc']==0xE004)
        self.assertEqual(node['mpr'],[0,0,1,0,0,0,0,0])
        self.assertEqual(node['rom_vector']['rom_offsets'],[8192,8193])
        self.assertIn(0xE040,self.pcs(result))

    def test_pointer_bytes_can_use_noncontiguous_mpr_banks(self):
        mapping=[0,2,1,0,0,0,0,0]
        self.inputs([(0,bytes.fromhex('6C FF 3F')),(0x5FFF,b'\x40'),
                     (0x2000,b'\xE0'),(0x40,b'\x60')],
                    [seed(size=3,mpr=mapping)],size=24576)
        result=self.discover(vectors=[(0x5FFF,1),(0x2000,1)])
        self.assertEqual(result.report['nodes'][0]['rom_vector']['rom_offsets'],[0x5FFF,0x2000])
        self.assertIn(0xE040,self.pcs(result))

    def test_unknown_index_and_stack_restore_stop_explicitly(self):
        for index,code in enumerate(('7C 00 E1','A2 02 FA 7C 00 E1','AE 00 20 7C 00 E1')):
            self.inputs([(0,bytes.fromhex(code)),(0x102,b'\x40\xE0'),(0x40,b'\x60')],
                        [seed(size=3 if index!=1 else 2)])
            result=self.discover(code=[(0,len(bytes.fromhex(code))),(0x40,1)],vectors=[(0x100,4)],name=str(index))
            self.assertNotIn(0xE040,self.pcs(result))
            self.assertEqual(self.reasons(result),{'indirect_index_unknown'})

    def test_conflicting_index_join_removes_previously_resolved_descendants(self):
        self.inputs([(0,bytes.fromhex('D0 04 A2 00 80 02 A2 02 7C 00 E1')),
                     (0x100,b'\x40\xE0\x50\xE0'),(0x40,b'\x60'),(0x50,b'\x60')],
                    [seed(size=2)])
        result=self.discover(code=[(0,11),(0x40,1),(0x50,1)],vectors=[(0x100,4)])
        self.assertEqual(self.pcs(result),{0xE000,0xE002,0xE004,0xE006,0xE008})
        self.assertEqual(self.reasons(result),{'indirect_index_unknown'})
        self.assertEqual(result.report['summary']['resolved_vectors'],0)
        self.assertGreater(result.report['summary']['explored_states'],5)

    def test_vector_permission_is_required_for_both_bytes_even_inside_code_range(self):
        self.inputs([(0,bytes.fromhex('6C 00 E1')),(0x100,b'\x40\xE0'),(0x40,b'\x60')])
        for index,ranges in enumerate(([(0x100,1)],[(0x101,1)],[(0x102,2)])):
            result=self.discover(code=[(0,0x102)],vectors=ranges,name=str(index))
            self.assertEqual(self.pcs(result),{0xE000})
            self.assertEqual(self.reasons(result),{'allowed_vector_boundary'})
            self.assertEqual(result.report['summary']['resolved_vectors'],0)

    def test_vector_does_not_authorize_target_code_and_limit_remains_explicit(self):
        self.inputs([(0,bytes.fromhex('6C 00 E1')),(0x100,b'\x40\xE0'),(0x40,b'\x60')])
        for name,options,reason in [('target',dict(code=[(0,3)]),'allowed_rom_boundary'),
                                    ('limit',dict(instruction_limit=1),'instruction_limit')]:
            result=self.discover(name=name,**options)
            self.assertEqual(self.pcs(result),{0xE000})
            self.assertEqual(self.reasons(result),{reason})
            self.assertEqual(result.report['summary']['resolved_vectors'],1)

    def test_ram_io_and_populous_aperture_are_not_rom_vector_sources(self):
        cases=[('base',8192,[0,248,0,0,0,0,0,0],0x2000),
               ('base',8192,[0,255,0,0,0,0,0,0],0x2000),
               ('populous',0x80000,[0,64,0,0,0,0,0,0],0x2000),
               ('base',8192,[0,248,0,0,0,0,0,0],0x1FFF)]
        for index,(profile,size,mapping,pointer) in enumerate(cases):
            self.inputs([(0,bytes([0x6C,pointer&255,pointer>>8]))],
                        [seed(size=3,mpr=mapping)],size=size,profile=profile)
            result=self.discover(vectors=[(0,size)],name=str(index))
            self.assertEqual(self.pcs(result),{0xE000})
            self.assertEqual(self.reasons(result),{'non_rom_vector'})

    def test_selector_and_same_pc_mappings_keep_vector_source_identity(self):
        mapping=[0,64,0,0,0,0,0,0]
        roots=[seed(size=3,mpr=mapping,selector=s) for s in (0,1)]
        self.inputs([(0,bytes.fromhex('6C 00 20')),(0x80000,b'\x40\xE0'),
                     (0x100000,b'\x50\xE0'),(0x40,b'\x60'),(0x50,b'\x60')],
                    roots,size=0x280000,profile='sf2')
        result=self.discover(code=[(0,3),(0x40,1),(0x50,1)],vectors=[(0x80000,2),(0x100000,2)])
        self.assertEqual({(n['selector'],n['pc']) for n in result.report['nodes']},
                         {(0,0xE000),(1,0xE000),(0,0xE040),(1,0xE050)})
        self.assertEqual(result.report['summary']['resolved_vectors'],2)

    def test_sf2_mapper_write_barrier_precedes_vector_lookup(self):
        self.inputs([(0,bytes.fromhex('8D F0 1F 6C 00 E1')),(0x100,b'\x40\xE0')],
                    [seed(size=3)],size=0x280000,profile='sf2')
        result=self.discover(code=[(0,6)])
        self.assertEqual(self.pcs(result),{0xE000})
        self.assertEqual(self.reasons(result),{'mapper_write_barrier'})

    def test_decoded_header_and_bit_conversion_apply_to_vector_bytes(self):
        self.inputs([(0,bytes.fromhex('6C 00 E1')),(0x100,b'\x40\xE0'),(0x40,b'\x60')],header=True,reverse=True)
        result=self.discover()
        self.assertEqual(self.pcs(result),{0xE000,0xE040})
        self.assertEqual(result.report['nodes'][0]['rom_vector']['rom_offsets'],[0x100,0x101])

    def test_forged_vector_details_and_policy_options_refuse_admission(self):
        mutations=[lambda r:r['nodes'][0]['rom_vector'].__setitem__('target',0xE050),
                   lambda r:r['nodes'][0]['rom_vector']['rom_offsets'].__setitem__(0,0x102),
                   lambda r:r.__setitem__('analysis_policy',discovery.POLICY),
                   lambda r:r['options'].__setitem__('rom_vector_ranges',[]),
                   lambda r:r['options'].__setitem__('rom_vector_ranges',[{'start':True,'length':2}]),
                   lambda r:r['options'].pop('rom_vector_ranges'),
                   lambda r:r['options']['rom_vector_ranges'][0].__setitem__('extra',0)]
        for index,mutate in enumerate(mutations):
            self.inputs([(0,bytes.fromhex('6C 00 E1')),(0x100,b'\x40\xE0'),(0x40,b'\x60')])
            result=self.discover(name=str(index));report=result.report;mutate(report)
            result.report_path.write_bytes(discovery._canonical(report,discovery.MAX_REPORT_BYTES))
            with self.assertRaises(ValueError):discovery.load_discovery(result.report_path,self.image)

    def test_invalid_vector_ranges_refuse_before_creating_output(self):
        self.inputs([(0,bytes.fromhex('6C 00 E1'))])
        for index,ranges in enumerate(([],True,[(0,0)],[(True,2)],[(8191,2)],[(0,1)]*257)):
            with self.assertRaises(ValueError):self.discover(vectors=ranges,name=str(index))
            self.assertFalse((self.root/str(index)).exists())

    def test_optimized_python_retains_indexed_vector_derivation(self):
        self.inputs([(0,bytes.fromhex('A2 02 7C FE E0')),(0x100,b'\x40\xE0'),(0x40,b'\x60')],
                    [seed(size=2)])
        code=('from pcerecomp.discovery import discover_roots; import sys; '
              'r=discover_roots(sys.argv[1],sys.argv[2],sys.argv[3],'
              'rom_ranges=[(0,5),(64,1)],rom_vector_ranges=[(256,2)]); '
              'print(r.report["summary"]["resolved_vectors"])')
        result=subprocess.run([sys.executable,'-O','-c',code,str(self.seeds),str(self.image),str(self.root/'optimized')],
                              capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'1')
