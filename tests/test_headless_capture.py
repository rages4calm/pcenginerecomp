"""Authored CLI coverage for opt-in bounded retired-instruction observations."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from pcerecomp.capture import load_capture

ROOT=Path(__file__).resolve().parent.parent
NAME='pce-headless.exe' if os.name=='nt' else 'pce-headless'
BINARY=Path(os.environ.get('PCE_TEST_HEADLESS',ROOT/'build'/NAME))
MPRS='255,248,128,129,130,131,132,0'


@unittest.skipUnless(BINARY.is_file(),'Build pce-headless for code capture checks')
class HeadlessCaptureTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.image=self.root/'authored.bin';self.out=self.root/'new capture.json'

    def invoke(self, program=b'\xea', steps=1, ticks=10000, options=None):
        self.image.write_bytes(program)
        command=[str(BINARY),str(self.image),'0x100000','0x4000',MPRS,str(steps),str(ticks),'hybrid']
        command+=['--code-capture',str(self.out)] if options is None else options
        result=subprocess.run(command,capture_output=True,text=True,timeout=5)
        self.assertEqual(self.image.read_bytes(),program)
        return result

    def report(self,result):
        self.assertEqual(result.returncode,0,result.stderr)
        report,digest=load_capture(self.out)
        state=json.loads(result.stdout)
        self.assertEqual(report['retired_instructions'],state['native_steps']+state['interpreter_steps'])
        return report,state

    def test_exact_instruction_length_and_tier_hits(self):
        report,state=self.report(self.invoke(b'\xa9\x45\xea'))
        self.assertEqual(report['capacity'],16384)
        self.assertTrue(report['complete'])
        self.assertEqual(report['retired_instructions'],1)
        self.assertEqual(report['observations'],[{'pc':0x4000,'mpr':[255,248,128,129,130,131,132,0],
            'physical':[0x100000,0x100001],'data':[0xa9,0x45],
            'native_hits':state['native_steps'],'interpreted_hits':state['interpreter_steps']}])
        self.assertEqual(state['a'],0x45)

    def test_same_pc_mutated_variants_are_distinct(self):
        # LDA #1; INC $4001; BRA $4000. The INC creates new observed literals.
        report,state=self.report(self.invoke(bytes([0xa9,1,0xee,1,0x40,0x80,0xf9]),steps=7))
        variants=[i['data'] for i in report['observations'] if i['pc']==0x4000]
        self.assertEqual(variants,[[0xa9,1],[0xa9,2],[0xa9,3]])
        self.assertEqual(len(report['observations']),5)
        self.assertEqual(state['a'],3)

    def test_capacity_keeps_counting_known_identity(self):
        # NOP; JMP $4000. Only the first identity fits, but repeated hits count.
        report,state=self.report(self.invoke(bytes([0xea,0x4c,0,0x40]),steps=5,
            options=['--code-capture',str(self.out),'--capture-limit','1']))
        self.assertFalse(report['complete'])
        self.assertEqual(report['dropped_instructions'],2)
        self.assertEqual(report['unreadable_instructions'],0)
        self.assertEqual(len(report['observations']),1)
        entry=report['observations'][0]
        self.assertEqual(entry['native_hits']+entry['interpreted_hits'],3)

    def test_unsupported_and_budget_do_not_create_observations(self):
        for program,ticks,stop in [(bytes([0]),10000,'unsupported_instruction'),(bytes([0xea]),0,'budget')]:
            with self.subTest(stop=stop):
                if self.out.exists(): self.out.unlink()
                result=self.invoke(program,ticks=ticks)
                report,digest=load_capture(self.out)
                self.assertEqual(json.loads(result.stdout)['stop'],stop)
                self.assertEqual(report['observations'],[])
                self.assertEqual(report['retired_instructions'],0)
                self.assertTrue(report['complete'])

    def test_default_does_not_capture_or_add_diagnostic_fields(self):
        result=self.invoke(options=[])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(self.out.exists())
        self.assertNotIn('code_capture',json.loads(result.stdout))

    def test_input_existing_output_and_hardlink_are_protected(self):
        for destination in (self.image,self.out,self.root/'hardlink.json'):
            with self.subTest(destination=destination):
                self.image.write_bytes(b'\xea')
                if destination==self.out:self.out.write_bytes(b'owner bytes')
                if destination.name=='hardlink.json':os.link(self.image,destination)
                original=destination.read_bytes()
                result=self.invoke(options=['--code-capture',str(destination)])
                self.assertEqual(result.returncode,2)
                self.assertEqual(destination.read_bytes(),original)

    def test_rejects_other_output_alias(self):
        result=self.invoke(options=['--code-capture',str(self.out),'--frame-out',str(self.out)])
        self.assertEqual(result.returncode,2)
        self.assertFalse(self.out.exists())

    def test_capture_limit_requires_opt_in_and_bounds(self):
        for options in (['--capture-limit','1'],['--code-capture',str(self.out),'--capture-limit','0'],
                        ['--code-capture',str(self.out),'--capture-limit','65537'],
                        ['--code-capture',str(self.out),'--code-capture',str(self.out)]):
            with self.subTest(options=options):
                result=self.invoke(options=options)
                self.assertEqual(result.returncode,2)
                self.assertFalse(self.out.exists())

    def test_capture_window_excludes_precapture_instructions_and_conserves_execution(self):
        # LDA executes only during startup; the following BRA is the only
        # instruction retired after the first completed video frame.
        program=bytes([0xa9,0x37,0x80,0xfe])
        plain=self.invoke(program,steps=100000,ticks=2000000,
                          options=['--video-output','continuous'])
        self.assertEqual(plain.returncode,0,plain.stderr)
        baseline=json.loads(plain.stdout)
        result=self.invoke(program,steps=100000,ticks=2000000,
            options=['--video-output','continuous','--code-capture',str(self.out),
                     '--code-capture-start-frame','1'])
        self.assertEqual(result.returncode,0,result.stderr)
        state=json.loads(result.stdout);window=state.pop('code_capture_window')
        self.assertEqual(state,baseline)
        self.assertTrue(window['started'])
        self.assertEqual(window['requested_start_frame'],1)
        self.assertEqual(window['actual_start_frame'],1)
        self.assertGreater(window['actual_start_ticks'],0)
        capture,_=load_capture(self.out)
        retired=state['native_steps']+state['interpreter_steps']
        before=window['native_steps_before']+window['interpreter_steps_before']
        self.assertGreater(before,1)
        self.assertEqual(capture['retired_instructions'],retired-before)
        self.assertEqual([entry['data'] for entry in capture['observations']],[[0x80,0xfe]])
        self.assertTrue(capture['complete'])

    def test_capture_window_zero_and_unreached_have_explicit_start_metadata(self):
        for start in (0,1000):
            with self.subTest(start=start):
                if self.out.exists():self.out.unlink()
                result=self.invoke(bytes([0xa9,0x37,0x80,0xfe]),steps=20,
                    options=['--video-output','continuous','--code-capture',str(self.out),
                             '--code-capture-start-frame',str(start)])
                self.assertEqual(result.returncode,0,result.stderr)
                state=json.loads(result.stdout);window=state['code_capture_window']
                capture,_=load_capture(self.out)
                self.assertEqual(window['requested_start_frame'],start)
                self.assertEqual(window['started'],start==0)
                if start==0:
                    self.assertEqual(window['actual_start_frame'],0)
                    self.assertEqual(window['actual_start_ticks'],0)
                    self.assertEqual(capture['retired_instructions'],20)
                else:
                    for field in ('actual_start_frame','actual_start_ticks','native_steps_before','interpreter_steps_before'):
                        self.assertIsNone(window[field])
                    self.assertEqual(capture['retired_instructions'],0)
                    self.assertEqual(capture['observations'],[])

    def test_capture_window_requires_capture_continuous_and_strict_single_value(self):
        prefix=['--video-output','continuous','--code-capture',str(self.out)]
        invalid=[['--code-capture-start-frame','0'],
                 ['--code-capture',str(self.out),'--code-capture-start-frame','0'],
                 [*prefix,'--code-capture-start-frame'],
                 [*prefix,'--code-capture-start-frame','0','--code-capture-start-frame','1']]
        invalid += [[*prefix,'--code-capture-start-frame',value]
                    for value in ('-1','1.5','x','18446744073709551616')]
        for options in invalid:
            with self.subTest(options=options):
                result=self.invoke(options=options)
                self.assertEqual(result.returncode,2,result.stderr)
                self.assertFalse(self.out.exists())


if __name__=='__main__':unittest.main()
