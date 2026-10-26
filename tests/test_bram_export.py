"""Opt-in raw BRAM snapshots through real hosts; every guest byte is authored."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.dev_client import DevClient

ROOT = Path(__file__).resolve().parent.parent
EXE = '.exe' if os.name == 'nt' else ''
HEADLESS = Path(os.environ.get('PCE_TEST_HEADLESS', ROOT/'build'/('pce-headless'+EXE)))
DESKTOP = Path(os.environ.get('PCE_TEST_DESKTOP', 'disabled'))
MPRS = '255,248,128,247,130,131,132,0'


class BramExportChecks:
    desktop = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.image = self.root/'authored program.bin'
        self.seed = self.root/'initial.bram'
        self.output = self.root/'final é.bram'
        self.pattern = bytes((index*37+61) & 255 for index in range(2048))
        self.seed.write_bytes(self.pattern)
        self.image.write_bytes(b'\xEA')
        self.environment = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software', SDL_AUDIODRIVER='dummy')

    def command(self, extra=(), steps=1, seed=True, tier='hybrid'):
        result = [str(self.binary), str(self.image), '0x100000', '0x4000', MPRS,
                  str(steps), '1000000000', tier, '--audio-output', 'off', '--video-output', 'continuous']
        if seed:
            result += ['--bram', str(self.seed)]
        if self.desktop:
            result += ['--hidden', 'on', '--unthrottled', 'on', '--window-scale', '1']
        return result + list(extra)

    def invoke(self, extra=(), **kwargs):
        return subprocess.run(self.command(extra, **kwargs), capture_output=True, text=True,
                              env=self.environment, timeout=5)

    def good(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_seed(self):
        self.assertEqual(self.seed.read_bytes(), self.pattern)
        self.assertFalse(any('.pce-bram-' in p.name for p in self.root.iterdir()))

    def test_locked_snapshot_is_exact_and_next_process_reloads_guest_writes(self):
        # Write both boundaries, lock through the status read, then observe FF.
        self.image.write_bytes(bytes.fromhex('A9 6C 8D 00 60 A9 B2 8D FF 67 AD 03 18 AD 00 60'))
        baseline = self.good(self.invoke(steps=6))
        state = self.good(self.invoke(['--bram-out', str(self.output)], steps=6))
        expected = bytearray(self.pattern)
        expected[0], expected[-1] = 0x6C, 0xB2
        self.assertEqual(self.output.read_bytes(), expected)
        self.assertEqual((state['a'], state['cd_control']['bram_unlocked']), (255, False))
        for key in ('pc', 'a', 'x', 'y', 'sp', 'p', 'ticks', 'cycles', 'mpr',
                    'native_steps', 'interpreter_steps', 'cd_control', 'scsi', 'raster'):
            self.assertEqual(state[key], baseline[key], key)
        self.assertNotIn(str(self.output), json.dumps(state))
        self.image.write_bytes(bytes.fromhex('AD 00 60 A8 AD FF 67'))
        second = self.root/'second.bram'
        self.seed = self.output
        reread = self.good(self.invoke(['--bram-out', str(second)], steps=3))
        self.assertEqual((reread['y'], reread['a']), (0x6C, 0xB2))
        self.assertEqual(second.read_bytes(), expected)
        self.assertEqual(self.output.read_bytes(), expected)
        self.assertFalse(any('.pce-bram-' in p.name for p in self.root.iterdir()))

    def test_default_is_volatile_and_explicit_export_does_not_attach_device(self):
        self.good(self.invoke())
        self.assertEqual({p.name for p in self.root.iterdir()}, {self.seed.name, self.image.name})
        result = self.invoke(['--bram-out', str(self.output)], seed=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn('already enabled', result.stderr)
        self.assertFalse(self.output.exists())
        self.assert_seed()

    def test_blank_bios_bram_exports_without_fabricated_format(self):
        firmware = self.root/'authored.pce'
        firmware.write_bytes(bytes(262144))
        self.good(self.invoke(['--bios', str(firmware), '--bram-out', str(self.output)], seed=False))
        self.assertEqual(self.output.read_bytes(), bytes(2048))
        self.assert_seed()

    def test_existing_files_directories_hardlinks_and_missing_parent_are_refused(self):
        existing = self.root/'existing.bram'
        existing.write_bytes(b'keep me')
        hardlink = self.root/'linked.bram'
        os.link(self.seed, hardlink)
        for output in (existing, self.root, self.seed, hardlink, self.image,
                       self.root/'absent'/'save.bram'):
            with self.subTest(output=output):
                result = self.invoke(['--bram-out', str(output)])
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertTrue(result.stderr)
                self.assertEqual(existing.read_bytes(), b'keep me')
                self.assert_seed()

    def test_new_output_aliases_are_refused_before_other_output_creation(self):
        for option in ('--frame-out', '--audio-out', '--code-capture'):
            with self.subTest(option=option):
                options = ['--bram-out', str(self.output), option, str(self.output)]
                if option == '--audio-out':
                    # Replace the command's explicit audio-off option.
                    command = self.command(options)
                    command[command.index('--audio-output')+1] = 'on'
                    result = subprocess.run(command, capture_output=True, text=True,
                                            env=self.environment, timeout=5)
                else:
                    result = self.invoke(options)
                self.assertEqual(result.returncode, 2)
                self.assertIn('aliases', result.stderr)
                self.assertFalse(self.output.exists())
        self.assert_seed()

    def test_dangling_and_input_symlinks_are_refused_without_following(self):
        dangling = self.root/'dangling.bram'
        linked = self.root/'linked.bram'
        try:
            dangling.symlink_to(self.root/'absent.bram')
            linked.symlink_to(self.seed)
        except OSError as error:
            self.skipTest(f'Symlink creation unavailable: {error}')
        for output in (dangling, linked):
            result = self.invoke(['--bram-out', str(output)])
            self.assertEqual(result.returncode, 2)
            self.assertTrue(output.is_symlink())
            self.assertFalse((self.root/'absent.bram').exists())
        self.assert_seed()

    def test_fault_and_native_miss_leave_no_export(self):
        self.image.write_bytes(bytes.fromhex('A9 5A 8D 00 60 0B'))  # An unassigned opcode.
        result = self.invoke(['--bram-out', str(self.output)], steps=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())
        self.image.write_bytes(b'\xEA')
        result = self.invoke(['--bram-out', str(self.output)], tier='native')
        self.assertEqual(result.returncode, 3)
        self.assertFalse(self.output.exists())
        # A disabled PSG write after retired BRAM work must not publish it.
        # Decoded CD holes now correctly accept ignored writes.
        self.image.write_bytes(bytes.fromhex('A9 5A 8D 00 60 8D 00 08'))
        result = self.invoke(['--bram-out', str(self.output)], steps=3)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout)['stop'], 'bus_fault')
        self.assertFalse(self.output.exists())
        self.assert_seed()

    def test_late_capture_finalization_failure_does_not_publish_export(self):
        result = self.invoke(['--bram-out', str(self.output), '--frame-out', str(self.root/'unavailable.ppm')])
        self.assertEqual(result.returncode, 2)
        self.assertIn('no completed video frame', result.stderr)
        self.assertFalse(self.output.exists())
        self.assert_seed()

    def test_duplicate_option_and_missing_value_are_refused(self):
        for options in (['--bram-out'], ['--bram-out', str(self.output), '--bram-out', str(self.output)]):
            with self.subTest(options=options):
                result = self.invoke(options)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.output.exists())
        self.assert_seed()

    def test_tcp_quit_publishes_only_after_exit_and_concurrent_destination_wins(self):
        self.image.write_bytes(bytes.fromhex('A9 47 8D 00 60 80 FE'))
        for race in (False, True):
            with self.subTest(race=race):
                output = self.root/('race.bram' if race else 'quit.bram')
                command = self.command(['--bram-out', str(output), '--dev-port', '0',
                                        '--dev-start-paused', 'on', '--wall-seconds', '10'], steps=10000000)
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True, env=self.environment)
                client = None
                try:
                    line = child.stderr.readline()
                    self.assertTrue(line.startswith('PCE_DEV_PORT='), line)
                    client = DevClient(int(line.split('=', 1)[1]), timeout=5)
                    initial = client.call('status')
                    self.assertEqual(initial['ticks'], 0)
                    self.assertFalse(output.exists())
                    client.advance(1)
                    first = client.call('status')
                    repeated = client.call('status')
                    self.assertEqual({k:v for k,v in first.items() if k != 'id'},
                                     {k:v for k,v in repeated.items() if k != 'id'})
                    self.assertFalse(output.exists())
                    if race:
                        output.write_bytes(b'other writer won')
                    client.call('quit')
                    stdout, stderr = child.communicate(timeout=5)
                    if race:
                        self.assertEqual(child.returncode, 2, stderr)
                        self.assertEqual(output.read_bytes(), b'other writer won')
                    else:
                        self.assertEqual(child.returncode, 0, stderr)
                        self.assertEqual(json.loads(stdout)['stop'], 'dev_quit')
                        expected = bytearray(self.pattern)
                        expected[0] = 0x47
                        self.assertEqual(output.read_bytes(), expected)
                finally:
                    if client is not None:
                        client.close()
                    if child.poll() is None:
                        child.kill()
                        child.communicate(timeout=5)
        self.assert_seed()

    def test_wall_timeout_cannot_publish_session(self):
        self.image.write_bytes(bytes.fromhex('80 FE'))
        result = self.invoke(['--bram-out', str(self.output), '--dev-port', '0',
                              '--dev-start-paused', 'on', '--wall-seconds', '1'], steps=10000000)
        self.assertEqual(result.returncode, 2)
        self.assertIn('no export', result.stderr)
        self.assertFalse(self.output.exists())
        self.assert_seed()

    def test_unicode_directory_seed_payload_firmware_script_and_outputs(self):
        directory = self.root/'saves 保存 U0001f3ae'
        directory.mkdir()
        self.image = directory/'guest é.bin'
        self.image.write_bytes(bytes.fromhex('80 FE'))
        self.seed = directory/'initial é.bram'
        self.seed.write_bytes(self.pattern)
        self.output = directory/'final é.bram'
        firmware = directory/'card é.pce'
        firmware.write_bytes(bytes(262144))
        script = directory/'input é.txt'
        script.write_text('PCE_INPUT 1\n0 0 0 0 0 0\n', encoding='ascii')
        screenshot = directory/'frame é.ppm'
        command = self.command(['--bios', str(firmware), '--input-script', str(script),
                                '--frame-out', str(screenshot), '--bram-out', str(self.output),
                                '--dev-port', '0', '--dev-start-paused', 'on', '--wall-seconds', '10'],
                               steps=10000000)
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, env=self.environment)
        client = None
        try:
            line = child.stderr.readline()
            self.assertTrue(line.startswith('PCE_DEV_PORT='), line)
            client = DevClient(int(line.split('=', 1)[1]), timeout=5)
            client.advance(1)
            client.call('quit')
            stdout, stderr = child.communicate(timeout=5)
            self.assertEqual(child.returncode, 0, stderr)
            final = json.loads(stdout)
            self.assertEqual(final['input_events_applied'], 1)
            self.assertEqual(final['development']['memory_bytes_changed'], 0)
            self.assertEqual(self.output.read_bytes(), self.pattern)
            self.assertTrue(screenshot.read_bytes().startswith(b'P6\n'))
            self.assert_seed()
        finally:
            if client is not None:
                client.close()
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)


@unittest.skipUnless(HEADLESS.is_file(), 'Build headless for BRAM export checks')
class HeadlessBramExportTests(BramExportChecks, unittest.TestCase):
    binary = HEADLESS


@unittest.skipUnless(DESKTOP.is_file(), 'Build desktop for BRAM export checks')
class DesktopBramExportTests(BramExportChecks, unittest.TestCase):
    binary = DESKTOP
    desktop = True
