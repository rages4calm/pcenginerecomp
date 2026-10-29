"""Authored overlap fixtures and strict source/clock/phase admission controls."""
import copy
import itertools
from pathlib import Path
import tempfile
import unittest

from tests.vdc_adpcm_irq_fixture import (
    cases, program, expected_ram, expected_vram, expected_wram, MPR, WORDS,
)
from scripts import vdc_adpcm_irq_reference as reference
from scripts import vdc_adpcm_irq_qualify as qualification


def work(**changes):
    result = dict(instructions=0, calls=0, clock_calls=0, clock_ticks=0,
                  irqs=0, rtis=0, blocks=0, block_bytes=0,
                  adpcm_cause_groups=0, vdc_cause_groups=0, wait_ticks=0)
    result.update(changes)
    return result


def clock_group():
    """Compact authored observer ledger, not an emulator or device trace.

    TAI2 has 14 startup, two (6+2)-cycle bytes and a 3+8-cycle epilogue.
    Twelve dynamic three-tick slices demonstrate the source/grant topology.
    """
    case = next(c for c in cases() if c['access'] == 'tai' and c['policy'] == 'retain'
                and c['divisor'] == 3 and c['vce'] == 2)
    markers = program(case)[1]
    source = next(r for r in program(case)[2] if r['pc'] == markers['target'])
    spans = []
    tick = 1000
    for duration, waiting, pending, requests in (
            [(42, 0, 0, 0), (6, 0, 0, 0)]
            + [(3, 1, 0 if i == 0 else 1 if i <= 9 else 3,
                1 if i < 9 else 3) for i in range(12)]
            + [(18, 0, 3, 3), (6, 0, 3, 3), (18, 0, 3, 3), (33, 0, 3, 3)]):
        spans.append([tick, duration, tick + duration, waiting, pending, requests])
        tick += duration
    def kernel(pending, requests, dots, read=1, flags=False, status=64):
        return [1, 4, pending, requests, status, dots, read, 0, 0x5AA5, 0, 0, 0,
                12, 12 if flags else 0, int(flags), int(flags), int(flags),
                65535 if flags else 65534, int(flags)]
    edges = [
        dict(span=2, kinds=9, before=kernel(0, 0, 100), after=kernel(0, 1, 99, flags=True)),
        dict(span=3, kinds=16, before=kernel(1, 1, 99, flags=True), after=kernel(1, 1, 98, flags=True)),
        dict(span=11, kinds=5, before=kernel(1, 1, 1, flags=True), after=kernel(1, 3, 0, flags=True, status=80)),
        dict(span=12, kinds=16, before=kernel(3, 3, 0, flags=True, status=80), after=kernel(3, 3, 0, flags=True, status=80)),
        dict(span=13, kinds=2, before=kernel(3, 3, 0, flags=True, status=80), after=kernel(3, 3, 0, read=0, flags=True, status=16)),
    ]
    values = [0] * 42
    values[:14] = [markers['handler1'], 2, 0, 0, 252, 5, 3, tick, 1, 0, 4, 3, 12, 12]
    values[15:23] = [2, 1, 65535, 1, 1, 1, 0, 1]
    values[23:26] = [16, 1, 0]
    values[36:] = [36, 2, 4096, 3, 2, 0xFFF8]
    row = dict(pc=source['pc'], mpr=source['mpr'], physical=source['physical'], bytes=source['data'],
               before=[2, 0, 0, 255, 1, 0, 0, 0, 0, 0, 100, 1, 0, 0],
               ticks=159, internal=48, wait_ticks=36, vector=0xFFF8, causes=7,
               clocks=spans,
               call_rows=[[1, 42, 0, 0, 0, 0, 1, 0, 0, 0],
                          [2, 60, 42, 0, 1, 14, 15, 36, 0, 7],
                          [3, 24, 6, 0, 15, 16, 17, 0, 0, 0],
                          [4, 33, 0, 1, 17, 17, 18, 0, 1, 0]],
               callbacks=[[2, spans[2][2], 7, 7, 0, 65534, 0, 1, 4],
                          [2, spans[2][2], 7, 8, 0, 65534, 0, 1, 12],
                          [2, spans[11][2], 2, 6, 0, 0, 0, 0, 0, 0, 0, 0],
                          [4, spans[-1][0], 1, 0xFFF8, markers['return_pc'], 4]],
               edges=edges, after=dict(values=values))
    return case, markers, row


class VdcAdpcmIrqReferenceTests(unittest.TestCase):
    def test_twenty_four_authored_recipes_have_three_natural_cuts(self):
        matrix = cases()
        self.assertEqual(len(matrix), 24)
        self.assertEqual(len({case['id'] for case in matrix}), 24)
        self.assertEqual({(c['divisor'], c['vce'], c['access'], c['policy']) for c in matrix},
                         set(itertools.product((3, 12), (4, 3, 2), ('high', 'tai'), ('retain', 'mask'))))
        for case in matrix:
            rom, markers, plan = program(case)
            self.assertEqual(len(rom), 262144)
            self.assertLess(markers['pre_dma'], markers['target'])
            self.assertLess(markers['target'], markers['return_pc'])
            self.assertLess(markers['return_pc'], markers['done'])
            self.assertLess(markers['handler1'], markers['post_ack'])
            self.assertLess(markers['post_ack'], markers['handler2'])
            target = next(row for row in plan if row['pc'] == markers['target'])
            self.assertEqual(target['mpr'], list(MPR))
            self.assertEqual(target['data'], [0xAD, 3, 0] if case['access'] == 'high'
                             else [0xF3, 2, 0, 0, 0x22, 2, 0])
            launch = next(row for row in plan if row['pc'] == markers['pre_dma'])
            self.assertEqual(launch['data'], [0x8D, 3, 0])
            self.assertTrue(all(bytes(rom[p] for p in row['physical']) == bytes(row['data']) for row in plan))

    def test_independent_vram_adpcm_and_handler_result_literals(self):
        vram = expected_vram()
        self.assertEqual(len(vram), 32768)
        self.assertEqual(WORDS, 4096)
        self.assertEqual({i: value for i, value in enumerate(vram) if value},
                         {0: 0xA65C, 4095: 0x5AA5, 8192: 0xA65C, 12287: 0x5AA5})
        ram = expected_ram()
        self.assertEqual(len(ram), 65536)
        self.assertEqual(ram[65534:], [0x53, 0x64])
        self.assertEqual(ram[:2046], [(i * 17 + (i >> 8) * 7 + 0x53) & 255 for i in range(2, 2048)])
        self.assertEqual(ram[2046:65534], [0] * (65534 - 2046))
        for case in cases():
            wram = expected_wram(case)
            markers = program(case)[1]
            value = 0xA6 if case['access'] == 'high' else 2
            flags = 0x81 if case['access'] == 'high' else 1
            ret = markers['return_pc'] + int(case['policy'] == 'retain')
            self.assertEqual(len(wram), 8192)
            self.assertEqual(wram[17:23], [1, int(case['policy'] == 'retain'), 0, 16, value, 12])
            self.assertEqual(wram[508:512], [value, flags, ret & 255, ret >> 8])
            self.assertEqual(wram[512:514], [0x5C, 0xA6] if case['access'] == 'tai' else [0, 0])

    def test_every_mpr_physical_operand_and_hit_type_identifies_source(self):
        case = cases()[0]
        row = dict(program(case)[2][0], hits=1)
        reference.validate_hits([row], case)
        for page in range(8):
            bad = copy.deepcopy(row)
            bad['mpr'][page] ^= 1
            with self.subTest(page=page), self.assertRaises(ValueError):
                reference.validate_hits([bad], case)
        for field in ('pc', 'physical', 'data', 'hits'):
            bad = copy.deepcopy(row)
            if field in ('physical', 'data'):
                bad[field][0] ^= 1
            elif field == 'hits':
                bad[field] = True
            else:
                bad[field] ^= 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                reference.validate_hits([bad], case)
        with self.assertRaises(ValueError):
            reference.validate_hits([row, row], case)

    def test_variable_length_original_block_calls_are_not_retirements(self):
        case = next(c for c in cases() if c['access'] == 'tai')
        plan = program(case)[2]
        rows = []
        for length, count in ((100, 2), (1023, 1), (2, 1)):
            source = next(row for row in plan if row['data'][0] in (0x73, 0xF3)
                          and int.from_bytes(bytes(row['data'][5:]), 'little') == length)
            rows.append(dict(source, hits=count))
        hits = reference.validate_hits(rows, case)
        # Four completed blocks transfer 1225 bytes; original calls are N+2
        # for each operand length, hence 1225 + 2*4, not a fixed-N shortcut.
        original = work(instructions=4, calls=1233, clock_calls=1233,
                        clock_ticks=10000, blocks=4, block_bytes=1225)
        reference.validate_work(original, hits, 10000, True)
        reference.validate_work(dict(original, calls=4, clock_calls=0), hits, 10000, False)
        for mutate in ('calls', 'instructions', 'blocks', 'block_bytes', 'clock_ticks', 'bool'):
            bad = dict(original)
            if mutate == 'bool':
                bad['calls'] = True
            else:
                bad[mutate] += 1
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                reference.validate_work(bad, hits, 10000, True)

    def test_source_edge_and_irq_work_cannot_move_between_checkpoint_phases(self):
        target = dict(causes=7, vector=0xFFF8, bytes=[0xAD, 3, 0])
        second = dict(causes=0, vector=0xFFF6, bytes=[0xEA])
        rti = dict(causes=0, vector=0, bytes=[0x40])
        prefix = work(adpcm_cause_groups=1, vdc_cause_groups=1, irqs=1)
        suffix = work(irqs=1, rtis=2)
        reference.validate_phase_journal(prefix, [target])
        reference.validate_phase_journal(suffix, [rti, second, rti])
        for field in ('adpcm_cause_groups', 'vdc_cause_groups', 'irqs'):
            bad_prefix = dict(prefix)
            bad_suffix = dict(suffix)
            bad_prefix[field] -= 1
            bad_suffix[field] += 1
            self.assertEqual(prefix[field] + suffix[field], bad_prefix[field] + bad_suffix[field])
            with self.subTest(field=field), self.assertRaises(ValueError):
                reference.validate_phase_journal(bad_prefix, [target])
            with self.subTest(field=field), self.assertRaises(ValueError):
                reference.validate_phase_journal(bad_suffix, [rti, second, rti])

    def test_actual_capture_requires_source_and_execution_tier_joins(self):
        case = cases()[0]
        source = copy.deepcopy(program(case)[2][0])
        actual = dict(tier='native', window_hits=[dict(source, hits=1)])
        capture = dict(schema=1, runtime_abi=reference.ABI, capacity=1,
                       dropped_instructions=0, unreadable_instructions=0,
                       retired_instructions=1, complete=True,
                       observations=[dict(source, native_hits=1, interpreted_hits=0)])
        reference.validate_capture(capture, actual, case)
        for mutate in ('mpr', 'tier', 'retirements', 'dropped', 'duplicate'):
            bad = copy.deepcopy(capture)
            if mutate == 'mpr':
                bad['observations'][0]['mpr'][7] ^= 1
            elif mutate == 'tier':
                bad['observations'][0].update(native_hits=0, interpreted_hits=1)
            elif mutate == 'retirements':
                bad['retired_instructions'] += 1
            elif mutate == 'dropped':
                bad['dropped_instructions'] = 1
            else:
                bad['observations'].append(copy.deepcopy(bad['observations'][0]))
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                reference.validate_capture(bad, actual, case)

    def test_original_clock_group_keeps_tai_cause_in_incomplete_byte(self):
        case, markers, row = clock_group()
        reference.validate_clock_group(row, case, markers)
        for mutate in ('missing-call', 'early-complete', 'early-irq', 'fixed-clock', 'lost-wait'):
            bad = copy.deepcopy(row)
            if mutate == 'missing-call':
                bad['call_rows'].pop(1)
            elif mutate == 'early-complete':
                bad['call_rows'][1][3] = 1
            elif mutate == 'early-irq':
                bad['call_rows'][1][8] = 1
                bad['call_rows'][-1][8] = 0
                bad['callbacks'][-1][0] = 2
            elif mutate == 'fixed-clock':
                bad['call_rows'][1][1] += 3
            else:
                bad['clocks'][2][3] = 0
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                reference.validate_clock_group(bad, case, markers)

    def test_actual_source_callbacks_must_precede_grant_in_dynamic_spans(self):
        case, markers, row = clock_group()
        reference.validate_clock_group(row, case, markers)
        for mutate in ('outside-wait', 'after-grant', 'wrong-call', 'missing-end',
                       'unknown-callback', 'missing-grant', 'pending-not-three',
                       'missing-kernel-source-transition'):
            bad = copy.deepcopy(row)
            if mutate == 'outside-wait':
                bad['callbacks'][0][1] = bad['clocks'][1][2]
            elif mutate == 'after-grant':
                bad['callbacks'][2][1] = bad['clocks'][14][2]
            elif mutate == 'wrong-call':
                bad['callbacks'][0][0] = 3
            elif mutate == 'missing-end':
                bad['callbacks'].pop(1)
            elif mutate == 'unknown-callback':
                bad['callbacks'].append([2, bad['clocks'][3][2], 99, 0, 0, 0])
            elif mutate == 'missing-grant':
                bad['edges'].pop()
            elif mutate == 'pending-not-three':
                bad['edges'][-1]['before'][2] = 1
            else:
                bad['edges'][0]['kinds'] = 1
                bad['edges'][0]['after'][14:16] = [0, 0]
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                reference.validate_clock_group(bad, case, markers)

    def test_real_provider_witness_requires_source_absent_inside_target_wait(self):
        case, markers, target = clock_group()
        # Provider admission uses a separate native bounded witness, without
        # pretending to expose exact native HALF/END callback timestamps.
        target['ticks'] = 500
        target['wait_ticks'] = 377
        target['after']['values'][7] = 1500
        target['after']['values'][36] = 377
        values = [0] * 42
        values[7] = 900
        actual = dict(cut_id=0, cut=dict(values=values),
                      prefix_work=work(), window_work=work(instructions=1),
                      prefix_journal=[], journal=[target])
        witness = {key: copy.deepcopy(target[key]) for key in ('pc', 'mpr', 'physical', 'bytes')}
        witness['values'] = [1075, 27, 100, 1, 1, 0, 0, 0, 0]
        reference.validate_provider_witnesses([witness], actual, case)
        for index, value in ((1, 0), (2, 40), (3, 0), (4, 5),
                             (5, 1), (6, 1), (7, 1), (8, 1)):
            bad = copy.deepcopy(witness)
            bad['values'][index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                reference.validate_provider_witnesses([bad], actual, case)
        for mutate in ('mpr', 'outside-target', 'duplicate'):
            bad = copy.deepcopy(witness)
            if mutate == 'mpr':
                bad['mpr'][4] ^= 1
            elif mutate == 'outside-target':
                bad['pc'] = markers['return_pc']
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                reference.validate_provider_witnesses([bad, bad] if mutate == 'duplicate' else [bad], actual, case)

    def test_actual_full_source_ledger_excludes_compiled_terminal_and_masked_handler(self):
        for case in cases():
            _, markers, plan = program(case)
            warmup = next(row['pc'] for row in plan if row['data'][0] == 0x73
                          and int.from_bytes(bytes(row['data'][5:]), 'little') == 1023)
            rows = []
            for source in plan:
                pc = source['pc']
                if pc == markers['done'] or (case['policy'] == 'mask' and pc >= markers['handler2']):
                    continue
                rows.append(dict(source, hits=case['loops'] if pc in (warmup, warmup + 7, warmup + 8) else 1))
            qualification.full_hits(rows, [], case)
            bad = copy.deepcopy(rows)
            next(row for row in bad if row['pc'] == warmup)['hits'] -= 1
            with self.subTest(case=case['id']), self.assertRaises(ValueError):
                qualification.full_hits(bad, [], case)
            terminal = next(source for source in plan if source['pc'] == markers['done'])
            with self.assertRaises(ValueError):
                qualification.full_hits(rows + [dict(terminal, hits=1)], [], case)

    def test_restored_capture_preserves_imported_origin_without_new_work(self):
        case = cases()[0]
        source = copy.deepcopy(program(case)[2][0])
        values = [0] * 42
        values[7] = 12345
        actual = dict(tier='interpreter', window_hits=[dict(source, hits=1)],
                      checkpoint_sha256='a' * 64, cut=dict(values=values),
                      origin_frame=9, prefix_native=0, prefix_interpreted=123)
        origin = dict(sha256='a' * 64, ticks=12345, frame=9,
                      native_steps=0, interpreter_steps=123)
        capture = dict(schema=1, runtime_abi=reference.ABI, capacity=1,
                       dropped_instructions=0, unreadable_instructions=0,
                       retired_instructions=1, complete=True, checkpoint_origin=origin,
                       observations=[dict(source, native_hits=0, interpreted_hits=1)])
        reference.validate_capture(capture, actual, case, resume=True)
        self.assertEqual(capture['retired_instructions'], 1)
        self.assertEqual(capture['checkpoint_origin']['interpreter_steps'], 123)
        for field in ('ticks', 'frame', 'native_steps', 'interpreter_steps'):
            bad = copy.deepcopy(capture)
            bad['checkpoint_origin'][field] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                reference.validate_capture(bad, actual, case, resume=True)

    def test_requested_tier_and_actual_guest_stderr_are_required(self):
        reference.requested_tier(dict(tier='native'), 'native')
        with self.assertRaises(ValueError):
            reference.requested_tier(dict(tier='interpreter'), 'native')
        qualification.validate_stderr('tool-configure', 'CMake warning')
        with self.assertRaises(ValueError):
            qualification.validate_stderr('high-retain-div3-vce4-cut0-gear', 'unexpected guest diagnostic')

    def test_duplicate_and_nonfinite_receipts_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'receipt.json'
            for value in ('{"x":1,"x":2}', '{"x":Infinity}', '{"x":NaN}',
                          '{"x":1e1000}', '{"x":1.5}'):
                path.write_text(value)
                with self.subTest(value=value), self.assertRaises(ValueError):
                    qualification.load(path)


if __name__ == '__main__':
    unittest.main()
