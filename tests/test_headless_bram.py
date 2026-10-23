"""Explicit, read-only initial BRAM attachment using entirely authored inputs."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.dev_client import DevClient

ROOT = Path(__file__).resolve().parent.parent
NAME = 'pce-headless.exe' if os.name == 'nt' else 'pce-headless'
BINARY = Path(os.environ.get('PCE_TEST_HEADLESS', ROOT/'build'/NAME))
MPRS = '255,248,128,247,130,131,132,0'


@unittest.skipUnless(BINARY.is_file(), 'Build pce-headless for initial BRAM checks')
class InitialBramTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.image = self.root/'program.bin'
        self.bram = self.root/'authored initial.bram'
        self.pattern = bytes((i*37 + 61) & 255 for i in range(2048))
        self.bram.write_bytes(self.pattern)

    def command(self, options, steps=1, ticks=10000, load='0x100000'):
        return [str(BINARY), str(self.image), load, '0x4000', MPRS,
                str(steps), str(ticks), 'hybrid', *options]

    def invoke(self, program=b'\xEA', options=None, **kwargs):
        self.image.write_bytes(program)
        before = self.bram.read_bytes() if self.bram.is_file() else None
        result = subprocess.run(self.command(
            ['--bram', str(self.bram)] if options is None else options, **kwargs),
            capture_output=True, text=True, timeout=5)
        self.assertEqual(self.image.read_bytes(), program)
        if before is not None:
            self.assertEqual(self.bram.read_bytes(), before)
        return result

    def state(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_exact_zero_and_patterned_images_read_first_last_and_upper_holes(self):
        for raw in (bytes(2048), self.pattern):
            self.bram.write_bytes(raw)
            for hole in (0x6800, 0x7FFF):
                with self.subTest(zero=not any(raw), hole=hole):
                    # LDA first; TAY; LDA last; TAX; LDA upper hole.
                    program = bytes([0xAD, 0, 0x60, 0xA8, 0xAD, 0xFF, 0x67,
                                     0xAA, 0xAD, hole & 255, hole >> 8])
                    state = self.state(self.invoke(program, steps=5))
                    self.assertEqual((state['y'], state['x'], state['a']),
                                     (raw[0], raw[-1], 255))
                    self.assertTrue(state['cd_control']['bram_seeded'])
                    self.assertTrue(state['cd_control']['enabled'])
                    self.assertFalse(state['scsi']['enabled'])
                    self.assertTrue(state['joypad']['cd'])

    def test_initial_copy_covers_middle_and_last_byte(self):
        program = bytes([0xAD, 0, 0x60, 0xA8, 0xAD, 0xA5, 0x64,
                         0xAA, 0xAD, 0xFF, 0x67])
        state = self.state(self.invoke(program, steps=5))
        self.assertEqual((state['y'], state['x'], state['a']),
                         (self.pattern[0], self.pattern[0x4A5], self.pattern[-1]))

    def test_guest_writes_are_volatile_and_never_change_initial_file(self):
        program = bytes([0xA9, 0x6C, 0x8D, 0, 0x60,
                         0xA9, 0xB2, 0x8D, 0xFF, 0x67,
                         0xAD, 0, 0x60, 0xA8, 0xAD, 0xFF, 0x67, 0xAA,
                         0xAD, 0, 0x68])
        state = self.state(self.invoke(program, steps=9))
        self.assertEqual((state['y'], state['x'], state['a']), (0x6C, 0xB2, 255))
        self.assertEqual(self.bram.read_bytes(), self.pattern)
        reread = self.state(self.invoke(bytes([0xAD, 0, 0x60])))
        self.assertEqual(reread['a'], self.pattern[0])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ['authored initial.bram', 'program.bin'])

    def test_upper_hole_writes_remain_ignored(self):
        state = self.state(self.invoke(bytes([0xA9, 0x2B, 0x8D, 0, 0x68,
                                              0xAD, 0, 0x68]), steps=3))
        self.assertEqual(state['a'], 255)
        self.assertEqual(state['cd_control']['bram_changes'], 1)  # Initial copy only.

    def test_no_option_preserves_original_default_and_bios_zero_bram(self):
        state = self.state(self.invoke(options=[]))
        self.assertFalse(state['cd_control']['enabled'])
        self.assertFalse(state['cd_control']['bram_seeded'])
        firmware = self.root/'synthetic.pce'
        firmware.write_bytes(bytes(262144))
        state = self.state(self.invoke(bytes([0xAD, 0, 0x60]),
                                       options=['--bios', str(firmware)]))
        self.assertEqual(state['a'], 0)
        self.assertTrue(state['cd_control']['enabled'])
        self.assertFalse(state['cd_control']['bram_seeded'])

    def test_bios_order_preserves_transport_video_audio_and_seed(self):
        firmware = self.root/'synthetic.pce'
        raw = bytes(262144)
        firmware.write_bytes(raw)
        for order in (['--bram', str(self.bram), '--bios', str(firmware)],
                      ['--bios', str(firmware), '--bram', str(self.bram)]):
            with self.subTest(order=order):
                state = self.state(self.invoke(bytes([0xAD, 0, 0x60]), options=order))
                self.assertEqual(state['a'], self.pattern[0])
                self.assertTrue(state['cd_control']['bram_seeded'])
                self.assertTrue(state['scsi']['enabled'])
                self.assertTrue(state['vdc']['enabled'])
                self.assertTrue(state['raster']['enabled'])
                self.assertTrue(state['adpcm']['enabled'])
                self.assertTrue(state['cd_audio']['enabled'])
                self.assertEqual(firmware.read_bytes(), raw)

    def test_rejects_inexact_sizes_missing_file_directory_duplicate_and_missing_value(self):
        for size in (0, 1, 2047, 2049, 8192):
            with self.subTest(size=size):
                self.bram.write_bytes(bytes(size))
                result = self.invoke()
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
                self.assertIn('exactly 2048', result.stderr)
        self.bram.write_bytes(self.pattern)
        for options in (['--bram', str(self.root/'absent.bram')],
                        ['--bram', str(self.root)], ['--bram'],
                        ['--bram', str(self.bram), '--bram', str(self.bram)]):
            with self.subTest(options=options):
                result = self.invoke(options=options)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
                self.assertTrue(result.stderr)

    def test_bram_attachment_does_not_allow_payload_in_protected_bank(self):
        result = self.invoke(load='0x1EE000')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertIn('standard CD RAM or work RAM', result.stderr)

    def test_tcp_reports_only_seed_presence_and_keeps_guest_paused(self):
        self.image.write_bytes(bytes([0x80, 0xFE]))
        command = self.command(['--bram', str(self.bram), '--dev-port', '0',
                                '--dev-start-paused', 'on', '--wall-seconds', '5'])
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            line = process.stderr.readline()
            self.assertTrue(line.startswith('PCE_DEV_PORT='), line)
            with DevClient(int(line.strip().split('=')[1]), timeout=3) as client:
                first = client.call('status')
                self.assertEqual((first['ticks'], first['paused']), (0, True))
                self.assertTrue(first['host']['cd_control']['bram_seeded'])
                self.assertTrue(first['host']['cd_control']['enabled'])
                self.assertFalse(first['host']['scsi']['enabled'])
                self.assertEqual(first['host'], client.call('status')['host'])
                self.assertNotIn(str(self.bram), json.dumps(first))
                client.call('quit')
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertTrue(json.loads(stdout)['cd_control']['bram_seeded'])
            self.assertEqual(self.bram.read_bytes(), self.pattern)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    def test_twenty_billion_step_cap_obeys_tiny_tick_deadline_and_rejects_bad_limits(self):
        for steps in (2000000001, 20000000000):
            with self.subTest(steps=steps):
                state = self.state(self.invoke(bytes([0x80, 0xFE]),
                                               options=[], steps=steps, ticks=1))
                self.assertEqual(state['stop'], 'budget')
                self.assertEqual(state['native_steps'] + state['interpreter_steps'], 1)
        for steps in (0, -1, 20000000001, 18446744073709551616):
            with self.subTest(steps=steps):
                result = self.invoke(bytes([0x80, 0xFE]), options=[], steps=steps, ticks=1)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
