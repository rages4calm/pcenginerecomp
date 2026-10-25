"""Authored HuCard exercises CG selection/monochrome through guest input.

Fixtures contain no retail bytes. TCP only supplies controller input and reads
completed guest pictures; all device configuration is executed by the guest.
The same helpers are usable with a separately generated native-only consumer.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.dev_client import DevClient
from test_hucard_boot import authored_hucard

ROOT = Path(__file__).resolve().parent.parent
EXE = '.exe' if os.name == 'nt' else ''
HEADLESS = Path(os.environ.get('PCE_TEST_HEADLESS', ROOT/'build'/('pce-headless'+EXE)))
DESKTOP = Path(os.environ.get('PCE_TEST_DESKTOP', 'disabled'))


def video_program():
    code, labels, fixups = bytearray(), {}, []

    def put(*values):
        code.extend(values)

    def branch(op, label):
        put(op, 0)
        fixups.append((len(code)-1, label, 'relative'))

    def lookup(label):
        put(0xBD, 0, 0)  # LDA table,X in the same authored ROM.
        fixups.append((len(code)-2, label, 'absolute'))

    def register(index, value):
        put(3, index, 0x13, value & 255, 0x23, value >> 8)

    def store(address, value):
        put(0xA9, value, 0x8D, address & 255, address >> 8)

    put(0x78, 0xD4, 0xD8, 0xA9, 0xFF, 0x53, 1, 0xA9, 0xF8, 0x53, 2)
    register(5, 0)  # Configure the authored picture while display is off.
    register(0, 0)
    put(3, 2, 0xA2, 0, 0xA0, 4)
    labels['bat'] = len(code)
    put(0x13, 0, 0x23, 0x21, 0xCA)  # BAT: tile $100, palette 2.
    branch(0xD0, 'bat')
    put(0x88)
    branch(0xD0, 'bat')
    register(0, 4096)
    put(3, 2)
    for word in [0x55AA]*8 + [0x0F33]*8:
        put(0x13, word & 255, 0x23, word >> 8)
    for index, color in ((0, 7), (33, 0x38), (34, 0x1C0), (35, 0x1FF)):
        store(0x402, index)
        store(0x403, 0)
        store(0x404, color & 255)
        store(0x405, color >> 8)
    for index, value in ((7, 0), (8, 0), (9, 3), (10, 0x0202),
                         (11, 0x2103), (12, 0x0F02), (13, 7), (14, 234), (5, 128)):
        register(index, value)
    labels['poll'] = len(code)
    store(0x1000, 1)
    store(0x1000, 0)
    put(0xAD, 0, 0x10, 0x49, 3, 0x29, 3, 0xAA, 0x8D, 0, 0x20)
    put(3, 9)
    lookup('cg')
    put(0x8D, 2, 0, 0xA9, 0, 0x8D, 3, 0)
    lookup('mono')
    put(0x8D, 0, 4)
    branch(0x80, 'poll')
    labels['cg'] = len(code)
    put(3, 0x83, 3, 0x83)
    labels['mono'] = len(code)
    put(0, 0, 0x80, 0x80)
    for position, label, kind in fixups:
        if kind == 'relative':
            displacement = labels[label]-(position+1)
            if not -128 <= displacement <= 127:
                raise ValueError('Authored relative branch exceeds range')
            code[position] = displacement & 255
        else:
            code[position:position+2] = (0xE100+labels[label]).to_bytes(2, 'little')
    return bytes(code)


def expected_picture(buttons):
    # Independently authored literal colors, including transparent palette zero.
    colors = [(0, 0, 255), (255, 0, 0), (0, 255, 0), (255, 255, 255)]
    if buttons & 2:
        colors = [(v, v, v) for v in (29, 76, 149, 255)]
    pattern = (0, 0, 1, 1, 2, 2, 3, 3) if buttons & 1 else (1, 2, 1, 2, 1, 2, 1, 2)
    return bytes(component for _y in range(8) for x in range(32) for component in colors[pattern[x % 8]])


def tcp_modes(binary, card, *, desktop=False, tier='hybrid', capture=None):
    """Finite five-state input route, natural quit, and unconditional cleanup."""
    command = [str(binary), '--hucard-reset', 'base', str(card), '10000000', '20000000', tier,
               '--video-output', 'continuous', '--audio-output', 'off', '--dev-port', '0',
               '--dev-start-paused', 'on', '--wall-seconds', '20']
    if capture:
        command += ['--code-capture', str(capture), '--capture-limit', '1024']
    if desktop:
        command += ['--hidden', 'on', '--unthrottled', 'on', '--window-scale', '1']
    environment = os.environ.copy()
    environment.update(SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software', SDL_AUDIODRIVER='dummy')
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, env=environment)
    observations = []
    try:
        line = process.stderr.readline()
        if not line.startswith('PCE_DEV_PORT='):
            raise AssertionError(line)
        with DevClient(int(line.strip().split('=')[1]), timeout=10) as client:
            initial = client.call('status')
            assert initial['paused'] and initial['ticks'] == 0
            for buttons in (0, 1, 3, 2, 0):
                client.call('set_input', port=0, mask=buttons)
                state = client.advance(3)
                assert client.read_memory(0x1F0000, 1) == bytes((buttons,))
                metadata, rgb = client.capture()
                assert (metadata['width'], metadata['height']) == (32, 8), metadata
                assert rgb == expected_picture(buttons), (buttons, rgb[:48])
                observations.append(dict(buttons=buttons, state=state, metadata=metadata, rgb=rgb.hex()))
            client.call('quit')
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
        result = json.loads(stdout)
        assert result['stop'] == 'dev_quit'
        if tier == 'native':
            assert result['guard_misses'] == 0
        assert result['development']['memory_write_requests'] == 0
        return dict(observations=observations, result=result, command=command,
                    stdout=stdout, stderr=line+stderr)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)


class VideoModeHostChecks:
    desktop = False

    def test_input_drives_both_cg_banks_and_live_monochrome(self):
        with tempfile.TemporaryDirectory() as temporary:
            card = Path(temporary)/'authored-video.pce'
            raw = authored_hucard(video_program())
            card.write_bytes(raw)
            result = tcp_modes(self.binary, card, desktop=self.desktop)
            self.assertEqual(card.read_bytes(), raw)
            self.assertEqual(result['result']['native_steps'], 0)
            self.assertGreater(result['result']['interpreter_steps'], 0)
            self.assertEqual(len(result['observations']), 5)


@unittest.skipUnless(HEADLESS.is_file(), 'build headless runner first')
class HeadlessVideoModes(VideoModeHostChecks, unittest.TestCase):
    binary = HEADLESS


@unittest.skipUnless(DESKTOP.is_file(), 'optional SDL runner not configured')
class DesktopVideoModes(VideoModeHostChecks, unittest.TestCase):
    binary = DESKTOP
    desktop = True


if __name__ == '__main__':
    unittest.main()
