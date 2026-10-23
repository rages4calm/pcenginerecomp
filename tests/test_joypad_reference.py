from pathlib import Path
import tempfile
import unittest

from generate_joypad_fixture import make_fixture
from scripts.joypad_reference import BUTTONS, plans, write_plan


class JoypadReferenceTests(unittest.TestCase):
    def test_authored_sequences_are_bounded_and_disjoint(self):
        snapshot, cases = make_fixture()
        sites = {pc: (op, address) for pc, op, address in cases}
        sequences = plans()
        self.assertEqual(len(sequences), 28)
        self.assertEqual(len({plan['id'] for plan in sequences}), 28)
        self.assertEqual(sum(len(plan['steps']) for plan in sequences), 1256)
        self.assertEqual([len(sequences[i::8]) for i in range(8)], [4, 4, 4, 4, 3, 3, 3, 3])
        self.assertEqual(snapshot.mpr[0], snapshot.mpr[5])
        for plan in sequences:
            self.assertLessEqual(len(plan['steps']), 256)
            self.assertEqual(len(plan['types']), 5)
            self.assertEqual(len(plan['pressed']), 5)
            self.assertTrue(set(plan['types']) <= {2, 6})
            self.assertTrue(all(0 <= mask <= 4095 for mask in plan['pressed']))
            for pc, value in plan['steps']:
                self.assertIn(pc, sites)
                self.assertIn(value, range(-1, 256))

    def test_plans_cover_every_button_output_byte_and_port_alias(self):
        _, cases = make_fixture()
        sites = {pc: (op, address) for pc, op, address in cases}
        sequences = plans()
        self.assertEqual(BUTTONS, ('I', 'II', 'select', 'run', 'up', 'right', 'down', 'left', 'III', 'IV', 'V', 'VI'))
        self.assertTrue({'button-' + button for button in BUTTONS} <= {p['id'] for p in sequences})
        output = [p for p in sequences if p['id'].startswith('output-bytes-')]
        self.assertEqual({value for p in output for pc, value in p['steps'] if sites[pc][0] == 0x8D}, set(range(256)))
        self.assertEqual({sites[pc][1] for p in output for pc, _ in p['steps']},
                         {0x1000, 0x1001, 0x107F, 0x1100, 0x13FF, 0xB000, 0xB001, 0xB07F, 0xB100, 0xB3FF})
        self.assertEqual({p['tap'] for p in sequences if p['id'].startswith('mixed-five')}, {False, True})
        self.assertTrue({(0x0C, 0x1000), (0x1C, 0x1000), (0x0C, 0xB3FF), (0x1C, 0xB3FF)} <=
                        {sites[pc] for p in sequences for pc, _ in p['steps']})

    def test_probe_plan_keeps_explicit_configuration_and_input(self):
        plan = plans()[11]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sequence.txt'
            write_plan(path, plan, True, False)
            lines = path.read_text().splitlines()
        header = list(map(int, lines[0].split()))
        self.assertEqual(header[:6], [plan[k] for k in ('seed', 'a', 'x', 'y', 'sp', 'p')])
        self.assertEqual(header[6:9], [1, 0, 0])
        self.assertEqual(header[9:14], plan['types'])
        self.assertEqual(header[14:19], plan['pressed'])
        self.assertEqual(header[19], len(plan['steps']))
        self.assertEqual([tuple(map(int, row.split())) for row in lines[1:]], plan['steps'])


if __name__ == '__main__':
    unittest.main()
