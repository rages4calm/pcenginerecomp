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
    def __init__(self, binary, root, desktop=False, satb_words=None, memory_write=False, bios=False, buttons=None):
        image = root/'authored.bin'
        # Blue backdrop with background enabled, then an ordinary infinite BRA.
        program = bytearray([0xA9, 7, 0x8D, 4, 4, 0xA9, 0, 0x8D, 5, 4,
                             3, 5, 0x13, 0x80, 0x23, 0])
        if satb_words is not None:
            if len(satb_words) != 256:
                raise ValueError('Authored SATB fixture must contain exactly 256 words')
            # MAWR=$1000, VWR fills, then SATB=$1000 arms one VBlank DMA.
            # Sprites remain disabled, preserving the independent blue image.
            program.extend([3, 0, 0x13, 0, 0x23, 0x10, 3, 2])
            for word in satb_words:
                program.extend([0x13, word & 255, 0x23, word >> 8])
            program.extend([3, 19, 0x13, 0, 0x23, 0x10])
        program.extend([0x80, 0xFE])
        image.write_bytes(program)
        command = [str(binary), str(image), '0x100000', '0x4000',
                   '255,248,128,129,130,131,132,0', '500000000', '3000000000',
                   'hybrid', '--dev-port', '0', '--dev-start-paused', 'on',
                   '--wall-seconds', '10']
        if desktop:
            command += ['--hidden', 'on', '--unthrottled', 'on', '--window-scale', '1']
        if memory_write:
            command += ['--dev-memory-write', 'on']
        if buttons is not None:
            command += ['--buttons', ','.join(map(str, buttons))]
        if bios:
            firmware = root/'authored-firmware.pce'
            firmware.write_bytes(bytes(262144))
            command += ['--bios', str(firmware)]
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


def check_pipelined_host_input(test, binary, *, desktop=False):
    """One send contains each input mutation and both following observations.

    Input diagnostics describe the current host masks even when the server
    handles all commands before the pump's normal guest-button application.
    The paused guest's controller latch, clocks and counters remain untouched.
    """
    with tempfile.TemporaryDirectory() as temporary:
        base = [1, 2, 4, 8, 16]
        masks = [0xF00, 0x801, 0x742, 0x183, 0xFFF]
        app = RunningSandbox(binary, Path(temporary), desktop=desktop, buttons=base)
        try:
            initial = app.client.call('status')
            test.assertEqual(initial['host']['buttons'], base)
            test.assertEqual((initial['ticks'], initial['frame'], initial['paused']), (0, 0, True))
            connection = app.client._socket
            # After the one baseline DevClient call, its receive buffer is empty.
            # Raw pipelined frames deliberately avoid per-request round trips.
            test.assertFalse(app.client._buffer)
            reader = connection.makefile('rb')
            identity = 100

            def batch(commands):
                nonlocal identity
                requests = []
                for command in commands:
                    requests.append({'id': identity, **command})
                    identity += 1
                encoded = b''.join(json.dumps(request, separators=(',', ':')).encode('ascii')+b'\n'
                                   for request in requests)
                test.assertLess(len(encoded), 4096)
                connection.sendall(encoded)
                responses = [json.loads(reader.readline()) for _ in requests]
                for request, response in zip(requests, responses):
                    test.assertTrue(response['ok'], response)
                    test.assertEqual(response['id'], request['id'])
                return responses

            def observe(status, expected):
                test.assertEqual(status['host']['buttons'], expected)
                test.assertEqual({key: value for key, value in status.items() if key not in {'id', 'host'}},
                                 {key: value for key, value in initial.items() if key not in {'id', 'host'}})
                test.assertEqual({key: value for key, value in status['host'].items() if key != 'buttons'},
                                 {key: value for key, value in initial['host'].items() if key != 'buttons'})

            try:
                for port, mask in enumerate(masks):
                    with test.subTest(port=port):
                        responses = batch([{'cmd': 'set_input', 'port': port, 'mask': mask}, {'cmd': 'status'},
                                           {'cmd': 'clear_input', 'port': port}, {'cmd': 'status'}])
                        expected = list(base)
                        expected[port] |= mask
                        observe(responses[1], expected)
                        observe(responses[3], base)
                responses = batch([*({'cmd': 'set_input', 'port': port, 'mask': mask}
                                      for port, mask in enumerate(masks)), {'cmd': 'status'},
                                   {'cmd': 'clear_input'}, {'cmd': 'status'}])
                observe(responses[5], [a | b for a, b in zip(base, masks)])
                observe(responses[7], base)
                batch([{'cmd': 'quit'}])
            finally:
                reader.close()
            stdout, stderr = app.process.communicate(timeout=5)
            test.assertEqual(app.process.returncode, 0, stderr)
            final = json.loads(stdout)
            test.assertEqual((final['ticks'], final['cycles'], final['native_steps'], final['interpreter_steps']), (0, 0, 0, 0))
            pad = final['joypad']
            test.assertEqual((pad['reads'], pad['writes'], pad['latched']), (0, 0, 0xB0))
            test.assertEqual((pad['sel'], pad['clr'], pad['extra'], pad['selected']), (True, True, False, 0))
            test.assertEqual([item['pressed'] for item in pad['pads']], base)
        finally:
            app.close()


@unittest.skipUnless(HEADLESS.is_file(), 'Build the headless runner')
class DevelopmentServerCliTests(unittest.TestCase):
    def test_pipelined_input_status_is_current_without_guest_retirement(self):
        check_pipelined_host_input(self, HEADLESS)

    def test_work_ram_alias_compare_write_and_boundary_are_coherent(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = RunningSandbox(HEADLESS, Path(tmp), memory_write=True)
            try:
                client = app.client
                data = bytes(range(1, 17))
                client.write_memory(0x1F2300, data, bytes(16))
                for bank in range(0xF8, 0xFC):
                    self.assertEqual(client.read_memory((bank << 13)+0x300, 16), data)
                before = client.call('status')
                with self.assertRaises(DevError):
                    client.write_memory(0x1F6300, bytes(16), bytes(16))
                self.assertEqual(client.call('status')['host']['debug_memory'], before['host']['debug_memory'])
                # Contiguous mapped addresses straddle the 8 KiB backing wrap.
                client.write_memory(0x1F3FFF, b'\x12\x34\x56', bytes(3))
                self.assertEqual(client.read_memory(0x1F1FFF, 3), b'\x12\x34\x56')
                self.assertEqual(client.read_memory(0x1F6000, 2), b'\x34\x56')
                self.assertEqual(client.call('status')['host']['debug_memory']['bytes_changed'], 19)
                self.assertEqual(client.call('status')['ticks'], 0)
            finally:
                app.close()

    def test_memory_reads_are_pure_and_writes_are_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = RunningSandbox(HEADLESS, Path(tmp))
            try:
                before = app.client.call('status')
                self.assertEqual(app.client.read_memory(0x100000, 2), bytes([0xA9, 7]))
                self.assertEqual(app.client.read_memory(0x1F0000, 256), bytes(256))
                self.assertEqual(before['host']['debug_memory'], {'write_enabled': False, 'write_requests': 0, 'bytes_changed': 0})
                with self.assertRaises(DevError):
                    app.client.write_memory(0x1F0000, b'\x01', b'\0')
                for address in (0, 0x1EE000, 0x1FE000):
                    with self.assertRaises(DevError):
                        app.client.read_memory(address, 1)
                self.assertEqual({k: v for k, v in app.client.call('status').items() if k != 'id'},
                                 {k: v for k, v in before.items() if k != 'id'})
            finally:
                app.close()

    def test_memory_compare_write_is_atomic_and_invalidates_changed_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = RunningSandbox(HEADLESS, Path(tmp), memory_write=True, bios=True)
            try:
                client = app.client
                before = client.call('status')
                self.assertEqual(client.read_memory(0, 4), bytes(4))
                data = bytes(range(1, 17))
                client.write_memory(0x100100, data, bytes(16))
                changed = client.call('status')
                self.assertEqual(client.read_memory(0x100100, 16), data)
                self.assertEqual((changed['ticks'], changed['frame']), (0, 0))
                self.assertEqual(changed['host']['cpu']['instruction_generations'], [v+16 for v in before['host']['cpu']['instruction_generations']])
                self.assertEqual(changed['host']['debug_memory'], {'write_enabled': True, 'write_requests': 1, 'bytes_changed': 16})
                for address, value, expected in ((0x100100, b'\xff'*16, bytes(16)),
                                                  (0, b'\xff', b'\0'),
                                                  (0x10FFFF, b'\x01\x02', bytes(2)),
                                                  (0x1EE000, b'\x01', b'\0'),
                                                  (0x1FE000, b'\x01', b'\0')):
                    with self.assertRaises(DevError):
                        client.write_memory(address, value, expected)
                    self.assertEqual({k: v for k, v in client.call('status').items() if k != 'id'},
                                     {k: v for k, v in changed.items() if k != 'id'})
                self.assertEqual(client.read_memory(0x10FFFF, 1), b'\0')
                client.write_memory(0x100100, data, data)
                same = client.call('status')
                self.assertEqual(same['host']['cpu'], changed['host']['cpu'])
                self.assertEqual(same['host']['debug_memory'], {'write_enabled': True, 'write_requests': 2, 'bytes_changed': 16})
                client.call('quit')
                stdout, stderr = app.process.communicate(timeout=5)
                self.assertEqual(app.process.returncode, 0, stderr)
                final = json.loads(stdout)['development']
                self.assertTrue(final['memory_write_enabled'])
                self.assertEqual((final['memory_write_requests'], final['memory_bytes_changed']), (2, 16))
            finally:
                app.close()

    def test_memory_write_cli_requires_explicit_valid_server_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp)/'authored.bin'
            image.write_bytes(b'\x80\xfe')
            base = [str(HEADLESS), str(image), '0x100000', '0x4000', '255,248,128,129,130,131,132,0', '1', '100', 'hybrid']
            for args in (['--dev-memory-write', 'on'], ['--dev-memory-write', 'off'],
                         ['--dev-port', '0', '--dev-memory-write', 'yes'],
                         ['--dev-port', '0', '--dev-memory-write', 'on', '--dev-memory-write', 'off']):
                result = subprocess.run(base+args, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_paused_frame_advance_capture_input_disconnect_and_quit(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = RunningSandbox(HEADLESS, Path(tmp))
            try:
                client = app.client
                self.assertEqual(client.call('ping')['protocol'], 'pce-dev-1')
                initial = client.call('status')
                self.assertEqual((initial['frame'], initial['ticks'], initial['paused']), (0, 0, True))
                cpu = initial['host']['cpu']
                self.assertEqual([cpu[k] for k in ('a', 'x', 'y', 'sp', 'p')], [0, 0, 0, 255, 4])
                self.assertEqual(cpu['mpr'], [255, 248, 128, 129, 130, 131, 132, 0])
                self.assertEqual(cpu['physical_pc'], 0x100000)
                self.assertEqual(cpu['instruction_bytes'], [0xA9, 7, 0x8D, 4, 4, 0xA9, 0])
                self.assertEqual(cpu['instruction_physical'], list(range(0x100000, 0x100007)))
                self.assertEqual(len(cpu['instruction_generations']), 7)
                self.assertTrue(all(g == cpu['instruction_generations'][0] for g in cpu['instruction_generations']))
                self.assertEqual(initial['host']['scsi']['last_command'], [])
                self.assertEqual(initial['host']['cd_audio']['state'], 1)
                self.assertEqual(initial['host']['adpcm']['samples'], 0)
                self.assertFalse(initial['host']['adpcm']['playing'])
                self.assertEqual(initial['host']['vdc']['satb'], [0]*256)
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
                # Polling diagnostics must not consume a data byte, acknowledge an
                # interrupt, move audio clocks, or mutate any guest-visible state.
                self.assertEqual(stopped['host'], again['host'])
                self.assertEqual(again['host']['cpu']['instruction_bytes'][:2], [0x80, 0xFE])
                self.assertEqual(again['host']['cpu']['physical_pc'], 0x100010)
                self.assertEqual(again['host']['vdc']['registers'][5], 0x80)
                self.assertEqual(len(again['host']['vdc']['registers']), 20)
                self.assertGreater(again['host']['raster']['master_ticks'], 0)
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
                self.assertEqual(final['cd_audio'], again['host']['cd_audio'])
                self.assertEqual(final['adpcm'], again['host']['adpcm'])
            finally:
                app.close()

    def test_satb_status_observes_authored_vblank_dma_without_mutation(self):
        # Distinct unsigned words, including high bits and width boundaries.
        # Keep all Y coordinates above the active region: even BG-only mode
        # fetches sprite patterns, and this test isolates raw SATB DMA rather
        # than requesting undriven VRAM through arbitrary pattern words.
        expected = [(i*257) ^ 0xA55A for i in range(256)]
        for i in range(0, 256, 4):
            expected[i] &= 0xFC00
        expected[:4] = [0, 0x7FFF, 0x8000, 0xFFFF]
        with tempfile.TemporaryDirectory() as tmp:
            app = RunningSandbox(HEADLESS, Path(tmp), satb_words=expected)
            try:
                initial = app.client.call('status')
                self.assertEqual(initial['host']['vdc']['satb'], [0]*256)
                stopped = app.client.advance(3)
                self.assertEqual(stopped['host']['vdc']['satb'], expected)
                self.assertEqual(stopped['host']['vdc']['satb_pending'], 0)
                self.assertLess(len(json.dumps(stopped)), 16384)
                time.sleep(0.02)
                again = app.client.call('status')
                self.assertEqual(stopped['host'], again['host'])
                self.assertEqual(stopped['ticks'], again['ticks'])
                app.client.call('quit')
                stdout, stderr = app.process.communicate(timeout=5)
                self.assertEqual(app.process.returncode, 0, stderr)
                self.assertEqual(json.loads(stdout)['stop'], 'dev_quit')
            finally:
                app.close()


@unittest.skipUnless(DESKTOP.is_file(), 'Enable PCE_BUILD_DESKTOP')
class DesktopDevelopmentServerCliTests(unittest.TestCase):
    def test_pipelined_input_status_is_current_without_guest_retirement(self):
        check_pipelined_host_input(self, DESKTOP, desktop=True)

    def test_desktop_memory_write_uses_shared_paused_ram_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = RunningSandbox(DESKTOP, Path(tmp), desktop=True, memory_write=True)
            try:
                app.client.write_memory(0x1F0000, b'\x12\x34', b'\0\0')
                self.assertEqual(app.client.read_memory(0x1F0000, 2), b'\x12\x34')
                status = app.client.call('status')
                self.assertEqual((status['frame'], status['ticks']), (0, 0))
                self.assertEqual(status['host']['debug_memory']['bytes_changed'], 2)
            finally:
                app.close()

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
