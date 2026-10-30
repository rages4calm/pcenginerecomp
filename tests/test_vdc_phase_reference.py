"""Authored phase-sweep, source/work, original-call and HSW controls."""
import copy
import hashlib
import itertools
from pathlib import Path
import tempfile
import unittest

from tests.vdc_phase_fixture import cases, program, expected_vram, expected_wram, MPR
from scripts import vdc_phase_reference as reference
from scripts import vdc_phase_qualify as qualification


def executed(case):
    _, markers, plan = program(case)
    return [dict(source, hits=1) for source in plan if source['pc'] != markers['done']]


def hsw_facts():
    case = next(c for c in cases() if (c['access'], c['divisor'], c['vce'], c['words'], c['pad'])
                == ('high', 12, 3, 127, 1))
    # Launch at h1215. 508 VCE3 dots end at next-line h9. The38-cycle
    # setup advances456 ticks, so target h306 has508-152=356 dots left.
    def phase(tick, hclock, read, dma, selected):
        return [tick, hclock, hclock // 3, 100, 100, 3, 0,
                32 + 1024 - hclock // 3, 3, read, 0, 0, 0, dma, 0, 1,
                0, 0, 0, 1365, 0, 0, 0x5AA5, 0, 127, 0, 8192, 126,
                0, selected, 0, 0, 0x7F1F, 0x7F7F, 0]
    return case, dict(before=phase(1215, 1215, 0, 0, 18)), dict(before=phase(1671, 306, 1, 356, 2))


def original_tai_group():
    case = next(c for c in cases() if c['access'] == 'tai' and c['divisor'] == 3)
    spans = []
    tick = 1000
    for n, dynamic, before_dma, after_dma, before_read, after_read in (
            (42, 0, 6, 5, 1, 1), (6, 0, 5, 2, 1, 1),
            (3, 1, 2, 1, 1, 1), (3, 1, 1, 0, 1, 1), (3, 1, 0, 0, 1, 0),
            (18, 0, 0, 0, 0, 0), (6, 0, 0, 0, 0, 0),
            (18, 0, 0, 0, 1, 0), (9, 0, 0, 0, 0, 0)):
        spans.append([tick, n, tick + n, dynamic, tick % 1365, before_dma,
                      after_dma, before_read, after_read, 0, 0, 0])
        tick += n
    return case, dict(bytes=[0xF3, 2, 0, 0, 0x22, 2, 0], before=[1000], after=[1108],
                      ticks=108, wait_ticks=9, calls=4, internal=21, clocks=spans,
                      call_rows=[[1, 42, 0, 0, 0, 0, 1, 0],
                                 [2, 33, 15, 0, 1, 5, 6, 9],
                                 [3, 24, 6, 0, 6, 7, 8, 0],
                                 [4, 9, 0, 1, 8, 8, 9, 0]], events=[])


class VdcPhaseReferenceTests(unittest.TestCase):
    def test_forty_eight_guest_only_recipes_and_source_literals(self):
        matrix = cases()
        self.assertEqual(len(matrix), 48)
        self.assertEqual(len({c['id'] for c in matrix}), 48)
        self.assertEqual({(c['divisor'], c['vce'], c['access'], c['words'], c['pad']) for c in matrix},
                         set(itertools.product((3, 12), (4, 3, 2), ('high', 'tai'), (127, 4096), (0, 1))))
        for case in matrix:
            rom, markers, plan = program(case)
            self.assertEqual(len(rom), 262144)
            self.assertTrue(all(bytes(rom[p] for p in row['physical']) == bytes(row['data']) for row in plan))
            self.assertEqual(next(r['data'] for r in plan if r['pc'] == markers['launch']), [0x8D, 3, 0])
            self.assertEqual(next(r['data'] for r in plan if r['pc'] == markers['target']),
                             [0xAD, 3, 0] if case['access'] == 'high' else [0xF3, 2, 0, 0, 0x22, 2, 0])
            self.assertEqual(sum(row['data'] == [0x48] for row in plan), case['pad'])
            for row in plan:
                if row['data'][0] in (0xAD, 0x8D):
                    address = row['data'][1] | row['data'][2] << 8
                    self.assertFalse(0x1800 <= address < 0x2000, 'No CD protocol in the no-CD source plan')
            vram = expected_vram(case)
            self.assertEqual({i: v for i, v in enumerate(vram) if v},
                             {0: 0xA65C, case['words'] - 1: 0x5AA5,
                              8192: 0xA65C, 8192 + case['words'] - 1: 0x5AA5})
            self.assertEqual(expected_wram(case)[0x15], 0xA6 if case['access'] == 'high' else 2)

    def test_full_source_identity_excludes_compiled_terminal_and_duplicate_work(self):
        case = cases()[0]
        rows = executed(case)
        reference.validate_hits(rows, case)
        for page in range(8):
            bad = copy.deepcopy(rows)
            bad[0]['mpr'][page] ^= 1
            with self.subTest(page=page), self.assertRaises(ValueError):
                reference.validate_hits(bad, case)
        for mutate in ('operand', 'physical', 'duplicate', 'missing', 'bool-hit', 'terminal'):
            bad = copy.deepcopy(rows)
            if mutate == 'operand':
                bad[0]['data'][0] ^= 1
            elif mutate == 'physical':
                bad[0]['physical'][0] ^= 1
            elif mutate == 'duplicate':
                bad.append(copy.deepcopy(bad[0]))
            elif mutate == 'missing':
                bad.pop()
            elif mutate == 'bool-hit':
                bad[0]['hits'] = True
            else:
                _, markers, plan = program(case)
                bad.append(dict(next(row for row in plan if row['pc'] == markers['done']), hits=1))
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                reference.validate_hits(bad, case)

    def test_actual_capture_joins_whole_source_and_execution_tier(self):
        case = cases()[0]
        rows = executed(case)
        capture = dict(schema=1, runtime_abi=reference.ABI, capacity=len(rows),
                       dropped_instructions=0, unreadable_instructions=0,
                       retired_instructions=len(rows), complete=True,
                       observations=[{k: v for k, v in row.items() if k != 'hits'}
                                     | dict(native_hits=1, interpreted_hits=0) for row in rows])
        reference.validate_capture(capture, case, 'native')
        with self.assertRaises(ValueError):
            reference.validate_capture(capture, case, 'interpreter')
        bad = copy.deepcopy(capture)
        bad['retired_instructions'] += 1
        with self.assertRaises(ValueError):
            reference.validate_capture(bad, case, 'native')

    def test_original_call_work_is_variable_length_not_retired_opcodes(self):
        for case in (cases()[0], next(c for c in cases() if c['access'] == 'tai')):
            hits = reference.validate_hits(executed(case), case)
            tai = case['access'] == 'tai'
            # Three initial100-byte blocks, four6000-byte blocks and one
            # final100-byte block; TAI2 adds one retirement/two bytes.
            blocks, count = 8 + int(tai), 24400 + 2 * int(tai)
            actual = dict(instructions=len(hits), calls=len(hits) + count + blocks,
                          clock_calls=len(hits) + count + blocks, blocks=blocks,
                          block_bytes=count, wait_ticks=9)
            reference.validate_work(actual, case, hits, True)
            reference.validate_work(dict(actual, calls=len(hits), clock_calls=0), case, hits, False)
            for field in ('instructions', 'calls', 'blocks', 'block_bytes'):
                bad = dict(actual)
                bad[field] += 1
                with self.subTest(field=field), self.assertRaises(ValueError):
                    reference.validate_work(bad, case, hits, True)

    def test_tai_dynamic_wait_stays_inside_incomplete_byte_call(self):
        case, row = original_tai_group()
        reference.validate_original_group(row, case)
        for mutate in ('early-complete', 'missing-call', 'wrong-byte-clock', 'outside-internal', 'false-wait', 'bad-event'):
            bad = copy.deepcopy(row)
            if mutate == 'early-complete':
                bad['call_rows'][1][3] = 1
            elif mutate == 'missing-call':
                bad['call_rows'].pop(2)
            elif mutate == 'wrong-byte-clock':
                bad['call_rows'][1][1] += 3
            elif mutate == 'outside-internal':
                bad['call_rows'][1][5] -= 1
            elif mutate == 'false-wait':
                bad['clocks'][2][3] = 0
            else:
                bad['events'].append([2, 1054, 99, 0, 0, 0, 0, 0, 0, 0, 0, 0])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                reference.validate_original_group(bad, case)

    def test_real_hsw_hold_and_odd_dot_are_distinct_before_grant_twenty_four(self):
        case, launch, target = hsw_facts()
        proof = reference.classify_hsw(launch, target, case)
        self.assertFalse(proof['hsw_excluded'])
        self.assertEqual(proof['completion_tick'], 2739)
        self.assertEqual([c['hclock'] for c in proof['candidates']], [9, 12, 15, 18, 21, 24])
        self.assertEqual([c['gated'] for c in proof['candidates']], [True, True, True, True, False, False])
        self.assertEqual([c['hstate'] for c in proof['candidates']], [3] * 6)
        self.assertEqual(proof['candidates'][-1]['hclock'] // 3, 8)
        self.assertEqual(proof['candidates'][-2]['hclock'] // 3, 7)
        with self.assertRaisesRegex(ValueError, 'hsw_excluded'):
            reference.predict(launch, target, case, proof)

    def test_hsw_profile_requires_geometry_and_observed_queue_latches(self):
        case, launch, target = hsw_facts()
        for index, value in ((6, 3), (7, 1000), (9, 0), (10, 1), (11, 3), (12, 1),
                             (14, 1), (15, 0), (16, 128), (19, 100), (21, 1), (32, 0)):
            bad = copy.deepcopy(target)
            bad['before'][index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                reference.classify_hsw(launch, bad, case)
        bad = copy.deepcopy(target)
        bad['before'][12] = True
        with self.assertRaises(ValueError):
            reference.classify_hsw(launch, bad, case)

    def test_actual_hsw_callback_kernels_hold_through_odd_twenty_one_then_grant(self):
        case, launch, target = hsw_facts()
        proof = reference.classify_hsw(launch, target, case)
        spans = [[c['tick'], 3, c['tick'] + 3, 1, c['hclock'], 0, 0,
                  1, int(i < 5), 0, 3, 0] for i, c in enumerate(proof['candidates'])]
        reference.validate_candidate_spans(spans, proof)
        self.assertEqual([s[4] for s in spans if s[7] and not s[8]], [24])
        self.assertEqual(spans[-2][4:9], [21, 0, 0, 1, 1])
        for mutate in ('early-odd-grant', 'missing-callback', 'wrong-hstate',
                       'wrong-hsync', 'wrong-hclock', 'missing-final-grant'):
            bad = copy.deepcopy(spans)
            if mutate == 'early-odd-grant':
                bad[-2][8] = 0
            elif mutate == 'missing-callback':
                bad.pop(2)
            elif mutate == 'wrong-hstate':
                bad[0][10] = 0
            elif mutate == 'wrong-hsync':
                bad[0][11] = 1
            elif mutate == 'wrong-hclock':
                bad[0][4] += 1
            else:
                bad[-1][8] = 1
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                reference.validate_candidate_spans(bad, proof)

    def test_every_raw_and_compiled_original_source_binding_is_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw, compiled = root / 'raw', root / 'compiled'
            expected = {}
            bindings = dict(reference_raw_sources={}, reference_compile_sources={})
            for name, content in (('src/a.h', b'// Authored first fixture\n'),
                                  ('src/b.cpp', b'// Authored second fixture\n')):
                expected[name] = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
                for group, base, data in (('reference_raw_sources', raw, content.replace(b'\n', b'\r\n')),
                                          ('reference_compile_sources', compiled, content)):
                    path = base / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    bindings[group][str(path)] = hashlib.sha256(data).hexdigest()
            qualification.validate_original_sources(bindings, expected, raw, compiled)
            for group in ('reference_raw_sources', 'reference_compile_sources'):
                bad = copy.deepcopy(bindings)
                bad[group].pop(next(iter(bad[group])))
                with self.subTest(group=group), self.assertRaises(ValueError):
                    qualification.validate_original_sources(bad, expected, raw, compiled)
            bad = dict(expected)
            bad['src/b.cpp'] = '0' * 40
            with self.assertRaises(ValueError):
                qualification.validate_original_sources(bindings, bad, raw, compiled)
            # A changed raw source cannot hide behind its unchanged LF copy.
            path = raw / 'src/b.cpp'
            path.write_bytes(path.read_bytes() + b'// Changed\r\n')
            with self.assertRaises(ValueError):
                qualification.validate_original_sources(bindings, expected, raw, compiled)


if __name__ == '__main__':
    unittest.main()
