"""Independently authored PSG signal-fixture gates and fresh-process runner."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import generate_psg_pipeline_fixture as fixture


class PsgPipelineFixtureTests(unittest.TestCase):
    def test_checked_in_authored_signal_is_current(self):
        expected=Path(__file__).with_name('psg_pipeline_fixture.hpp').read_text()
        self.assertEqual(fixture.render(),expected)

    def test_all_decimal_gain_quantization_levels(self):
        self.assertEqual(fixture.gains(),[341,287,241,203,171,143,121,101,85,72,
            60,51,42,36,30,25,21,18,15,12,10,9,7,6,5,4,3,3,2,2,1,0])

    def test_authored_source_has_odd_half_and_unclipped_headroom(self):
        centered=fixture.source_sums(True)
        unipolar=fixture.source_sums(False)
        self.assertEqual(centered[0],[63426,32643])
        self.assertEqual(centered[4],[-63426,-32643])
        self.assertEqual(unipolar[0],[126852,65286])
        self.assertGreater(max(x[0] for x in unipolar),65535)
        self.assertTrue(any(pair[1]%2 for pair in centered))
        self.assertEqual(centered[40:],[[0,-993]]*216)

    def test_binary32_stores_unclipped_history_and_half_values(self):
        self.assertEqual(fixture.hpf([[3,-3],[6,-6]]),[[1,-1],[2,-2]])
        self.assertEqual(fixture.hpf([[200000,-200000],[0,0]]),
                         [[32767,-32768],[-150,150]])
        self.assertEqual(fixture.hpf([[10571,-10571]]*2),[[5285,-5285],[5277,-5277]])

    def test_direct_convolution_rational_frames_and_zero(self):
        for length in (1,2,147,256):
            self.assertEqual(fixture.resample([[0,0]]*length),[[0,0]]*(length*160//147))


def fresh_process_run(binary,out):
    binary=Path(binary).resolve()
    out=Path(out).resolve()
    if not binary.is_file() or out.exists():
        raise ValueError('require an actual test binary and a new private output directory')
    out.mkdir(parents=True)
    report={'schema':1,'scope':'Authored PSG audio-only payload; two actual fresh processes, no guest program/media/save input.',
            'binary':str(binary),'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
            'native_retirements':0,'interpreted_retirements':0,'commands':[]}
    for operation in ('--checkpoint-write','--checkpoint-resume'):
        command=[str(binary),operation,str(out)]
        completed=subprocess.run(command,capture_output=True,text=True,timeout=90)
        report['commands'].append({'argv':command,'returncode':completed.returncode,
                                   'stdout':completed.stdout,'stderr':completed.stderr})
        if completed.returncode:
            raise RuntimeError(completed.stdout+completed.stderr)
    checkpoints=sorted(out.glob('*.checkpoint'))
    expected=sorted(out.glob('*.expected'))
    if len(checkpoints)!=12 or len(expected)!=12:
        raise ValueError('finite process matrix did not produce all 12 checkpoints/endpoints')
    bindings={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in checkpoints+expected}
    command=[str(binary),'--checkpoint-write',str(out)]
    duplicate=subprocess.run(command,capture_output=True,text=True,timeout=90)
    report['commands'].append({'argv':command,'returncode':duplicate.returncode,
                              'stdout':duplicate.stdout,'stderr':duplicate.stderr})
    if not duplicate.returncode or 'must be empty' not in duplicate.stderr:
        raise ValueError('existing authored checkpoints were not explicitly preserved')
    negative=out/'truncated-copy';negative.mkdir()
    for path in checkpoints+expected:
        shutil.copyfile(path,negative/path.name)
    target=negative/'0-489.checkpoint'
    target.write_bytes(target.read_bytes()[:17])
    command=[str(binary),'--checkpoint-resume',str(negative)]
    refused=subprocess.run(command,capture_output=True,text=True,timeout=90)
    report['commands'].append({'argv':command,'returncode':refused.returncode,
                              'stdout':refused.stdout,'stderr':refused.stderr})
    if not refused.returncode:
        raise ValueError('actually written/reloaded truncated checkpoint copy was accepted')
    if bindings!={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in checkpoints+expected}:
        raise ValueError('original authored checkpoint artifacts changed')
    report.update(result='pass',checkpoint_cases=12,fresh_restore_processes=1,
                  written_negative_cases=2,artifact_sha256=bindings,
                  source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                    [Path(__file__),Path(fixture.__file__),Path(__file__).with_name('psg_pipeline_tests.cpp'),
                     Path(__file__).with_name('psg_pipeline_fixture.hpp')]})
    (out/'fresh-process-result.json').write_text(json.dumps(report,indent=2)+'\n')
    print('12 authored PSG fresh-process checkpoints passed; truncated copy refused; zero guest retirements')


if __name__=='__main__':
    if '--fresh' in sys.argv:
        import argparse
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--fresh',type=Path,required=True)
        parser.add_argument('--out',type=Path)
        args=parser.parse_args()
        if args.out:
            fresh_process_run(args.fresh,args.out)
        else:
            with tempfile.TemporaryDirectory(prefix='pce-psg-pipeline-') as directory:
                fresh_process_run(args.fresh,Path(directory)/'authored')
    else:
        unittest.main()
