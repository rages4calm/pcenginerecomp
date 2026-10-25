"""Authored firmware exercises Arcade Card Duo through real guest instructions.

The TCP route only supplies input and reads paused state. No Arcade RAM, CPU
register or owner save is injected. Debugger refusal cases are separate.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.dev_client import DevClient, DevError
from test_reset_boot import authored_card

ROOT = Path(__file__).resolve().parent.parent
EXE = '.exe' if os.name == 'nt' else ''
HEADLESS = Path(os.environ.get('PCE_TEST_HEADLESS', ROOT/'build'/('pce-headless'+EXE)))
DESKTOP = Path(os.environ.get('PCE_TEST_DESKTOP', 'disabled'))


def arcade_program():
    code = bytearray(bytes.fromhex('78 D4 D8 A9 FF 53 01 A9 F8 53 02'))

    def put(*values):
        code.extend(values)

    def store(address, value):
        put(0xA9, value, 0x8D, address & 255, address >> 8)

    def read_to(address, destination):
        put(0xAD, address & 255, address >> 8, 0x8D, destination & 255, destination >> 8)

    def port(index, base, control=0):
        address = 0x1A00+index*16
        for register, value in ((2, base & 255), (3, (base >> 8) & 255), (4, base >> 16),
                                (5, 0), (6, 0), (7, 1), (8, 0), (9, control)):
            store(address+register, value)

    for index in range(4):
        put(0xA9, 0x40+index, 0x53, 1 << (index+2))
    port(0, 0x1FFFFC, 3)  # Auto-increment the offset and include it in addressing.
    port(1, 0x100)
    port(2, 0x10000, 10)  # Add offset and subtract 64 KiB -> RAM address zero.
    port(3, 0x1800)
    loop = len(code)
    store(0x1000, 1)
    store(0x1000, 0)
    put(0xAD, 0, 0x10, 0x49, 3, 0x29, 3, 0xAA, 0x8D, 0, 0x20)
    for index in range(8):
        put(0x8A, 0x18, 0x69, 0x40+index, 0x8D, index, 0x23)
    store(0x1A05, 0)
    store(0x1A06, 0)
    # Eight consecutive addresses in the mapped window all access port zero.
    put(0x73, 0, 0x23, 0, 0x40, 8, 0)  # TII $2300,$4000,8.
    store(0x1A45, 0)  # Hardware mirror of port zero's offset registers.
    store(0x1A46, 0)
    put(0x73, 0, 0x40, 0, 0x24, 8, 0)  # TII $4000,$2400,8.
    for index in range(1, 4):
        put(0x8A, 0x18, 0x69, 0x60+index)
        put(0x8D, (0x1A00+index*16) & 255, 0x1A)
        read_to(0x4000+index*0x2000, 0x2000+index)
    for index, value in enumerate((0x78, 0x56, 0x34, 0xE2)):
        store(0x1AE0+index, value)
    put(0x8E, 0xE5, 0x1A)  # STX rotate amount, always zero through three.
    for index in range(4):
        read_to(0x1AE0+index, 0x2004+index)
    read_to(0x1AFE, 0x2008)
    read_to(0x1AFF, 0x2009)
    # The authored loop is larger than a relative branch; JMP is intentional.
    put(0x4C, (0xE100+loop) & 255, (0xE100+loop) >> 8)
    return bytes(code)


def expected_ram(buttons):
    # Literal independent rotations include wraparound from the high bits.
    rotated = (0xE2345678, 0xC468ACF1, 0x88D159E3, 0x11A2B3C7)[buttons]
    return bytes((buttons, 0x61+buttons, 0x62+buttons, 0x63+buttons))+rotated.to_bytes(4, 'little')+bytes((0x10, 0x51))


def expected_boot():
    return dict(mode='system-card-reset', profile='super',
                initialization='gear-deterministic-zero-v1', vector_physical=8190,
                pc=0xE100, a=0, x=0, y=0, sp=0, p=4, clock_divisor=12, ticks=0,
                cycles=0, mpr=[0]*8, bram='blank-unformatted', arcade_card='duo')


def arcade_route(binary, bios, *, desktop=False, tier='hybrid', capture=None, probe_debug=False):
    command = [str(binary), '--system-card-reset', 'super', str(bios), '10000000', '20000000', tier,
               '--arcade-card', 'duo', '--video-output', 'continuous', '--audio-output', 'off',
               '--dev-port', '0', '--dev-start-paused', 'on', '--wall-seconds', '20']
    if capture:
        command += ['--code-capture', str(capture), '--capture-limit', '1024']
    if probe_debug:
        command += ['--dev-memory-write', 'on']
    if desktop:
        command += ['--hidden', 'on', '--unthrottled', 'on', '--window-scale', '1']
    environment = os.environ.copy()
    environment.update(SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software', SDL_AUDIODRIVER='dummy')
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, env=environment)
    observations = []
    try:
        line = process.stderr.readline()
        assert line.startswith('PCE_DEV_PORT='), line
        with DevClient(int(line.strip().split('=')[1]), timeout=10) as client:
            initial = client.call('status')
            assert initial['paused'] and initial['ticks'] == 0
            assert initial['host']['boot'] == expected_boot()
            for buttons in (0, 3, 1, 2, 0):
                client.call('set_input', port=0, mask=buttons)
                state = client.advance(2)
                ram = client.read_memory(0x1F0000, 10)
                buffer = client.read_memory(0x1F0400, 8)
                assert ram == expected_ram(buttons), (buttons, ram)
                assert buffer == bytes(range(0x40+buttons, 0x48+buttons)), (buttons, buffer)
                hardware = state['host']['arcade_card']
                assert hardware['profile'] == 'duo' and hardware['ram_bytes'] == 2097152
                assert hardware['ports'][0]['base'] == 0x1FFFFC
                assert hardware['ports'][2]['effective_address'] == 0
                if probe_debug:
                    before = copy.deepcopy(hardware)
                    for address in (0x80000, 0x82000, 0x84000, 0x86000):
                        try:
                            client.read_memory(address, 1)
                        except DevError:
                            pass
                        else:
                            raise AssertionError('Arcade data window exposed as debugger RAM')
                        try:
                            client.write_memory(address, bytes((1,)), bytes((0,)))
                        except DevError:
                            pass
                        else:
                            raise AssertionError('Arcade data window accepted debugger RAM write')
                    assert client.call('status')['host']['arcade_card'] == before
                observations.append(dict(buttons=buttons, ram=ram.hex(), buffer=buffer.hex(), state=state))
            metadata, rgb = client.capture()
            assert len(rgb) == metadata['width']*metadata['height']*3
            client.call('quit')
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
        result = json.loads(stdout)
        assert result['stop'] == 'dev_quit'
        assert result['development']['memory_write_requests'] == 0
        assert result['development']['memory_bytes_changed'] == 0
        assert result['boot'] == expected_boot()
        if tier == 'native':
            assert result['interpreter_steps'] == 0 and result['guard_misses'] == 0
        else:
            assert result['native_steps'] == 0
        return dict(command=command, observations=observations, result=result,
                    stdout=stdout, stderr=line+stderr, metadata=metadata,
                    rgb_sha256=hashlib.sha256(rgb).hexdigest())
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)


class ArcadeHostChecks:
    desktop = False

    def route(self, *, probe_debug=False):
        with tempfile.TemporaryDirectory() as temporary:
            bios = Path(temporary)/'authored-system-card.pce'
            raw = authored_card(arcade_program())
            bios.write_bytes(raw)
            route = arcade_route(self.binary, bios, desktop=self.desktop, probe_debug=probe_debug)
            self.assertEqual(bios.read_bytes(), raw)
            self.assertEqual(len(route['observations']), 5)

    def test_guest_wrap_block_transfers_all_ports_shifter_and_input(self):
        self.route()

    def test_debugger_refuses_side_effect_windows_without_touching_ports(self):
        self.route(probe_debug=True)

    def test_unsupported_attachments_reject_before_creating_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bios = root/'authored.pce'
            bios.write_bytes(authored_card())
            output = root/'must-not-exist.ppm'
            for startup in (['--system-card-reset', 'standard', str(bios), '1', '10000', 'hybrid', '--arcade-card', 'duo'],
                            ['--system-card-reset', 'super', str(bios), '1', '10000', 'hybrid', '--arcade-card', 'pro'],
                            ['--system-card-reset', 'super', str(bios), '1', '10000', 'hybrid', '--arcade-card', 'duo', '--arcade-card', 'duo'],
                            ['--hucard-reset', 'base', str(bios), '1', '10000', 'hybrid', '--arcade-card', 'duo'],
                            [str(bios), '0', str(0xE100), '0,0,0,0,0,0,0,0', '1', '10000', 'hybrid', '--arcade-card', 'duo']):
                command = [str(self.binary), *startup, '--frame-out', str(output)]
                if self.desktop:
                    command += ['--hidden', 'on', '--unthrottled', 'on']
                result = subprocess.run(command, capture_output=True, text=True, timeout=10)
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertFalse(output.exists())


@unittest.skipUnless(HEADLESS.is_file(), 'Build the headless runner first')
class HeadlessArcadeChecks(ArcadeHostChecks, unittest.TestCase):
    binary = HEADLESS


@unittest.skipUnless(DESKTOP.is_file(), 'Optional SDL runner not configured')
class DesktopArcadeChecks(ArcadeHostChecks, unittest.TestCase):
    binary = DESKTOP
    desktop = True


if __name__ == '__main__':
    unittest.main()
