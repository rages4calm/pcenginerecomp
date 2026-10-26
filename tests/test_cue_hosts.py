"""Authored CUE data reaches guest RAM through the real paused TCP hosts.

The program issues READ(6), acknowledges all 2048 bytes, consumes status and
message, and records completion itself. Tests never write guest RAM via TCP.
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
MPR = [255, 248, 128, 129, 130, 131, 132, 0]


def read_program(lba=1):
    """Authored fixed-mapping program; suitable for direct CFG translation."""
    code, labels, branches = bytearray(), {}, []

    def put(*values):
        code.extend(values)

    def branch(op, label):
        put(op, 0)
        branches.append((len(code)-1, label))

    def wait_req(label):
        labels[label] = len(code)
        put(0xAD, 0, 0x18, 0x29, 0x40)  # LDA status; AND #REQ
        branch(0xF0, label)

    def ack():
        put(0xA9, 0x80, 0x8D, 2, 0x18, 0xA9, 0, 0x8D, 2, 0x18)

    put(0x78, 0xD4, 0xD8)  # SEI; CSH; CLD
    put(0xA9, 0, 0x8D, 0x10, 0x20, 0x8D, 0x11, 0x20, 0x8D, 0x12, 0x20)
    put(0x85, 0x20, 0xA9, 0x24, 0x85, 0x21)  # buffer pointer $2400
    put(0xA9, 0, 0x8D, 2, 0x18, 0x8D, 0, 0x18)
    for index, value in enumerate((8, (lba >> 16) & 31, (lba >> 8) & 255, lba & 255, 1, 0)):
        wait_req('cdb'+str(index))
        put(0xA9, value, 0x8D, 1, 0x18)
        ack()
    put(0xA2, 8, 0xA0, 0)
    wait_req('read')
    put(0xAD, 1, 0x18, 0x91, 0x20)  # sample byte; STA ($20),Y
    ack()
    put(0xC8)
    branch(0xD0, 'read')
    put(0xE6, 0x21, 0xCA)
    branch(0xD0, 'read')
    for index in range(2):
        wait_req('completion'+str(index))
        put(0xAD, 1, 0x18, 0x8D, 0x10+index, 0x20)
        ack()
    labels['free'] = len(code)
    put(0xAD, 0, 0x18)
    branch(0xD0, 'free')
    put(0xA9, 0xA5, 0x8D, 0x12, 0x20)
    labels['done'] = len(code)
    branch(0x80, 'done')
    for operand, label in branches:
        offset = labels[label]-(operand+1)
        if not -128 <= offset <= 127:
            raise ValueError('Authored branch exceeds relative range')
        code[operand] = offset & 255
    return bytes(code)


def sector_pattern(lba):
    return bytes((lba*31+offset*13+(offset >> 8)*19+0x27) & 255 for offset in range(2048))


def create_media(root, raw=False, postgap=False):
    data = bytearray()
    for lba in range(3):
        payload = sector_pattern(lba)
        if raw:
            payload = b'\0'+b'\xff'*10+b'\0'+bytes((0, 2, lba, 1))+payload+bytes(288)
        data.extend(payload)
    (root/'authored data.bin').write_bytes(data)
    # Independent audio samples distinguish signedness and little endian.
    audio = b''.join(value.to_bytes(2, 'little', signed=True)
                     for value in (0, 1, -1, 32767, -32768, 0x1234)*196)
    (root/'authored audio.bin').write_bytes(audio*2)
    cue = root/'authored.cue'
    extra = (f' POSTGAP 00:00:02\n TRACK 02 MODE1/{2352 if raw else 2048}\n INDEX 01 00:00:01\n'
             if postgap else '')
    cue.write_text('FILE "authored data.bin" BINARY\n'
                   f' TRACK 01 MODE1/{2352 if raw else 2048}\n INDEX 01 00:00:00\n'+extra+
                   f'FILE "authored audio.bin" BINARY\n TRACK {3 if postgap else 2:02} AUDIO\n'
                   ' PREGAP 00:00:02\n INDEX 01 00:00:00\n', encoding='utf-8')
    return cue


class CueHostChecks:
    desktop = False
    native = False
    raw_cases = (False, True)
    postgap = False

    def test_complete_read_through_tcp_without_memory_edits(self):
        self.executions = []
        for raw in self.raw_cases:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                cue = create_media(root, raw, self.postgap)
                payload = root/'program.bin'
                # POSTGAP shifts the second data track to disc LBA3 while
                # retaining its original FILE-relative frame1 payload.
                payload.write_bytes(read_program(3 if self.postgap else 1))
                before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
                command = [str(self.binary), str(payload), str(0x100000), str(0x4000),
                           ','.join(map(str, MPR)), '10000000', '30000000', 'native' if self.native else 'hybrid',
                           '--disc', str(cue), '--video-output', 'continuous',
                           '--audio-output', 'off', '--dev-port', '0', '--dev-start-paused', 'on',
                           '--wall-seconds', '15']
                if self.desktop:
                    command += ['--hidden', 'on', '--unthrottled', 'on', '--window-scale', '1']
                environment = os.environ.copy()
                environment.update(SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software', SDL_AUDIODRIVER='dummy')
                process = subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    line = process.stderr.readline()
                    self.assertTrue(line.startswith('PCE_DEV_PORT='), line)
                    with DevClient(int(line.strip().split('=')[1]), timeout=10) as client:
                        initial = client.call('status')
                        self.assertEqual((initial['ticks'], initial['frame'], initial['paused']), (0, 0, True))
                        self.assertEqual(client.read_memory(0x1F0010, 3), bytes(3))
                        client.call('set_input', port=0, mask=8)
                        final = client.advance(25)
                        self.assertEqual((final['frame'], final['paused']), (25, True))
                        self.assertEqual(final['host']['buttons'][0], 8)
                        self.assertEqual(client.read_memory(0x1F0010, 3), b'\0\0\xa5')
                        actual = b''.join(client.read_memory(0x1F0400+offset, 256)
                                          for offset in range(0, 2048, 256))
                        self.assertEqual(actual, sector_pattern(1))
                        metadata, rgb = client.capture()
                        self.assertEqual(metadata['frame'], 25)
                        self.assertEqual(len(rgb), metadata['width']*metadata['height']*3)
                        client.call('set_input', port=0, mask=0)
                        client.advance(1)
                        self.assertEqual(client.call('status')['host']['buttons'][0], 0)
                        client.call('quit')
                    stdout, stderr = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 0, stderr)
                    result = json.loads(stdout)
                    self.assertEqual((result['scsi']['read_commands'], result['scsi']['sectors_read'],
                                      result['scsi']['read_errors']), (1, 1, 0))
                    self.assertEqual(result['scsi']['data_bytes_acked'], 2048)
                    self.assertEqual(result['scsi']['current_lba'], 4 if self.postgap else 2)
                    if self.native:
                        self.assertGreater(result['native_steps'], 0)
                        self.assertEqual((result['interpreter_steps'], result['guard_misses']), (0, 0))
                    else:
                        self.assertGreater(result['interpreter_steps'], 0)
                    self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()})
                    self.executions.append(dict(raw=raw, result=result, inputs_unchanged=True,
                                                ram_payload_sha256=hashlib.sha256(actual).hexdigest(),
                                                capture_sha256=hashlib.sha256(rgb).hexdigest()))
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=5)


@unittest.skipUnless(HEADLESS.is_file(), 'Build headless runner for CUE TCP tests')
class HeadlessCueHosts(CueHostChecks, unittest.TestCase):
    binary = HEADLESS


@unittest.skipUnless(DESKTOP.is_file(), 'Build desktop runner for CUE TCP tests')
class DesktopCueHosts(CueHostChecks, unittest.TestCase):
    binary = DESKTOP
    desktop = True


@unittest.skipUnless(HEADLESS.is_file(), 'Build headless runner for CUE TCP tests')
class HeadlessPostgapCueHosts(CueHostChecks, unittest.TestCase):
    binary = HEADLESS
    postgap = True


@unittest.skipUnless(DESKTOP.is_file(), 'Build desktop runner for CUE TCP tests')
class DesktopPostgapCueHosts(CueHostChecks, unittest.TestCase):
    binary = DESKTOP
    desktop = True
    postgap = True
