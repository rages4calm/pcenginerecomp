"""Authored fixture and counterexample checks for HuCard reference receipts."""
import copy
import unittest

from pcerecomp.project import ABI
from hucard_fixture import (BANK_COUNTS, CPU_FIELDS, DEVICE_FIELDS, authored_program,
                            authored_rom, backing_bank, plans, serialize)
from scripts.hucard_reference import (compare, compose_captures, validate_capture,
                                      validate_execution, validate_records)


class HuCardReferenceTests(unittest.TestCase):
    def test_authored_special_maps_and_non_power_of_two_are_distinct(self):
        self.assertEqual([backing_bank(48, b) for b in (0, 31, 32, 63, 64, 79, 80, 127)],
                         [0, 31, 0, 31, 32, 47, 32, 47])
        self.assertEqual([backing_bank(64, b) for b in (0, 32, 63, 64, 95, 96, 127)],
                         [0, 32, 63, 32, 63, 32, 63])
        self.assertEqual([backing_bank(96, b) for b in (0, 63, 64, 95, 96, 127)],
                         [0, 63, 64, 95, 64, 95])
        self.assertEqual([backing_bank(3, b) for b in range(8)], [0, 1, 2, 0, 1, 2, 0, 1])
        for count, bank in ((0, 0), (129, 0), (1, 128), (1, -1)):
            with self.assertRaises(ValueError):
                backing_bank(count, bank)

    def test_actual_authored_fetch_program_fits_each_bank_and_avoids_csh(self):
        from pcerecomp.isa import decode
        for count in BANK_COUNTS:
            rom = authored_rom(count)
            self.assertEqual(len(rom), count*8192)
            self.assertEqual(rom[8190:8192], b'\0\xe1')
            for bank in range(count):
                self.assertEqual(rom[bank*8192+256:bank*8192+256+len(authored_program())], authored_program())
        code = authored_program()
        pc, instructions = 0, []
        while pc < len(code):
            ins = decode(lambda address: code[address], pc, (0,)*8)
            instructions.append(ins)
            pc += len(ins.data)
        self.assertNotIn(0xD4, [ins.data[0] for ins in instructions])
        self.assertNotIn(0x54, [ins.data[0] for ins in instructions])
        self.assertIn((0x53, 0x80), [ins.data for ins in instructions])
        self.assertEqual(instructions[-1].data, (0x80, 0xFE))

    def test_finite_plan_accounting_and_non_wrapping_geometry(self):
        cases = plans(48)
        text, spans = serialize(cases)
        self.assertEqual(len(cases), 7)
        self.assertEqual(sum(op[1] for c in cases for op in c['operations'] if op[0] == 'i'), 384)
        self.assertEqual(sum(row['records'] for row in spans), spans[-1]['start']+spans[-1]['records'])
        self.assertTrue(text.endswith('\n'))
        self.assertEqual(text.count('\nr ')+int(text.startswith('r ')), 7)
        self.assertTrue(all(0 <= op[1] <= 255 and 0 <= op[2] <= 8191
                            for c in cases for op in c['operations'] if op[0] in ('q', 'p', 'w')))

    def test_record_shape_and_raw_mismatch_are_strict(self):
        cases = [dict(id='shape', operations=[('s',), ('d',), ('q', 0, 0), ('i', 1)])]
        rows = [dict(kind='cpu', values=[0]*len(CPU_FIELDS)),
                dict(kind='devices', values=[0]*len(DEVICE_FIELDS)),
                dict(kind='memory', values=[0, 0, 29]), dict(kind='cpu', values=[0]*len(CPU_FIELDS))]
        self.assertIs(validate_records(rows, cases), rows)
        self.assertIsNone(compare(rows, copy.deepcopy(rows), cases))
        changed = copy.deepcopy(rows)
        changed[-1]['values'][7] = 18
        self.assertEqual(compare(changed, rows, cases)['field'], 'ticks')
        for change in ('bool', 'width', 'tag', 'extra', 'negative'):
            bad = copy.deepcopy(rows)
            if change == 'bool': bad[0]['values'][0] = False
            if change == 'width': bad[1]['values'].pop()
            if change == 'tag': bad[2]['kind'] = 'peek'
            if change == 'extra': bad[0]['projected'] = True
            if change == 'negative': bad[0]['values'][0] = -1
            with self.assertRaises(ValueError):
                validate_records(bad, cases)

    def execution(self, native=False):
        return dict(runtime_abi=ABI, native_only=native, interpreter_fallback=False, cases=2,
                    native_steps=2 if native else 0, interpreter_steps=0 if native else 2,
                    guard_checks=6 if native else 0, restored_source_mutations=2 if native else 0,
                    per_case=[[0, 0], [2, 0] if native else [0, 2]])

    def capture(self, native=False):
        return dict(schema=1, runtime_abi=ABI, capacity=16, complete=True,
                    dropped_instructions=0, unreadable_instructions=0, retired_instructions=2,
                    observations=[dict(pc=0xE100, mpr=[0]*8, physical=[0x100, 0x101],
                                       data=[0xA9, 7], native_hits=2 if native else 0,
                                       interpreted_hits=0 if native else 2)])

    def test_execution_report_does_not_accept_bool_counts_or_tier_relabel(self):
        cases = [dict(operations=[('r', 0, 0, 0, 0)]), dict(operations=[('i', 2)])]
        for native in (False, True):
            expected = self.execution(native)
            self.assertEqual(validate_execution(expected, cases, native), expected)
            for field, value in (('runtime_abi', ABI-1), ('cases', True), ('native_steps', 7),
                                 ('guard_checks', True), ('interpreter_fallback', True), ('native_only', int(native))):
                bad = copy.deepcopy(expected)
                bad[field] = value
                with self.assertRaises(ValueError):
                    validate_execution(bad, cases, native)

    def test_complete_capture_conserves_actual_hits(self):
        for native in (False, True):
            capture = self.capture(native)
            work = self.execution(native)
            self.assertEqual(validate_capture(capture, work, native), capture)
            bad = copy.deepcopy(capture)
            bad['observations'][0]['native_hits'] = 1
            bad['observations'][0]['interpreted_hits'] = 1
            with self.assertRaises(ValueError):
                validate_capture(bad, work, native)

    def test_profile_union_preserves_original_identities_and_hits(self):
        first, second = self.capture(), self.capture()
        union = compose_captures([first, second])
        self.assertEqual(union['retired_instructions'], 4)
        self.assertEqual(union['observations'][0]['interpreted_hits'], 4)
        second['observations'][0]['mpr'][7] = 64
        second['observations'][0]['physical'] = [0x80100, 0x80101]
        union = compose_captures([first, second])
        self.assertEqual(len(union['observations']), 2)
        second['runtime_abi'] = 17 if ABI != 17 else 16
        with self.assertRaises(ValueError):
            compose_captures([first, second])
        incomplete = self.capture()
        incomplete.update(complete=False, dropped_instructions=1, retired_instructions=3)
        with self.assertRaises(ValueError):
            compose_captures([first, incomplete])


if __name__ == '__main__':
    unittest.main()
