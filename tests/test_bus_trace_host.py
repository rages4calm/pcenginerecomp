"""Authored raw-host observer smoke/refusal checks, without game media."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from tests.bus_reference_fixture import fixture
from pcerecomp.bus_trace import load_trace

BINARY = Path(os.environ['PCE_TEST_HEADLESS']) if 'PCE_TEST_HEADLESS' in os.environ else Path('build/pce-headless.exe' if os.name=='nt' else 'build/pce-headless')

@unittest.skipUnless(BINARY.is_file(), 'Build pce-headless for host tracing')
class BusTraceHostTests(unittest.TestCase):
    def command(self, image, output):
        return [str(BINARY.resolve()), '--hucard-reset', 'base', str(image), '10', '1000000', 'hybrid',
            '--audio-output', 'off', '--bus-trace', str(output), '--bus-trace-calls', '8',
            '--bus-trace-events', '60000', '--bus-trace-context', hashlib.sha256(image.read_bytes()).hexdigest(),
            '--bus-trace-source', 'b'*64, '--bus-trace-revision', 'a'*40]

    def test_known_no_module_host_closes_actual_interpreter_callbacks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); image=root/'fixture.pce'; output=root/'trace.jsonl'
            image.write_bytes(fixture('low')[0])
            result=subprocess.run(self.command(image,output),capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            host=json.loads(result.stdout); trace=load_trace(output)
            self.assertTrue(trace.final['complete'])
            self.assertEqual(trace.final['calls'],8)
            self.assertEqual(host['bus_trace']['native'],0)
            self.assertEqual(host['bus_trace']['interpreted'],8)
            self.assertEqual(trace.sha256,host['bus_trace_sha256'])
            self.assertEqual(trace.header['engine']['binary_sha256'],hashlib.sha256(BINARY.read_bytes()).hexdigest())
            self.assertEqual(host['interpreter_steps'],10)
            self.assertLess(trace.final['state']['ticks'],host['ticks'])
            again=subprocess.run(self.command(image,output),capture_output=True,text=True,timeout=20)
            self.assertNotEqual(again.returncode,0)
            self.assertEqual(trace.sha256,hashlib.sha256(output.read_bytes()).hexdigest())

    def test_host_refuses_alias_and_invalid_bounds_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); image=root/'fixture.pce'; output=root/'trace.jsonl'
            raw=fixture('low')[0]; image.write_bytes(raw)
            for flag,value in (('--bus-trace-calls','0'),('--bus-trace-events','60001'),
                               ('--bus-trace-source','invalid'),('--bus-trace',str(image))):
                command=self.command(image,output); command[command.index(flag)+1]=value
                result=subprocess.run(command,capture_output=True,text=True,timeout=20)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(image.read_bytes(),raw)
                self.assertFalse(output.exists())
