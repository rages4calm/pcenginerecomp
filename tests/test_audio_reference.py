"""Boundaries of authored settled audio-port reference inputs."""
import tempfile
from pathlib import Path
import unittest
from scripts.audio_reference import plans,write_plan,normalize_adpcm,normalize_psg


class AudioReferenceTests(unittest.TestCase):
    def test_plans_cover_wrap_disabled_channels_and_invalid_selection(self):
        matrix=plans()
        self.assertEqual(len(matrix),8)
        self.assertEqual(len({p['id'] for p in matrix}),8)
        for plan in matrix:
            self.assertLessEqual(len(plan['operations']),256)
            self.assertTrue(all(-1<=value<=255 for _,value in plan['operations']))
            if plan['id'].startswith('adpcm'):
                self.assertEqual(sum(address==0x180A and value>=0 for address,value in plan['operations']),64)
                self.assertEqual(sum(address==0x180A and value<0 for address,value in plan['operations']),65)
            else:self.assertFalse(any(address==0x804 and value&128 for address,value in plan['operations'] if value>=0))
        self.assertTrue(any(p['id']=='adpcm-ffff' for p in matrix))
        self.assertTrue(any(p['id']=='psg-disabled-7' for p in matrix))

    def test_numeric_probe_format_has_exact_action_count(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'plan.txt'
            for plan in plans():
                write_plan(path,plan)
                values=list(map(int,path.read_text().split()))
                self.assertEqual(len(values),1+2*values[0])

    def test_normalizers_keep_declared_register_widths(self):
        self.assertEqual(normalize_adpcm(dict(address='FFFF',read_address='0000',write_address='FFFE',length=65537,control='80',dma='00',playing=False))['length'],65537)
        psg=normalize_psg(dict(channel_select=7,main_amplitude='E7',lfo_frequency='7F',lfo_control='80',channels=[dict(frequency=564,amplitude='A5',vol_left='0A',vol_right='05',wave_index=31,dda=1,enabled=0,noise=0)]))
        self.assertEqual(psg['channels'][0]['balance'],0xA5)
        self.assertEqual(psg['channels'][0]['dda_mode'],1)
        self.assertEqual(psg['channels'][0]['enabled'],0)
        self.assertEqual(psg['selected'],7)


if __name__=='__main__':unittest.main()
