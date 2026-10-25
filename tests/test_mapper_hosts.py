"""Authored enhanced cartridges: guest mapper/RAM code under real TCP hosts.

No game media or firmware is used. Ordinary qualification never edits memory
through TCP. The separate explicit debug-CAS test records its own write count.
"""
import hashlib
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
_REVERSE = bytes(int(f'{value:08b}'[::-1], 2) for value in range(256))


def mapper_program(profile):
    code = bytearray(bytes.fromhex('78 D4 D8 A9 FF 53 01 A9 F8 53 02'))

    def put(*values):
        code.extend(values)

    def store(address, value):
        put(0xA9, value, 0x8D, address & 255, address >> 8)

    put(0xA9, 0 if profile == 'sf2' else 0x40, 0x53, 4)
    put(0xA9, 0x40 if profile == 'sf2' else 0x5C, 0x53, 8)
    put(0xA9, 0x60, 0x53, 16)  # Populous's upper surviving ROM aperture.
    loop = len(code)
    store(0x1000, 1)
    store(0x1000, 0)
    put(0xAD, 0, 0x10, 0x49, 3, 0x29, 3, 0xAA, 0x8D, 0, 0x20)
    if profile == 'sf2':
        # Data is deliberately unrelated to selection; the physical write
        # address chooses the mapper latch. All four callees share PC/MPR/PA.
        put(0xA9, 0xA7, 0x9D, 0xF0, 0x5F, 0x20, 0, 0x61)
        put(0xAD, 0, 0x60, 0x8D, 2, 0x20, 0xAD, 1, 0x60, 0x8D, 3, 0x20)
    elif profile == 'populous':
        # Author the callable routine in physical bank40; execute its bank5C
        # mirror. Four immediate values require real per-byte source variants.
        store(0x4000, 0xA9)
        put(0x8A, 0x18, 0x69, 0x60, 0x8D, 1, 0x40)
        store(0x4002, 0x60)
        put(0x20, 0, 0x60, 0x8D, 1, 0x20)
        put(0xAD, 0, 0x40, 0x8D, 2, 0x20, 0xAD, 1, 0x60, 0x8D, 3, 0x20)
    else:
        raise ValueError('Authored fixture requires sf2 or populous')
    put(0xAD, 0, 0x18, 0x8D, 4, 0x20, 0xAD, 0, 0x80, 0x8D, 5, 0x20)
    displacement = loop-(len(code)+2)
    if not -128 <= displacement <= 127:
        raise ValueError('Authored polling branch exceeds relative range')
    put(0x80, displacement & 255)
    return bytes(code)


def authored_mapper(profile, *, encoded=False):
    count = 320 if profile == 'sf2' else 64
    raw = bytearray()
    for bank in range(count):
        # Two literal marker bytes distinguish bank00 and bank100, which have
        # identical low bytes but live in different SF2 source windows.
        block = bytearray(bytes((bank & 255,))*8192)
        block[1] = bank >> 8
        raw.extend(block)
    code = mapper_program(profile)
    raw[0x100:0x100+len(code)] = code
    raw[8190:8192] = bytes((0, 0xE1))
    if profile == 'sf2':
        for selector in range(4):
            offset = 0x80000+selector*0x80000+0x100
            raw[offset:offset+6] = bytes((0xA9, 0x30+selector, 0x8D, 1, 0x20, 0x60))
    return bytes((0x96,))*512+bytes(raw).translate(_REVERSE) if encoded else bytes(raw)


def expected_ram(profile, buttons):
    if profile == 'sf2':
        bank = 64+64*buttons
        return bytes((buttons, 0x30+buttons, bank & 255, bank >> 8, 255, (96+64*buttons) & 255))
    return bytes((buttons, 0x60+buttons, 0xA9, 0x60+buttons, 255, 32))


def mapper_route(binary, card, profile, *, desktop=False, tier='hybrid', encoded=False,
                 capture=None, debug_cas=False):
    command = [str(binary), '--hucard-reset', profile, str(card), '10000000', '20000000', tier,
               '--rom-header', 'copier512' if encoded else 'none',
               '--rom-encoding', 'bit-reversed' if encoded else 'linear',
               '--video-output', 'continuous', '--audio-output', 'off', '--dev-port', '0',
               '--dev-start-paused', 'on', '--wall-seconds', '20']
    if capture:
        command += ['--code-capture', str(capture), '--capture-limit', '1024']
    if debug_cas:
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
            assert initial['host']['boot']['profile'] == profile
            if profile == 'sf2':
                assert initial['host']['boot']['mapper_latch'] == 0
            else:
                assert initial['host']['boot']['cartridge_ram_bytes'] == 32768
            assert not initial['host']['cd_control']['enabled']
            for buttons in (0, 3, 1, 2, 0):
                client.call('set_input', mask=buttons, port=0)
                state = client.advance(2)
                ram = client.read_memory(0x1F0000, 6)
                assert ram == expected_ram(profile, buttons), (profile, buttons, ram)
                assert client.read_memory(0x1F6000, 6) == ram
                hardware = state['host']['cartridge']
                assert hardware == dict(profile=profile, mapper_latch=buttons if profile == 'sf2' else 0,
                                        rom_bytes=0x280000 if profile == 'sf2' else 0x80000,
                                        ram_bytes=0 if profile == 'sf2' else 32768), hardware
                if profile == 'populous':
                    routine = bytes((0xA9, 0x60+buttons, 0x60))
                    assert client.read_memory(0x80000, 3) == routine
                    assert client.read_memory(0xB8000, 3) == routine
                else:
                    assert client.read_memory(0x80000, 2) == bytes(((64+64*buttons) & 255, (64+64*buttons) >> 8))
                observations.append(dict(buttons=buttons, ram=ram.hex(), state=state))
            if debug_cas:
                assert profile == 'populous'
                assert client.read_memory(0x80100, 1) == bytes((0,))
                client.write_memory(0xB8100, bytes((0xD3,)), bytes((0,)))
                assert client.read_memory(0x80100, 1) == bytes((0xD3,))
                assert client.read_memory(0x88100, 1) == bytes((0xD3,))
            client.call('quit')
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
        result = json.loads(stdout)
        assert result['stop'] == 'dev_quit'
        assert result['interpreter_steps'] == 0 if tier == 'native' else result['native_steps'] == 0
        if tier == 'native':
            assert result['guard_misses'] == 0
        assert result['development']['memory_write_requests'] == (1 if debug_cas else 0)
        assert result['development']['memory_bytes_changed'] == (1 if debug_cas else 0)
        assert not result['scsi']['enabled'] and not result['adpcm']['enabled']
        return dict(command=command, observations=observations, result=result, stdout=stdout, stderr=line+stderr)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)


class MapperHostChecks:
    desktop = False

    def route(self, profile, *, encoded=False, debug_cas=False):
        with tempfile.TemporaryDirectory() as temporary:
            card = Path(temporary)/'authored.pce'
            raw = authored_mapper(profile, encoded=encoded)
            card.write_bytes(raw)
            result = mapper_route(self.binary, card, profile, desktop=self.desktop,
                                  encoded=encoded, debug_cas=debug_cas)
            self.assertEqual(hashlib.sha256(card.read_bytes()).digest(), hashlib.sha256(raw).digest())
            return result

    def test_sf2_same_identity_four_source_variants_select_by_address(self):
        self.route('sf2')

    def test_sf2_header_and_bit_reversal_do_not_change_guest_mapper(self):
        self.route('sf2', encoded=True)

    def test_populous_guest_authors_and_executes_mirrored_ram_code(self):
        self.route('populous')

    def test_populous_debug_cas_uses_the_same_ram_aliases_with_explicit_counts(self):
        self.route('populous', debug_cas=True)


@unittest.skipUnless(HEADLESS.is_file(), 'Build headless runner first')
class HeadlessMapperChecks(MapperHostChecks, unittest.TestCase):
    binary = HEADLESS


@unittest.skipUnless(DESKTOP.is_file(), 'Optional SDL runner not configured')
class DesktopMapperChecks(MapperHostChecks, unittest.TestCase):
    binary = DESKTOP
    desktop = True


if __name__ == '__main__':
    unittest.main()
