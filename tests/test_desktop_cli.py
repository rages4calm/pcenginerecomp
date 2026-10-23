"""Authored host integration boundaries; no retail inputs or persistent state."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
EXE = '.exe' if os.name == 'nt' else ''
HEADLESS = Path(os.environ.get('PCE_TEST_HEADLESS', ROOT/'build'/('pce-headless'+EXE)))
DESKTOP = Path(os.environ.get('PCE_TEST_DESKTOP', 'disabled'))


def invoke(binary, image, *options, ticks=750000, steps=100000):
    env = os.environ.copy()
    env.update(SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software')
    return subprocess.run([str(binary), str(image), '0x100000', '0x4000',
                           '255,248,128,129,130,131,132,0', str(steps),
                           str(ticks), 'hybrid', *options], env=env,
                          capture_output=True, text=True, timeout=10)


@unittest.skipUnless(HEADLESS.is_file(), 'Build the headless runner')
class ContinuousCliTests(unittest.TestCase):
    def test_extended_step_allowance_still_obeys_tick_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp)/'authored.bin'
            image.write_bytes(bytes([0x80, 0xFE]))
            result = invoke(HEADLESS, image, ticks=1, steps=2000000000)
            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads(result.stdout)
            self.assertEqual(state['stop'], 'budget')
            self.assertEqual(state['native_steps']+state['interpreter_steps'], 1)
            for steps in (0, 20000000001):
                rejected = invoke(HEADLESS, image, ticks=1, steps=steps)
                self.assertEqual(rejected.returncode, 2)
                self.assertEqual(rejected.stdout, '')

    def test_continuous_publication_preserves_cpu_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp)/'authored.bin'
            image.write_bytes(bytes([0x80, 0xFE]))
            snapshot = invoke(HEADLESS, image)
            output = Path(tmp)/'completed.ppm'
            continuous = invoke(HEADLESS, image, '--video-output', 'continuous',
                                '--frame-out', str(output))
            self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
            self.assertEqual(continuous.returncode, 0, continuous.stderr)
            a, b = json.loads(snapshot.stdout), json.loads(continuous.stdout)
            for field in ('pc', 'ticks', 'cycles', 'native_steps', 'interpreter_steps',
                          'p', 'sp', 'mpr', 'joypad', 'raster'):
                if field in ('joypad', 'raster'):
                    continue  # The default profile intentionally has no video/pad.
                self.assertEqual(a[field], b[field], field)
            self.assertEqual(b['video_output']['frames'], 2)
            self.assertEqual(b['video_output']['completed_ticks'], 715260)
            self.assertTrue(output.read_bytes().startswith(b'P6\n256 240\n255\n'))
            protected = output.read_bytes()
            again = invoke(HEADLESS, image, '--video-output', 'continuous',
                           '--frame-out', str(output))
            self.assertEqual(again.returncode, 2)
            self.assertEqual(output.read_bytes(), protected)
            self.assertEqual(image.read_bytes(), bytes([0x80, 0xFE]))

    def test_no_completed_frame_does_not_create_an_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp)/'authored.bin'
            image.write_bytes(bytes([0x80, 0xFE]))
            output = Path(tmp)/'too-early.ppm'
            result = invoke(HEADLESS, image, '--video-output', 'continuous',
                            '--frame-out', str(output), ticks=10)
            self.assertEqual(result.returncode, 2)
            self.assertIn('no completed video frame', result.stderr)
            self.assertFalse(output.exists())
            self.assertEqual(result.stdout, '')


@unittest.skipUnless(DESKTOP.is_file(), 'Enable PCE_BUILD_DESKTOP')
class DesktopCliTests(unittest.TestCase):
    def test_dummy_window_presents_completed_frames_with_same_cpu_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp)/'authored.bin'
            image.write_bytes(bytes([0x80, 0xFE]))
            direct = invoke(HEADLESS, image, '--video-output', 'continuous')
            capture = Path(tmp)/'window.ppm'
            result = invoke(DESKTOP, image, '--hidden', 'on', '--unthrottled', 'on',
                            '--window-scale', '1', '--window-capture', str(capture))
            self.assertEqual(result.returncode, 0, result.stderr)
            a, b = json.loads(direct.stdout), json.loads(result.stdout)
            for field in ('pc', 'ticks', 'cycles', 'native_steps', 'interpreter_steps',
                          'mpr', 'joypad', 'raster', 'video_output'):
                self.assertEqual(a[field], b[field], field)
            self.assertEqual(b['desktop']['presented'], 2)
            self.assertGreater(b['desktop']['polls'], 0)
            self.assertTrue(capture.read_bytes().startswith(b'P6\n256 240\n255\n'))
            protected = capture.read_bytes()
            again = invoke(DESKTOP, image, '--window-capture', str(capture))
            self.assertEqual(again.returncode, 2)
            self.assertEqual(capture.read_bytes(), protected)

    def test_desktop_option_validation_precedes_window_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp)/'authored.bin'
            image.write_bytes(bytes([0x80, 0xFE]))
            for options in (('--video-output', 'snapshot'), ('--window-scale', '0'),
                            ('--window-scale', '7'), ('--wall-seconds', '0'),
                            ('--wall-seconds', '601'), ('--hidden', 'yes'),
                            ('--unthrottled', 'yes'), ('--hidden', 'on', '--hidden', 'off')):
                with self.subTest(options=options):
                    result = invoke(DESKTOP, image, *options)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, '')
