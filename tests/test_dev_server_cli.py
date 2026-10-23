"""Run authored programs through the real loopback server and shared host loop."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from scripts.dev_client import DevClient, DevError

ROOT = Path(__file__).resolve().parent.parent
EXE = '.exe' if os.name == 'nt' else ''
HEADLESS = Path(os.environ.get('PCE_TEST_HEADLESS', ROOT/'build'/('pce-headless'+EXE)))
DESKTOP = Path(os.environ.get('PCE_TEST_DESKTOP', 'disabled'))


class RunningSandbox:
    def __init__(self, binary, root, desktop=False):
        image = root/'authored.bin'
        # Blue backdrop with background enabled, then an ordinary infinite BRA.
        image.write_bytes(bytes([0xA9, 7, 0x8D, 4, 4, 0xA9, 0, 0x8D, 5, 4,
                                 3, 5, 0x13, 0x80, 0x23, 0, 0x80, 0xFE]))
        command = [str(binary), str(image), '0x100000', '0x4000',
                   '255,248,128,129,130,131,132,0', '500000000', '3000000000',
                   'hybrid', '--dev-port', '0', '--dev-start-paused', 'on',
                   '--wall-seconds', '10']
        if desktop:
            command += ['--hidden', 'on', '--unthrottled', 'on', '--window-scale', '1']
        env = os.environ.copy()
        env.update(SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software')
        self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, env=env)
        line = self.process.stderr.readline()
        if not line.startswith('PCE_DEV_PORT='):
            self.close()
            raise AssertionError('development listener did not report its bound port: '+line)
        self.port = int(line.strip().split('=')[1])
        self.client = DevClient(self.port, timeout=5)

    def close(self):
        if hasattr(self, 'client'):
            self.client.close()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate(timeout=5)


@unittest.skipUnless(HEADLESS.is_file(), 'Build the headless runner')
class DevelopmentServerCliTests(unittest.TestCase):
    def test_paused_frame_advance_capture_input_disconnect_and_quit(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = RunningSandbox(HEADLESS, Path(tmp))
            try:
                client = app.client
                self.assertEqual(client.call('ping')['protocol'], 'pce-dev-1')
                initial = client.call('status')
                self.assertEqual((initial['frame'], initial['ticks'], initial['paused']), (0, 0, True))
                with self.assertRaises(DevError):
                    client.capture()
                client.call('set_input', mask=8, port=4)
                stopped = client.advance(3)
                self.assertEqual((stopped['frame'], stopped['paused']), (3, True))
                self.assertEqual(stopped['host']['buttons'][4], 8)
                metadata, rgb = client.capture()
                self.assertEqual((metadata['width'], metadata['height'], metadata['frame']), (256, 240, 3))
                self.assertEqual(rgb, bytes([0, 0, 255])*(256*240))
                time.sleep(0.02)
                again = client.call('status')
                self.assertEqual((stopped['ticks'], stopped['frame']), (again['ticks'], again['frame']))
                with self.assertRaises(DevError):
                    client.call('present_shot')
                client.close()
                app.client = DevClient(app.port, timeout=5)
                cleared = app.client.advance(1)
                self.assertEqual(cleared['host']['buttons'], [0]*5)
                app.client.call('quit')
                stdout, stderr = app.process.communicate(timeout=5)
                self.assertEqual(app.process.returncode, 0, stderr)
                final = json.loads(stdout)
                self.assertEqual(final['stop'], 'dev_quit')
                self.assertEqual(final['video_output']['frames'], 4)
            finally:
                app.close()


@unittest.skipUnless(DESKTOP.is_file(), 'Enable PCE_BUILD_DESKTOP')
class DesktopDevelopmentServerCliTests(unittest.TestCase):
    def test_composed_capture_matches_guest_at_one_to_one_scale(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = RunningSandbox(DESKTOP, Path(tmp), desktop=True)
            try:
                app.client.advance(3)
                guest, a = app.client.capture('guest')
                presented, b = app.client.capture('present')
                self.assertEqual((guest['width'], guest['height']), (256, 240))
                self.assertEqual((presented['width'], presented['height']), (256, 240))
                self.assertEqual(guest['frame'], presented['frame'])
                self.assertEqual(a, b)
                self.assertEqual(presented['source'], 'present')
                app.client.call('quit')
                stdout, stderr = app.process.communicate(timeout=5)
                self.assertEqual(app.process.returncode, 0, stderr)
                final = json.loads(stdout)
                self.assertEqual(final['stop'], 'dev_quit')
                self.assertEqual(final['desktop']['presented'], 3)
            finally:
                app.close()
