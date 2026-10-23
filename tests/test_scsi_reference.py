from pathlib import Path
import tempfile
import unittest

from generate_scsi_fixture import make_fixture
from scripts.cd_reference import prepare_media
from scripts.scsi_reference import PHASES, cd_state, plans, toc_plans, validate_toc


class ScsiReferenceTests(unittest.TestCase):
    def test_directed_handshake_plan_is_bounded_and_authored(self):
        snapshot, cases = make_fixture()
        sites = {pc: (op, address) for pc, op, address in cases}
        sequences = plans()
        self.assertEqual(len(sequences), 21)
        self.assertEqual(len({p['id'] for p in sequences}), 21)
        self.assertEqual(sum(len(p['steps']) for p in sequences), 743)
        self.assertEqual(sum(s[2] for p in sequences for s in p['steps']), 1007108)
        used = set()
        for plan in sequences:
            self.assertLessEqual(len(plan['steps']), 256)
            self.assertLessEqual(sum(s[2] for s in plan['steps']), 1_000_000)
            for pc, value, nops in plan['steps']:
                self.assertIn(pc, sites)
                self.assertIn(value, range(-1, 256))
                self.assertIn(nops, range(100001))
                used.add(sites[pc])
        self.assertTrue({(0x8D, 0x1800), (0x8D, 0xB800), (0x8D, 0x1801),
                         (0x8D, 0xB801), (0xAD, 0x1808), (0xAD, 0xB808), (0xEA, 0)} <= used)
        self.assertEqual(snapshot.mpr[0], snapshot.mpr[5])
        self.assertEqual([len(sequences[i::3]) for i in range(3)], [7, 7, 7])

    def test_unknown_reference_phase_is_rejected(self):
        status = {'bram_enabled': True, 'scsi_ack': False, 'enabled_irqs': '00',
                  'active_irqs': '00', 'reset': 0, 'scsi_phase': 'UNKNOWN'}
        with self.assertRaises(KeyError):
            cd_state(status, {'IRQ2_asserted': False})

    def test_reference_phase_and_signal_schema_is_explicit(self):
        self.assertEqual(PHASES, {'BUS FREE': 0, 'COMMAND': 3, 'DATA IN': 4,
                                 'STATUS': 7, 'MESSAGE IN': 6, 'BUSY': 8})
        status = {'bram_enabled': False, 'scsi_ack': True, 'enabled_irqs': '20',
                  'active_irqs': '20', 'reset': 0, 'scsi_phase': 'STATUS',
                  'scsi_bsy': True, 'scsi_req': False, 'scsi_msg': False,
                  'scsi_cd': True, 'scsi_io': True, 'scsi_data_bus': '02'}
        self.assertEqual(cd_state(status, {'IRQ2_asserted': True}),
                         {'bram_unlocked': False, 'ack': True, 'irq_enable': 32,
                          'irq_active': 32, 'reset': 0, 'irq2': True, 'phase': 7,
                          'bsy': True, 'req': False, 'msg': False, 'cd': True,
                          'io': True, 'data': 2})

    def test_toc_sequences_cover_modes_tracks_and_transfer_paths(self):
        _, cases = make_fixture()
        sites = {pc: (op, address) for pc, op, address in cases}
        sequences = toc_plans()
        self.assertEqual(len(sequences), 26)
        self.assertEqual(len({p['id'] for p in sequences}), 26)
        self.assertEqual(sum(len(p['steps']) for p in sequences), 2014)
        self.assertEqual(sum(s[2] for p in sequences for s in p['steps']), 670460)
        for plan in sequences:
            self.assertLessEqual(len(plan['steps']), 256)
            self.assertLessEqual(sum(s[2] for s in plan['steps']), 1_000_000)
            for pc, value, nops in plan['steps']:
                self.assertIn(pc, sites)
                self.assertIn(value, range(-1, 256))
                self.assertIn(nops, range(100001))
        for mode, track in [(0, 0), (1, 0)] + [(2, t) for t in (0, 1, 2, 9, 0x10, 0x12, 0x13, 0x99, 0xAA)]:
            for suffix in ('manual', 'auto'):
                self.assertIn(f'toc-mode-{mode}-track-{track:02x}-{suffix}', {p['id'] for p in sequences})
        self.assertEqual([len(sequences[i::7]) for i in range(7)], [4, 4, 4, 4, 4, 3, 3])

    def test_authored_mixed_toc_is_bounded_reused_and_matches_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            cue, bios = prepare_media(out, b'\x80\xfe', profile='toc')
            self.assertEqual(bios.stat().st_size, 262144)
            self.assertEqual((out/'synthetic-disc.bin').stat().st_size, 2352 * 1032)
            self.assertEqual(cue.read_text().count('TRACK '), 12)
            self.assertEqual(cue.read_text().count('AUDIO'), 10)
            self.assertIn('TRACK 10 AUDIO\n    INDEX 01 00:10:24', cue.read_text())
            self.assertEqual(prepare_media(out, b'\x80\xfe', profile='toc'), (cue, bios))
            with self.assertRaises(ValueError):
                prepare_media(out, b'\x80\xfe')
            with self.assertRaises(ValueError):
                prepare_media(out, b'', profile='unknown')
        result = {'track_count': 12, 'sector_count': 1032, 'total_length_msf': '00:15:57',
                  'data_track_count': 2, 'audio_track_count': 10,
                  'tracks': [{'number': i + 1, 'start_lba': i * 86, 'sector_count': 86,
                              'is_audio': i not in (0, 11)} for i in range(12)]}
        self.assertEqual(validate_toc(result)['tracks'][9], {'index1_lba': 774, 'type': 0})
        result['tracks'][9]['start_lba'] += 1
        with self.assertRaises(RuntimeError):
            validate_toc(result)


if __name__ == '__main__':
    unittest.main()
