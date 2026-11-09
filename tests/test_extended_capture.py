"""Strict opt-in framed captures; authored records and real bounded host runs."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp.capture import (EXTENDED_FORMAT, EXTENDED_MAGIC,
    MAX_CAPTURE_BYTES, MAX_CAPTURE_LINE_BYTES, MAX_EXTENDED_CAPTURE_BYTES,
    MAX_EXTENDED_OBSERVATIONS, MAX_OBSERVATIONS, load_capture,
    parse_capture_bytes, validate_capture)
from tests.test_capture import capture, observation

ROOT = Path(__file__).resolve().parents[1]
HEADLESS = Path(os.environ.get('PCE_TEST_HEADLESS', ROOT/'build'/('pce-headless.exe' if os.name == 'nt' else 'pce-headless')))


def extended(items=None, capacity=65537, **values):
    result = capture(items, capacity=capacity)
    result.update(schema=2, format=EXTENDED_FORMAT, runtime_abi=29)
    result.update(values)
    return result


def wire(value):
    header = {k: v for k, v in value.items() if k not in ('format', 'schema', 'observations')}
    encode = lambda row: json.dumps(row, separators=(',', ':')).encode('utf-8')+b'\n'
    return (EXTENDED_MAGIC+encode(header)+b''.join(encode(row) for row in value['observations'])
            +encode(dict(record='end', observations=len(value['observations']))))


class ExtendedCaptureTests(unittest.TestCase):
    def test_exact_framing_raw_sha_and_full_identity_variants(self):
        changed = [255, 248, 128, 129, 130, 131, 132, 1]
        value = extended([observation(), observation(raw=(0xA9, 43)), observation(mpr=changed)])
        raw = wire(value)
        self.assertEqual(parse_capture_bytes(raw), value)
        self.assertEqual(len(validate_capture(value)), 3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'original.jsonl';path.write_bytes(raw)
            actual, digest = load_capture(path)
            self.assertEqual(actual, value)
            self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
            self.assertEqual(path.read_bytes(), raw)

    def test_opt_in_schema_and_caps_do_not_widen_legacy(self):
        self.assertEqual((MAX_CAPTURE_BYTES, MAX_OBSERVATIONS), (64*1024*1024, 65536))
        self.assertEqual((MAX_EXTENDED_CAPTURE_BYTES, MAX_EXTENDED_OBSERVATIONS), (512*1024*1024, 1048576))
        for capacity in (1, 65536, 65537, 1048576):
            self.assertEqual(len(validate_capture(extended(capacity=capacity))), 1)
        for capacity in (0, True, 1.0, 1048577):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                parse_capture_bytes(wire(extended(capacity=capacity)))
        with self.assertRaises(ValueError): validate_capture(capture(capacity=65537))
        with self.assertRaises(ValueError): parse_capture_bytes(json.dumps(extended()).encode())
        with self.assertRaises(ValueError): parse_capture_bytes(json.dumps(extended()).encode(), validate=False)
        with self.assertRaises(ValueError): validate_capture(extended() | {'schema': 1})
        with self.assertRaises(ValueError): validate_capture(extended() | {'runtime_abi': 28})
        with self.assertRaises(ValueError): validate_capture(extended() | {'format': 'other'})

    def test_loss_origin_and_reference_policy_retained(self):
        origin = dict(sha256='a'*64, ticks=900, frame=7, native_steps=500, interpreter_steps=3)
        policy = dict(schema=1, reference_enabled=True, selected=True, configured_tier='native',
                      effective_policy='interpreter', effective_native_span=0)
        value = extended([observation(interpreted=3)], checkpoint_origin=origin, execution_policy=policy,
                         dropped_instructions=2, unreadable_instructions=1, retired_instructions=6, complete=False)
        self.assertEqual(parse_capture_bytes(wire(value)), value)
        invalid = copy.deepcopy(value);invalid['observations'][0]['native_hits']=1;invalid['retired_instructions']=7
        with self.assertRaisesRegex(ValueError, 'native retirements'):parse_capture_bytes(wire(invalid))

    def test_missing_truncated_extra_and_forged_terminal_records_refuse(self):
        raw = wire(extended())
        lines = raw.splitlines(keepends=True)
        variants = [b'', EXTENDED_MAGIC, b''.join(lines[:-1]), raw[:-1], raw+b'\n',
                    raw+b'{}\n', raw+lines[-1], b''.join(lines[:-1])+b'{"record":"end","observations":2}\n',
                    b''.join(lines[:-1])+b'{"record":"end","observations":true}\n',
                    b''.join(lines[:-1])+b'{"record":"end","observations":1,"extra":0}\n',
                    b''.join(lines[:-1])+b'{"observations":1,"record":"end"}\n',
                    b''.join(lines[:-1])+b'{"record":"other","observations":1}\n']
        for index, invalid in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):parse_capture_bytes(invalid)

    def test_header_and_observation_fields_are_closed(self):
        raw = wire(extended());lines=raw.splitlines(keepends=True)
        header = json.loads(lines[1])
        for key, value in (('schema', 2), ('format', EXTENDED_FORMAT), ('observations', []), ('extra', 1)):
            changed = header | {key: value}
            invalid = lines[0]+json.dumps(changed).encode()+b'\n'+b''.join(lines[2:])
            with self.subTest(key=key), self.assertRaises(ValueError):parse_capture_bytes(invalid)
        for invalid in (b'[]\n', b'null\n', b'\n', b'{"record":"data"}\n',
                        json.dumps(observation() | {'extra': 1}).encode()+b'\n'):
            with self.subTest(row=invalid[:40]), self.assertRaises(ValueError):
                parse_capture_bytes(lines[0]+lines[1]+invalid+lines[-1])
        # Duplicate identities cannot be smuggled in as repeated data records.
        with self.assertRaisesRegex(ValueError, 'Duplicate observed'):
            parse_capture_bytes(wire(extended([observation(), observation()])))

    def test_duplicate_keys_floats_nonfinite_and_invalid_encoding_refuse(self):
        raw = wire(extended());lines=raw.splitlines(keepends=True)
        for replacement in (b'"capacity":1e9999', b'"capacity":NaN', b'"capacity":1.0',
                            b'"capacity":65537,"capacity":65537'):
            invalid=raw.replace(b'"capacity":65537',replacement)
            with self.subTest(value=replacement), self.assertRaises(ValueError):parse_capture_bytes(invalid)
        for header in (b'\xef\xbb\xbf'+lines[1], lines[1].decode().encode('utf-16'), b'\xff\n',
                       lines[1].replace(b'"capacity"', b'"ca\0pacity"')):
            with self.subTest(header=header[:12]), self.assertRaises(ValueError):
                parse_capture_bytes(lines[0]+header+b''.join(lines[2:]))

    def test_record_and_total_bounds_and_validate_false_still_check_wire(self):
        raw=wire(extended());lines=raw.splitlines(keepends=True)
        oversized=lines[0]+b' '*(MAX_CAPTURE_LINE_BYTES+1)+b'\n'+b''.join(lines[2:])
        with self.assertRaisesRegex(ValueError, '64 KiB'):parse_capture_bytes(oversized)
        with patch('pcerecomp.capture.MAX_EXTENDED_CAPTURE_BYTES', len(raw)-1):
            with self.assertRaisesRegex(ValueError, '512 MiB'):parse_capture_bytes(raw)
        with patch('pcerecomp.capture.MAX_CAPTURE_BYTES', 20):
            self.assertEqual(parse_capture_bytes(raw)['schema'], 2)
            with self.assertRaisesRegex(ValueError, '64 MiB'):parse_capture_bytes(json.dumps(capture()).encode())
        bad=extended();bad['observations'][0]['physical']=[0, 1]
        self.assertEqual(parse_capture_bytes(wire(bad),validate=False),bad)
        with self.assertRaisesRegex(ValueError, 'physical mapping'):parse_capture_bytes(wire(bad))
        with self.assertRaises(ValueError):parse_capture_bytes(raw[:-1],validate=False)


@unittest.skipUnless(HEADLESS.is_file(), 'Build headless runner or set PCE_TEST_HEADLESS')
class ExtendedHostTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        card=bytearray(262144);card[:64]=bytes([0xEA])*64;card[0x1FFE:0x2000]=bytes([0,0xE0])
        self.card=self.root/'authored.pce';self.card.write_bytes(card)

    def run_host(self, output, *options):
        return subprocess.run([str(HEADLESS),'--system-card-reset','standard',str(self.card),'16','100000','hybrid',
                               '--code-capture',str(output),*options],capture_output=True,text=True,timeout=15)

    def test_actual_legacy_default_and_explicit_profile_preserve_bytes_and_clocks(self):
        outputs=[];states=[]
        for name, options in (('omitted',()),('legacy',('--capture-profile','legacy')),
                              ('extended',('--capture-profile','extended','--capture-limit','65537'))):
            path=self.root/(name+'.json')
            done=self.run_host(path,*options)
            self.assertEqual(done.returncode,0,done.stderr)
            state=json.loads(done.stdout);states.append(state);outputs.append(path)
            self.assertEqual({k:state[k] for k in ('pc','cycles','ticks','native_steps','interpreter_steps')},
                             dict(pc=0xE010,cycles=32,ticks=384,native_steps=0,interpreter_steps=16))
        self.assertEqual(outputs[0].read_bytes(),outputs[1].read_bytes())
        self.assertEqual(states[0],states[1]);self.assertEqual(states[1],states[2])
        value,digest=load_capture(outputs[2])
        self.assertEqual(value['schema'],2);self.assertEqual(value['capacity'],65537)
        self.assertEqual(len(value['observations']),16)
        self.assertEqual(digest,hashlib.sha256(outputs[2].read_bytes()).hexdigest())

    def test_invalid_profile_duplicate_or_capacity_refuses_before_output(self):
        for index,options in enumerate((('--capture-limit','65537'),('--capture-profile','other'),
            ('--capture-profile','extended','--capture-limit','1048577'),
            ('--capture-profile','extended','--capture-profile','extended'),
            ('--capture-limit','1','--capture-limit','2'))):
            output=self.root/f'invalid-{index}.json'
            done=self.run_host(output,*options)
            self.assertNotEqual(done.returncode,0,done.stdout)
            self.assertFalse(output.exists())
        done=subprocess.run([str(HEADLESS),'--system-card-reset','standard',str(self.card),'16','100000','hybrid',
                             '--capture-profile','extended'],capture_output=True,text=True,timeout=15)
        self.assertNotEqual(done.returncode,0)
        self.assertIn('requires --code-capture',done.stderr)

    def test_actual_extended_reference_window_live_metadata_and_closure(self):
        from scripts.dev_client import DevClient
        image=self.root/'mutating.bin'
        image.write_bytes(bytes.fromhex('A9 01 8D 00 20 EE 01 40 80 F6'))
        output=self.root/'reference.jsonl'
        process=subprocess.Popen([str(HEADLESS),str(image),'0x100000','0x4000',
            '255,248,128,129,130,131,132,0','1000000','100000000','hybrid',
            '--code-capture',str(output),'--capture-profile','extended','--capture-limit','65537',
            '--video-output','continuous','--dev-port','0','--dev-start-paused','on',
            '--dev-reference','on','--wall-seconds','10'],stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        def cleanup():
            if process.poll() is None:
                process.kill();process.wait(timeout=5)
            process.stdout.close();process.stderr.close()
        self.addCleanup(cleanup)
        line=process.stderr.readline()
        self.assertTrue(line.startswith('PCE_DEV_PORT='),line)
        client=DevClient(int(line.strip().split('=')[1]),timeout=5)
        self.addCleanup(client.close)
        fresh=client.capture_summary()
        self.assertEqual((fresh['schema'],fresh['capture_schema'],fresh['capture_format']),
                         (1,2,EXTENDED_FORMAT))
        self.assertEqual(fresh['capacity'],65537)
        client.advance(1,reference=True)
        before=client.call('status')
        live=client.capture_history()
        after=client.call('status')
        self.assertEqual({k:v for k,v in before.items() if k!='id'},
                         {k:v for k,v in after.items() if k!='id'})
        self.assertEqual(output.stat().st_size,0)
        self.assertTrue(live['execution_policy']['selected'])
        self.assertEqual(live['native_instructions'],0)
        self.assertEqual(len([row for row in live['sources'] if row['pc']==0x4000]),256)
        client.call('quit')
        stdout,stderr=process.communicate(timeout=10)
        self.assertEqual(process.returncode,0,stderr)
        raw,digest=load_capture(output)
        self.assertEqual(raw['schema'],2)
        self.assertEqual(raw['execution_policy'],live['execution_policy'])
        self.assertEqual(raw['retired_instructions'],live['retired_instructions'])
        self.assertEqual(raw['retired_instructions'],json.loads(stdout)['interpreter_steps'])
        self.assertEqual(digest,hashlib.sha256(output.read_bytes()).hexdigest())
        self.assertEqual({(r['pc'],tuple(r['mpr']),r['native_hits'],r['interpreted_hits']) for r in raw['observations']},
                         {(r['pc'],tuple(r['mpr']),r['native_hits'],r['interpreted_hits']) for r in live['sources']})

    def test_actual_cpp_observer_exceeds_legacy_identity_capacity_and_preserves_variants(self):
        binary=HEADLESS.with_name('pce-code-capture-tests.exe' if os.name=='nt' else 'pce-code-capture-tests')
        if not binary.is_file():self.skipTest('Build code-capture C++ test runner')
        destination=self.root/'actual-observer'
        done=subprocess.run([str(binary),str(destination)],capture_output=True,text=True,timeout=15)
        self.assertEqual(done.returncode,0,done.stderr)
        large,digest=load_capture(destination/'extended.jsonl')
        self.assertEqual(len(large['observations']),65537)
        self.assertEqual((large['retired_instructions'],large['dropped_instructions']), (65540,2))
        self.assertEqual(sum(row['native_hits'] for row in large['observations']),1)
        self.assertEqual(sum(row['interpreted_hits'] for row in large['observations']),65537)
        variants=[row for row in large['observations'] if row['pc']==0]
        self.assertEqual(len(variants),2)
        self.assertEqual([row['mpr'][7] for row in variants],[0,1])
        self.assertEqual(variants[0]['data'],variants[1]['data'])
        self.assertEqual(digest,hashlib.sha256((destination/'extended.jsonl').read_bytes()).hexdigest())
        legacy,_=load_capture(destination/'observed.json')
        framed,_=load_capture(destination/'extended-variants.jsonl')
        self.assertEqual(framed,legacy | dict(schema=2,format=EXTENDED_FORMAT))
        maximum,_=load_capture(destination/'extended-maximum.jsonl')
        self.assertEqual(maximum['capacity'],1048576)
        self.assertEqual(maximum['observations'],[])
        self.assertEqual(maximum['checkpoint_origin']['native_steps'],100)
        self.assertTrue(maximum['execution_policy']['selected'])


if __name__ == '__main__':unittest.main()
