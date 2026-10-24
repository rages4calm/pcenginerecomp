"""Authored System Card images exercise the real CLI, reset vector and TCP host.

No firmware excerpts, formatted BRAM, saved guest state or retail inputs are used.
Reset expectations follow the documented Gear deterministic power-on profile;
the independent reset oracle qualifies that profile separately.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from pcerecomp.capture import load_capture
from scripts.dev_client import DevClient, DevError

ROOT = Path(__file__).resolve().parent.parent
EXE = '.exe' if os.name == 'nt' else ''
HEADLESS = Path(os.environ.get('PCE_TEST_HEADLESS', ROOT/'build'/('pce-headless'+EXE)))
DESKTOP = Path(os.environ.get('PCE_TEST_DESKTOP', 'disabled'))


def authored_card(program=b'\xea', pc=0xE100):
    # Distinguish each of the 32 ROM banks; hardware mirrors this 256 KiB
    # cartridge below $100000, except where Super System Card RAM overlays it.
    rom = bytearray(b''.join(bytes([bank])*8192 for bank in range(32)))
    offset = pc & 8191
    rom[offset:offset+len(program)] = program
    rom[0x1FFE:0x2000] = pc.to_bytes(2, 'little')
    return bytes(rom)


class ResetHostChecks:
    desktop = False

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bios = self.root/'authored card.pce'
        self.environment = os.environ.copy()
        self.environment.update(SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software',
                                SDL_AUDIODRIVER='dummy')

    def command(self, profile='standard', steps=1, ticks=10000, tier='hybrid', options=()):
        command = [str(self.binary), '--system-card-reset', profile, str(self.bios),
                   str(steps), str(ticks), tier, *options]
        if self.desktop:
            command += ['--hidden', 'on', '--unthrottled', 'on', '--window-scale', '1']
        return command

    def invoke(self, program=b'\xea', **arguments):
        raw = authored_card(program)
        self.bios.write_bytes(raw)
        result = subprocess.run(self.command(**arguments), env=self.environment,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(self.bios.read_bytes(), raw)
        return result

    def state(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def expected_boot(self, profile='standard', bram='blank-unformatted'):
        return dict(mode='system-card-reset', profile=profile,
                    initialization='gear-deterministic-zero-v1', vector_physical=8190,
                    pc=0xE100, a=0, x=0, y=0, sp=0, p=4,
                    clock_divisor=12, ticks=0, cycles=0, mpr=[0]*8, bram=bram)

    def test_vector_first_instruction_and_reset_metadata_are_distinct(self):
        for profile in ('standard', 'super'):
            with self.subTest(profile=profile):
                state = self.state(self.invoke(profile=profile))
                self.assertEqual(state['boot'], self.expected_boot(profile))
                self.assertEqual((state['pc'], state['ticks'], state['cycles']),
                                 (0xE101, 24, 2))
                self.assertEqual((state['a'], state['x'], state['y'], state['sp'], state['p']),
                                 (0, 0, 0, 0, 4))
                self.assertEqual(state['mpr'], [0]*8)
                self.assertEqual((state['native_steps'], state['interpreter_steps']), (0, 1))

    def test_guest_sets_its_own_io_and_work_ram_mappings(self):
        # LDA #FF; TAM #1; LDA #F8; TAM #2; LDA #37; STA $2000; LDA $2000.
        program = bytes([0xA9, 0xFF, 0x53, 1, 0xA9, 0xF8, 0x53, 2,
                         0xA9, 0x37, 0x8D, 0, 0x20, 0xAD, 0, 0x20])
        state = self.state(self.invoke(program, steps=7))
        self.assertEqual(state['a'], 0x37)
        self.assertEqual(state['mpr'], [255, 248, 0, 0, 0, 0, 0, 0])
        self.assertEqual(state['boot'], self.expected_boot())

    def test_vector_contents_choose_the_initial_logical_pc(self):
        # A different authored vector rules out a hard-coded IPL entry point.
        raw = authored_card(bytes([0xA9, 0xC5]), pc=0xE6B2)
        self.bios.write_bytes(raw)
        result = subprocess.run(self.command(), env=self.environment,
                                capture_output=True, text=True, timeout=10)
        state = self.state(result)
        expected = self.expected_boot()
        expected['pc'] = 0xE6B2
        self.assertEqual(state['boot'], expected)
        self.assertEqual((state['pc'], state['a']), (0xE6B4, 0xC5))
        self.assertEqual(self.bios.read_bytes(), raw)

    def test_standard_rom_and_super_ram_overlay_are_different(self):
        # Bank 68 is mirrored ROM bank 08 on Standard, independently writable
        # zeroed RAM on Super. Adjacent bank 69 must not alias bank 68 RAM.
        program = bytes([0xA9, 0x68, 0x53, 4, 0xA9, 0x37, 0x8D, 0, 0x40,
                         0xAD, 0, 0x40, 0xAA, 0xA9, 0x69, 0x53, 4, 0xAD, 0, 0x40])
        for profile, expected in (('standard', (8, 9)), ('super', (0x37, 0))):
            with self.subTest(profile=profile):
                state = self.state(self.invoke(program, profile=profile, steps=9))
                self.assertEqual((state['x'], state['a']), expected)

    def test_system_card_identification_reads_use_selected_profile(self):
        program = bytes([0xA9, 0xFF, 0x53, 1, 0xAD, 0xC1, 0x18, 0xAA,
                         0xAD, 0xC3, 0x18])
        for profile, expected in (('standard', (255, 255)), ('super', (0xAA, 3))):
            with self.subTest(profile=profile):
                state = self.state(self.invoke(program, profile=profile, steps=5))
                self.assertEqual((state['x'], state['a']), expected)

    def test_guest_rom_write_is_ignored_without_mutating_source(self):
        program = bytes([0xA9, 0x7B, 0x8D, 0, 0xE1, 0xAD, 0, 0xE1])
        state = self.state(self.invoke(program, steps=3))
        self.assertEqual(state['a'], 0xA9)
        # The old sandbox remains intentionally strict about ROM writes.
        payload = self.root/'sandbox.bin'
        payload.write_bytes(program)
        args = [str(self.binary), str(payload), '0x100000', '0x4000',
                '255,248,128,129,130,131,132,0', '3', '10000', 'hybrid',
                '--bios', str(self.bios)]
        if self.desktop:
            args += ['--hidden', 'on', '--unthrottled', 'on']
        result = subprocess.run(args, env=self.environment, capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(json.loads(result.stdout)['stop'], 'bus_fault')
        self.assertNotEqual(result.returncode, 0)

    def test_bram_starts_unformatted_and_explicit_image_is_only_a_volatile_seed(self):
        # Read both ends of the 2 KiB BRAM through a guest-selected F7 mapping.
        program = bytes([0xA9, 0xF7, 0x53, 4, 0xAD, 0, 0x40, 0xAA, 0xAD, 0xFF, 0x47])
        blank = self.state(self.invoke(program, steps=5))
        self.assertEqual((blank['x'], blank['a']), (0, 0))
        image = self.root/'unformatted seed.bram'
        raw = bytes((i*37+61) & 255 for i in range(2048))
        image.write_bytes(raw)
        seeded = self.state(self.invoke(program, steps=5, options=['--bram', str(image)]))
        self.assertEqual((seeded['x'], seeded['a']), (raw[0], raw[-1]))
        self.assertEqual(seeded['boot'], self.expected_boot(bram='explicit-image'))
        write = bytes([0xA9, 0xF7, 0x53, 4, 0xA9, 0xC6, 0x8D, 0, 0x40, 0xAD, 0, 0x40])
        changed = self.state(self.invoke(write, steps=5, options=['--bram', str(image)]))
        self.assertEqual(changed['a'], 0xC6)
        self.assertEqual(image.read_bytes(), raw)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ['authored card.pce', 'unformatted seed.bram'])

    def test_code_capture_records_reset_mapping_and_actual_source(self):
        output = self.root/'reset capture.json'
        state = self.state(self.invoke(options=['--code-capture', str(output)]))
        capture, _ = load_capture(output)
        self.assertEqual(capture['retired_instructions'], 1)
        self.assertEqual(capture['observations'], [dict(pc=0xE100, mpr=[0]*8,
                         physical=[0x100], data=[0xEA], native_hits=0, interpreted_hits=1)])
        self.assertEqual(state['boot'], self.expected_boot())

    def test_native_only_guard_miss_does_not_execute_reset_vector(self):
        result = self.invoke(tier='native')
        state = json.loads(result.stdout)
        self.assertEqual((state['ticks'], state['pc']), (0, 0xE100))
        self.assertEqual((state['native_steps'], state['interpreter_steps']), (0, 0))
        self.assertEqual(state['stop'], 'guard_miss')
        self.assertEqual(result.returncode, 3)
        self.assertEqual(state['boot'], self.expected_boot())

    def test_rejects_invalid_profiles_sizes_duplicates_and_snapshot_positionals(self):
        self.bios.write_bytes(authored_card())
        for options in (['--bios', str(self.bios)], ['--system-card-reset', 'super'],
                        ['0x100000', '0x4000'], ['--bram'],
                        ['--dev-port', '0', '--dev-port', '0']):
            with self.subTest(options=options):
                result = subprocess.run(self.command(options=options), env=self.environment,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual((result.returncode, result.stdout), (2, ''))
        for profile in ('standardish', 'arcade', 'supergrafx', ''):
            with self.subTest(profile=profile):
                result = subprocess.run(self.command(profile=profile), env=self.environment,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual((result.returncode, result.stdout), (2, ''))
        for size in (0, 8192, 262143, 262145):
            with self.subTest(size=size):
                self.bios.write_bytes(bytes(size))
                result = subprocess.run(self.command(), env=self.environment,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertEqual(self.bios.stat().st_size, size)

    def test_tcp_initial_reset_is_paused_and_advances_through_ordinary_host_controls(self):
        # Map MMIO and work RAM in guest code, then a normal infinite BRA.
        raw = authored_card(bytes([0xA9, 0xFF, 0x53, 1, 0xA9, 0xF8, 0x53, 2, 0x80, 0xFE]))
        self.bios.write_bytes(raw)
        command = self.command(profile='super', steps=10000000, ticks=10000000,
                               options=['--dev-port', '0', '--dev-start-paused', 'on',
                                        '--dev-memory-write', 'on', '--wall-seconds', '10'])
        process = subprocess.Popen(command, env=self.environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            line = process.stderr.readline()
            self.assertTrue(line.startswith('PCE_DEV_PORT='), line)
            with DevClient(int(line.strip().split('=')[1]), timeout=5) as client:
                before = client.call('status')
                self.assertEqual((before['ticks'], before['frame'], before['paused']), (0, 0, True))
                self.assertEqual(before['host']['boot'], self.expected_boot('super'))
                cpu = before['host']['cpu']
                self.assertEqual([cpu[k] for k in ('a', 'x', 'y', 'sp', 'p')], [0, 0, 0, 0, 4])
                self.assertEqual((cpu['mpr'], cpu['physical_pc']), ([0]*8, 0x100))
                for address in (0x100, 0x40100, 0x80100, 0xC0100):
                    self.assertEqual(client.read_memory(address, 10), raw[0x100:0x10A])
                self.assertEqual(client.read_memory(0xD0000, 16), bytes(16))
                client.write_memory(0xD0000, b'\x56', b'\0')
                self.assertEqual(client.read_memory(0xD0000, 1), b'\x56')
                self.assertEqual(client.read_memory(0xD2000, 1), b'\0')
                with self.assertRaises(DevError):
                    client.write_memory(0x100, b'\0', raw[0x100:0x101])
                with self.assertRaises(DevError):
                    client.capture()
                # Pure source reads and RAM diagnostics must not execute reset code.
                self.assertEqual(client.call('status')['ticks'], 0)
                client.call('set_input', mask=8, port=0)
                advanced = client.advance(2)
                self.assertEqual((advanced['frame'], advanced['paused']), (2, True))
                self.assertEqual(advanced['host']['buttons'][0], 8)
                self.assertEqual(advanced['host']['cpu']['mpr'][:2], [255, 248])
                self.assertEqual(advanced['host']['boot'], self.expected_boot('super'))
                metadata, rgb = client.capture()
                self.assertEqual((metadata['width'], metadata['height'], metadata['frame']), (256, 240, 2))
                self.assertEqual(len(rgb), 256*240*3)
                again = client.call('status')
                self.assertEqual(again['host'], advanced['host'])
                self.assertEqual(again['ticks'], advanced['ticks'])
                client.call('quit')
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            final = json.loads(stdout)
            self.assertEqual(final['stop'], 'dev_quit')
            self.assertEqual(final['boot'], self.expected_boot('super'))
            self.assertEqual(self.bios.read_bytes(), raw)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


@unittest.skipUnless(HEADLESS.is_file(), 'Build the headless runner')
class HeadlessResetBootTests(ResetHostChecks, unittest.TestCase):
    binary = HEADLESS


@unittest.skipUnless(DESKTOP.is_file(), 'Enable PCE_BUILD_DESKTOP')
class DesktopResetBootTests(ResetHostChecks, unittest.TestCase):
    binary = DESKTOP
    desktop = True
