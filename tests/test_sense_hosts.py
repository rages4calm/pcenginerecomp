"""Authored guest CD sense commands through actual headless and SDL hosts.

No retail BIOS/disc, source patches, save files or RAM edits. Guest code handles
selection, CDBs, DATA IN auto-ACK, manual status/message ACK and warm reset.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.dev_client import DevClient
from test_reset_boot import authored_card

ROOT = Path(__file__).resolve().parent.parent
EXE = '.exe' if os.name == 'nt' else ''
HEADLESS = Path(os.environ.get('PCE_TEST_HEADLESS', ROOT/'build'/('pce-headless'+EXE)))
DESKTOP = Path(os.environ.get('PCE_TEST_DESKTOP', 'disabled'))


def firmware():
    code = bytearray(bytes.fromhex('78 A9 FF 53 01 A9 F8 53 02'))
    def emit(*values):
        code.extend(values)
    def req():
        emit(0xAD, 0, 0x18, 0x29, 0x40, 0xF0, 0xF9)
    def ack():
        emit(0xA9, 0x80, 0x8D, 2, 0x18, 0x9C, 2, 0x18)
    def store(offset):
        emit(0x8D, offset, 0x20)
    def command(values):
        emit(0x9C, 0, 0x18)
        for value in values:
            req()
            emit(0xA9, value, 0x8D, 1, 0x18)
            ack()
    def finish(offset):
        for index in (offset, offset+1):
            req()
            emit(0xAD, 1, 0x18)
            store(index)
            ack()
        emit(0xAD, 0, 0x18, 0x29, 0x80, 0xD0, 0xF9)
    def sense(allocation, offset):
        command((3, 0, 0, 0, allocation, 0))
        for index in range(18):
            req()
            emit(0xAD, 8, 0x18)
            store(offset+index)
        finish(offset+18)
    sense(18, 0)
    command((0xDE, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    finish(0x20)
    # Warm SCSI reset must not erase the pending NEC sense context.
    emit(0xA9, 2, 0x8D, 4, 0x18, 0x9C, 4, 0x18)
    sense(0, 0x40)
    sense(255, 0x60)
    emit(0xA9, 0xA5)
    store(0x7F)
    emit(0x80, 0xFE)
    return authored_card(bytes(code))


class SenseHostChecks:
    desktop = False

    def test_guest_recovers_sense_across_warm_reset_and_inspects_without_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bios = root/'authored.pce'
            raw = firmware()
            bios.write_bytes(raw)
            command = [str(self.binary), '--system-card-reset', 'super', str(bios),
                       '1000000', '100000000', 'hybrid', '--video-output', 'continuous',
                       '--dev-port', '0', '--dev-start-paused', 'on', '--wall-seconds', '20']
            if self.desktop:
                command += ['--hidden', 'on', '--unthrottled', 'on', '--window-scale', '1']
            environment = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software', SDL_AUDIODRIVER='dummy')
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, env=environment)
            client = None
            try:
                port_line = child.stderr.readline()
                self.assertTrue(port_line.startswith('PCE_DEV_PORT='), port_line)
                client = DevClient(int(port_line.split('=', 1)[1]), timeout=10)
                self.assertNotIn('cd_sense', client.call('status')['host'])
                client.advance(3)
                before = client.call('status')
                ram = client.read_memory(0x1F0000, 128)
                after = client.call('status')
                self.assertEqual({k:v for k,v in before.items() if k != 'id'},
                                 {k:v for k,v in after.items() if k != 'id'})
                empty = bytearray(18)
                empty[0], empty[7] = 0x70, 0x0A
                error = bytearray(empty)
                error[2], error[12] = 2, 0x0B
                self.assertEqual(ram[:20], bytes(empty)+b'\0\0')
                self.assertEqual(ram[0x20:0x22], b'\2\2')
                self.assertEqual(ram[0x40:0x54], bytes(error)+b'\0\0')
                self.assertEqual(ram[0x60:0x74], bytes(empty)+b'\0\0')
                self.assertEqual(ram[0x7F], 0xA5)
                expected = dict(commands=3, errors=1,
                                pending=dict(key=0, asc=0, ascq=0, fru=0, failed_lba=None))
                self.assertEqual(after['host']['cd_sense'], expected)
                self.assertEqual(after['host']['debug_memory']['write_requests'], 0)
                client.call('quit')
                stdout, stderr = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, stderr)
                final = json.loads(stdout)
                self.assertEqual(final['stop'], 'dev_quit')
                self.assertEqual(final['cd_sense'], expected)
                self.assertEqual(final['native_steps'], 0)
                self.assertGreater(final['interpreter_steps'], 0)
                self.assertEqual(bios.read_bytes(), raw)
            finally:
                if client is not None:
                    client.close()
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.communicate(timeout=5)


@unittest.skipUnless(HEADLESS.is_file(), 'Build headless for CD sense host tests')
class HeadlessSenseTests(SenseHostChecks, unittest.TestCase):
    binary = HEADLESS


@unittest.skipUnless(DESKTOP.is_file(), 'Build desktop for CD sense host tests')
class DesktopSenseTests(SenseHostChecks, unittest.TestCase):
    binary = DESKTOP
    desktop = True
