"""Fresh compiled native/interpreter observer roundtrips on authored firmware.

These are internal tier/disabled-path checks, not independent emulator proof.
Original Geargrafx/Beetle qualification is a separate reference runner.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from pcerecomp import bus_trace
from pcerecomp.isa import _LENGTH, _ROWS
from tests.bus_reference_fixture import expected_accesses, fixture

ROOT = Path(__file__).resolve().parent.parent
NAME = 'pce-bus-trace-tests.exe' if os.name == 'nt' else 'pce-bus-trace-tests'
CANDIDATES = ([Path(os.environ.get('PCE_TEST_BUS_TRACE', os.environ.get('PCE_TEST_BUS_PROBE')))]
    if 'PCE_TEST_BUS_TRACE' in os.environ or 'PCE_TEST_BUS_PROBE' in os.environ else
    ([Path(os.environ['PCE_TEST_HEADLESS']).parent/NAME] if 'PCE_TEST_HEADLESS' in os.environ else []) +
    [ROOT/'build'/NAME, ROOT/'build'/'Release'/NAME])
BINARY = next((path for path in CANDIDATES if path.is_file()), None)


@unittest.skipUnless(BINARY, 'Build pce-bus-trace-tests for compiled observer roundtrips')
class BusTraceIntegrationTests(unittest.TestCase):
    def test_all_256_compiled_source_identities_match_independent_decoder_extents(self):
        result=subprocess.run([str(BINARY),'--source-identities'],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        rows=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(rows),256)
        for opcode,row in enumerate(rows):
            with self.subTest(opcode=hex(opcode)):
                length=_LENGTH[_ROWS[opcode].split('.')[1]]
                self.assertEqual(row['opcode'],opcode)
                self.assertEqual(row['pc'],0x2870)
                self.assertEqual(row['length'],length)
                source=bytes((opcode,17,34,51,68,85,102))[:length]
                self.assertEqual(row['sha256'],bus_trace.source_identity(0x2870,[248]*8,source)['sha256'])

    def run_case(self, profile, tier, observed=True):
        rom, description = fixture(profile)
        with tempfile.TemporaryDirectory(prefix='pce-bus-roundtrip-') as temporary:
            root = Path(temporary)
            image, output = root/'authored.pce', root/'private.jsonl'
            image.write_bytes(rom)
            binary_sha = hashlib.sha256(BINARY.read_bytes()).hexdigest()
            source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            command = [str(BINARY), '--probe', profile, tier, str(image), str(output),
                '1'*40, source_sha, binary_sha, description['fixture_sha256'],
                'observed' if observed else 'disabled']
            result = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(image.read_bytes(), rom)
            counters = json.loads(result.stdout)
            if not observed:
                self.assertFalse(output.exists())
                return None, counters, description
            trace = bus_trace.load_trace(output)
            self.assertEqual(trace.header['engine']['binary_sha256'], binary_sha)
            self.assertEqual(trace.header['engine']['source_sha256'], source_sha)
            self.assertEqual(trace.header['fixture_sha256'], hashlib.sha256(rom).hexdigest())
            self.assertTrue(trace.final['complete'])
            self.assertEqual(trace.final['calls'], description['steps'])
            self.assertEqual(trace.final['retired'], counters['native']+counters['interpreted'])
            self.assertEqual(trace.final['events'], counters['events'])
            self.assertEqual(trace.final['state']['ticks'], counters['ticks'])
            self.assertEqual(trace.initial['clock_divisor'], description['entry_divisor'])
            return trace, counters, description

    def test_compiled_native_and_interpreter_streams_have_exact_internal_parity(self):
        for profile in ('low', 'high', 'block'):
            with self.subTest(profile=profile):
                native, n, _ = self.run_case(profile, 'native')
                interpreter, i, _ = self.run_case(profile, 'interpreter')
                comparison = bus_trace.compare_traces(native, interpreter, structural=True)
                self.assertTrue(comparison['equal'], comparison['first_difference'])
                self.assertTrue(comparison['structural_correspondence']['timing_equal'])
                self.assertEqual(n['native'], native.final['retired'])
                self.assertEqual(n['interpreted'], 0)
                self.assertEqual(i['native'], 0)
                self.assertEqual(i['interpreted'], interpreter.final['retired'])
                self.assertFalse(comparison['counter_observations']['native']['equal'])

    def test_actual_callbacks_match_literal_addresses_mapping_values_and_order(self):
        for profile in ('low', 'high', 'block'):
            for tier in ('native', 'interpreter'):
                with self.subTest(profile=profile,tier=tier):
                    trace, _, _ = self.run_case(profile, tier)
                    actual = [{field:event[field] for field in
                        ('direction','logical','value','mpr','physical')} for event in trace.events]
                    self.assertEqual(actual, expected_accesses(profile))
                    self.assertTrue(all(event['purpose'] is None and event['dummy'] is None
                                        for event in trace.events))
                    self.assertFalse(trace.header['capabilities']['fetch'])
                    self.assertFalse(trace.header['capabilities']['idle'])

    def test_every_actual_entry_identity_binds_authored_bytes_at_that_boundary(self):
        for profile in ('low', 'high', 'block'):
            with self.subTest(profile=profile):
                trace, _, description = self.run_case(profile, 'native')
                for call, instruction in zip(trace.calls, description['instructions'], strict=True):
                    entry = call['entry']
                    self.assertEqual(entry['entry']['pc'], instruction['pc'])
                    self.assertEqual(entry['source'], bus_trace.source_identity(instruction['pc'],
                        entry['entry']['mpr'], bytes(instruction['data'])))
                # Same PC/mapping is insufficient when mutable encoded data differs.
                first = trace.calls[0]['entry']
                raw = bytes(description['instructions'][0]['data'])
                changed = bytes((raw[0], raw[1]^1))
                self.assertNotEqual(first['source'], bus_trace.source_identity(first['entry']['pc'],
                    first['entry']['mpr'], changed))

    def test_observation_preserves_full_guest_checkpoint_in_both_tiers_and_speeds(self):
        for profile in ('low', 'high', 'block'):
            for tier in ('native', 'interpreter'):
                with self.subTest(profile=profile,tier=tier):
                    _, observed, _ = self.run_case(profile, tier)
                    _, disabled, _ = self.run_case(profile, tier, observed=False)
                    self.assertEqual(observed['checkpoint_sha256'], disabled['checkpoint_sha256'])
                    for field in ('ticks', 'native', 'interpreted'):
                        self.assertEqual(observed[field], disabled[field])
                    self.assertEqual(disabled['calls'], 0)
                    self.assertEqual(disabled['events'], 0)

    def test_real_serialized_clock_difference_remains_a_failed_comparison(self):
        trace, _, _ = self.run_case('low', 'native')
        rows = [copy.deepcopy(trace.header), dict(type='initial',state=copy.deepcopy(trace.initial)),
                *copy.deepcopy(list(trace.records)), copy.deepcopy(trace.final)]
        event = next(row for row in rows if row['type']=='access')
        event['ticks'] += 1
        shifted = bus_trace.parse_trace(bus_trace.encode_records(rows))
        result = bus_trace.compare_traces(trace, shifted, structural=True)
        self.assertFalse(result['equal'])
        self.assertTrue(result['structural_correspondence']['matched'])
        self.assertFalse(result['structural_correspondence']['timing_equal'])
        self.assertEqual(result['first_difference']['field'], 'record.ticks')


if __name__ == '__main__':
    unittest.main()
