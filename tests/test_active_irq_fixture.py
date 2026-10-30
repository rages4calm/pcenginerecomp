"""Source-designed active-display firmware and independent fixture constants."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tests import active_irq_fixture as fixture


class ActiveIrqFixtureTests(unittest.TestCase):
    def test_matrix_has_all_requested_axes_once(self):
        cases=fixture.cases()
        self.assertEqual(len(cases),48)
        self.assertEqual(len({case['id']for case in cases}),48)
        self.assertEqual({(case['source'],case['access'],case['policy'],case['divisor'],case['vce'])for case in cases},
            {(source,access,policy,divisor,vce)for source in ('raster','collision')for access in ('high','tai')
             for policy in ('retain','mask')for divisor in (3,12)for vce in (4,3,2)})

    def test_every_authored_source_is_pinned_to_exact_rom_and_mapping(self):
        for case in fixture.cases():
            rom,markers,sources=fixture.program(case)
            self.assertEqual(len(rom),262144)
            self.assertLess(markers['done'],markers['handler1'])
            self.assertEqual(int.from_bytes(rom[0x1ff8:0x1ffa],'little'),0xf800)
            self.assertEqual(int.from_bytes(rom[0x1ff6:0x1ff8],'little'),0xf880)
            for row in sources:
                expected=[(row['mpr'][((row['pc']+i)&65535)>>13]<<13)|((row['pc']+i)&8191)
                          for i in range(len(row['data']))]
                self.assertEqual(row['physical'],expected)
                self.assertEqual([rom[address]for address in expected],row['data'])

    def test_target_pre_dma_and_ack_are_natural_instruction_boundaries(self):
        for case in fixture.cases():
            _,markers,sources=fixture.program(case)
            by_pc={row['pc']:row['data']for row in sources}
            self.assertEqual(by_pc[markers['pre_dma']],[0x8d,0x0b,0x18])
            self.assertEqual(by_pc[markers['post_ack']],[0x68])
            self.assertEqual(by_pc[markers['target']],
                [0xad,3,0]if case['access']=='high'else[0xf3,2,0,0,0x22,2,0])
            self.assertEqual(by_pc[markers['return_pc']],[0xea])
            # The actual guest mask records cause bits; original BUSY remains
            # visible in the preceding raw load's instruction observation.
            handler=bytes(value for row in sources if 0xf800<=row['pc']<0xf880 for value in row['data'])
            self.assertIn(bytes([0xad,0,0,0x29,63,0x8d,0x14,0x20]),handler)

    def test_expected_pixels_memory_and_cmp_carry_are_independent_literals(self):
        values=fixture.expected_vram()
        self.assertEqual(values[0x7000:0x7008],[64,32,512,0x3000]*2)
        self.assertEqual(values[0x6000:0x6003],[0xdead,0xa65c,0x5aa5])
        self.assertEqual(values[0x4000],65535)
        self.assertEqual(values[0x418f],65535)
        for case in fixture.cases():
            memory=fixture.expected_wram(case)
            self.assertEqual(memory[509],129 if case['access']=='high'else 1)
            self.assertEqual(memory[20],4 if case['source']=='raster'else 1)
            self.assertEqual(memory[18],int(case['policy']=='retain'))
            # CMP #2 exits equal and sets C; LDA, TII and CLI preserve it.
            self.assertEqual(memory[509]&1,1)

    def test_fixture_is_deterministic_and_emission_is_not_execution(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary)
            one=fixture.fixtures(root/'one');two=fixture.fixtures(root/'two')
            first=json.loads((one/'fixture.json').read_text())
            self.assertFalse(first['execution_evidence'])
            self.assertEqual(len(first['cases']),48)
            self.assertEqual((one/'fixture.json').read_bytes(),(two/'fixture.json').read_bytes())
            for case in first['cases']:
                self.assertEqual(hashlib.sha256((one.parent/case['rom']).read_bytes()).hexdigest(),case['sha256'])
            self.assertFalse(json.loads((one/'module.json').read_text())['execution_evidence'])
            self.assertNotIn('interpret_step(', (one/'module.cpp').read_text())

    def test_geometry_reaches_sprite_fetch_and_padding_policy_is_source_designed(self):
        widths={4:256,3:384,2:576}
        for divider,width in widths.items():
            display=(32 if divider==3 else 24)+24
            self.assertLess((display+width-14)*divider,1365)
            self.assertEqual((display+width)*divider,{4:1216,3:1320,2:1248}[divider])
        for case in fixture.cases():
            _,_,sources=fixture.program(case)
            # Between the non-acknowledging IRR poll and first queued high read,
            # only raster recipes add the two declared WRAM TII operations.
            rows=sorted((r for r in sources if r['pc']<0xf800),key=lambda r:r['pc'])
            index=next(i for i,r in enumerate(rows)if r['data']==[0xad,3,0x14])
            target=next(i for i in range(index+1,len(rows))if rows[i]['data']==[0xad,3,0])
            pads=[r['data']for r in rows[index:target]if r['data'][0]==0x73]
            self.assertEqual(len(pads),2 if case['source']=='raster'else 0)
            for raw in pads:
                self.assertEqual(raw[5]|raw[6]<<8,10 if case['divisor']==3 else 1)


if __name__=='__main__':unittest.main()
