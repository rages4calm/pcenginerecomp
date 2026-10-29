"""Authored live SDL wire evidence and paused PCM checkpoint continuation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from test_dev_server_cli import DESKTOP
from scripts.dev_client import DevClient
from scripts.dev_journal_audit import audit_wire_journal
from scripts.dev_observation import ObservationError, validate_paused_observation


def authored_program():
    # Blue backdrop, then repeated TII $4000->$2200,4096 and BRA back to TII.
    # The block spans a host poll/frame boundary, leaving actual pending PCM.
    # WRAM $2200..$31FF does not overlap the CPU stack at $2100..$21FF.
    prefix = bytes([0xA9, 7, 0x8D, 4, 4, 0xA9, 0, 0x8D, 5, 4,
                    3, 5, 0x13, 0x80, 0x23, 0])
    program = prefix + bytes([0x73, 0, 0x40, 0, 0x22, 0, 0x10, 0x80, 0xF7])
    return program + bytes(4096 - len(program))


def wire_records(path):
    pairs = []
    pending = None
    def visit(event):
        nonlocal pending
        if event.event == 'request':
            pending = json.loads(event.wire)
        elif event.event == 'response':
            if event.protocol_error is not None:
                raise AssertionError('invalid live protocol reply')
            pairs.append((pending, json.loads(event.wire)))
            pending = None
    summary = audit_wire_journal(path, visit=visit)
    if (summary['ending'] != 'paired-frames' or summary['failure_records']
            or summary['unanswered_intents'] or summary['forensic_prefix']):
        raise AssertionError('unexpected live transport failure or missing reply')
    # Actual process exit, image/state predicates and checkpoint bytes are
    # checked separately; paired raw frames alone cannot prove them.
    return pairs


def checkpoint_core(path):
    """Independently parse the schema-1 host envelope, retaining all core bytes."""
    data = path.read_bytes()
    offset = 0

    def take(size):
        nonlocal offset
        result = data[offset:offset + size]
        if len(result) != size:
            raise AssertionError('truncated authored checkpoint')
        offset += size
        return result

    def integer(size):
        return int.from_bytes(take(size), 'little')

    def digest():
        if integer(4) != 64:
            raise AssertionError('checkpoint digest extent differs')
        result = take(64).decode('ascii')
        if any(char not in '0123456789abcdef' for char in result):
            raise AssertionError('checkpoint digest is not hex')
        return result

    if take(8) != b'PCEDEVCP' or integer(4) != 1:
        raise AssertionError('checkpoint envelope schema differs')
    abi = integer(4)
    identity, body_digest = digest(), digest()
    body = take(integer(8))
    if offset != len(data) or hashlib.sha256(body).hexdigest() != body_digest:
        raise AssertionError('checkpoint body digest/extent differs')
    # Five scripted/remote u16 masks each, then five u64 host cursors/counters.
    core = body[60:]
    if core[:8] != b'PCECORE\0' or int.from_bytes(core[8:12], 'little') != 1:
        raise AssertionError('checkpoint core schema differs')
    return abi, identity, core


class LiveAudioSandbox:
    """A single owned hidden host; source, input recipe and binary stay fixed."""
    def __init__(self, binary, root, name):
        self.directory = root / name
        self.directory.mkdir()
        self.journal = self.directory / 'wire.jsonl'
        self.stdout = self.directory / 'stdout.json'
        self.stderr = self.directory / 'stderr.txt'
        self.client = None
        self.command = [str(binary), str(root / 'authored.bin'), '0x100000', '0x4000',
                        '255,248,128,129,130,131,132,0', '500000000', '3000000000',
                        'hybrid', '--dev-port', '0', '--dev-start-paused', 'on',
                        '--wall-seconds', '20', '--hidden', 'on', '--unthrottled', 'on',
                        '--window-scale', '1', '--audio-output', 'on',
                        '--audio-profile', 'raw', '--audio-rate', '44100',
                        '--audio-timing', 'gear', '--checkpoint-dir', str(root / 'checkpoints'),
                        '--checkpoint-context', 'b' * 64]
        environment = os.environ.copy()
        environment.update(SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software',
                           SDL_AUDIODRIVER='dummy')
        with self.stdout.open('xb') as output, self.stderr.open('xb') as errors:
            self.process = subprocess.Popen(self.command, stdin=subprocess.DEVNULL,
                                            stdout=output, stderr=errors, env=environment,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                lines = self.stderr.read_text().splitlines()
                ports = [line for line in lines if line.startswith('PCE_DEV_PORT=')]
                if ports:
                    self.port = int(ports[0].split('=', 1)[1])
                    self.client = DevClient(self.port, timeout=8, journal=self.journal)
                    break
                if self.process.poll() is not None:
                    raise AssertionError('authored SDL host exited before TCP: ' + self.stderr.read_text())
                time.sleep(.005)
            else:
                raise AssertionError('authored SDL listener deadline exceeded')
        except BaseException:
            self.close()
            raise

    def finish(self, test):
        self.client.call('quit')
        self.client.close()
        self.client = None
        test.assertEqual(self.process.wait(timeout=5), 0, self.stderr.read_text())
        test.assertEqual(self.stderr.read_text().strip(), f'PCE_DEV_PORT={self.port}')
        result = json.loads(self.stdout.read_text())
        test.assertEqual(result['stop'], 'dev_quit')
        return result

    def close(self):
        if self.client is not None:
            try:
                self.client.call('quit')
            except (OSError, RuntimeError):
                # Cleanup must still reap this owned process if its client or
                # journal has already failed. Successful paths use finish().
                pass
            finally:
                self.client.close()
                self.client = None
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)


def observe(test, app, image):
    before = app.client.call('status')
    test.assertEqual(app.client.read_memory(0x1F0200, 16), image[:16])
    cpu = before['host']['cpu']
    physical = cpu['instruction_physical']
    test.assertEqual(cpu['mpr'], [255, 248, 128, 129, 130, 131, 132, 0])
    test.assertEqual(physical, [((cpu['mpr'][((before['host']['pc'] + i) & 65535) >> 13] << 13)
                               | ((before['host']['pc'] + i) & 8191)) for i in range(7)])
    test.assertEqual(app.client.read_memory(physical[0], 7), bytes(cpu['instruction_bytes']))
    metadata, rgb = app.client.capture('guest')
    test.assertEqual((metadata['width'], metadata['height'], metadata['frame']),
                     (256, 240, before['frame']))
    test.assertEqual(rgb, bytes([0, 0, 255]) * (256 * 240))
    after = app.client.call('status')
    # Both actual replies already exist on disk before the higher-level policy.
    pairs = wire_records(app.journal)
    test.assertEqual(next(response for _, response in pairs if response['id'] == before['id']), before)
    test.assertEqual(pairs[-1][1], after)
    proof = validate_paused_observation(before, after)
    test.assertEqual(proof['changed_paths'], [])
    test.assertIsNone(proof['presentation'])
    return after


def exercise_live_observation(test, binary, root):
    image = authored_program()
    (root / 'authored.bin').write_bytes(image)
    (root / 'checkpoints').mkdir()
    app = LiveAudioSandbox(binary, root, 'writer')
    try:
        initial = app.client.call('status')
        test.assertEqual((initial['frame'], initial['ticks']), (0, 0))
        app.client.advance(2)
        frontier = observe(test, app, image)
        audio = frontier['host']['audio_output']
        test.assertEqual(audio['discarded_frames'], 0)
        pending = audio['frames'] - audio['host']['submitted_frames']
        test.assertGreater(pending, 0)
        test.assertLessEqual(pending, 8192)
        test.assertEqual(audio['host']['submitted_frames'], audio['host']['dropped_frames'])
        test.assertEqual((audio['host']['queued_frames'], audio['wav_frames']), (0, 0))
        # Deliberately compare two different execution epochs. Failure belongs
        # to the observation policy, and cannot discard the actual AFTER wire.
        retained = app.journal.read_bytes()
        with test.assertRaises(ObservationError):
            validate_paused_observation(initial, frontier)
        test.assertEqual(app.journal.read_bytes(), retained)
        test.assertEqual(wire_records(app.journal)[-1][1], frontier)
        saved = app.client.call('save_checkpoint', name='frontier.pcec')['checkpoint']
        test.assertEqual(saved['pending_pcm_frames'], pending)
        test.assertEqual(saved['ticks'], frontier['ticks'])
        app.client.advance(1)
        endpoint = observe(test, app, image)
        end_saved = app.client.call('save_checkpoint', name='writer-end.pcec')['checkpoint']
        writer_final = app.finish(test)
    finally:
        app.close()

    app = LiveAudioSandbox(binary, root, 'restorer')
    try:
        loaded = app.client.call('load_checkpoint', name='frontier.pcec')['checkpoint']
        test.assertEqual(loaded, saved)
        restored = observe(test, app, image)
        origin = restored['host']['checkpoint']
        test.assertEqual(origin['audio_origin'], {'pending_pcm_frames': pending, 'source_wav_frames': 0})
        test.assertEqual(origin['window'], {'ticks': 0, 'native_steps': 0, 'interpreter_steps': 0})
        test.assertEqual(origin['origin']['sha256'], saved['sha256'])
        test.assertEqual(restored['ticks'], frontier['ticks'])
        for key in ('frames', 'pcm_hash', 'psg_nonzero', 'adpcm_nonzero', 'cdda_nonzero'):
            test.assertEqual(restored['host']['audio_output'][key], audio[key])
        # Fresh SDL submission counters are local; generated frames include
        # imported work and must not be subtracted as if this were a reset run.
        test.assertEqual(restored['host']['audio_output']['host']['submitted_frames'], 0)
        roundtrip = app.client.call('save_checkpoint', name='roundtrip.pcec')['checkpoint']
        test.assertEqual(roundtrip, saved)
        test.assertEqual((root / 'checkpoints/frontier.pcec').read_bytes(),
                         (root / 'checkpoints/roundtrip.pcec').read_bytes())
        test.assertEqual(checkpoint_core(root / 'checkpoints/frontier.pcec'),
                         checkpoint_core(root / 'checkpoints/roundtrip.pcec'))
        app.client.advance(1)
        restored_endpoint = observe(test, app, image)
        continued = app.client.call('save_checkpoint', name='restored-end.pcec')['checkpoint']
        test.assertEqual(continued, end_saved)
        test.assertEqual((root / 'checkpoints/writer-end.pcec').read_bytes(),
                         (root / 'checkpoints/restored-end.pcec').read_bytes())
        test.assertEqual(checkpoint_core(root / 'checkpoints/writer-end.pcec'),
                         checkpoint_core(root / 'checkpoints/restored-end.pcec'))
        test.assertGreater(restored_endpoint['host']['checkpoint']['window']['interpreter_steps'], 0)
        test.assertEqual(restored_endpoint['ticks'], endpoint['ticks'])
        restorer_final = app.finish(test)
    finally:
        app.close()

    commands = []
    for name in ('writer', 'restorer'):
        pairs = wire_records(root / name / 'wire.jsonl')
        commands.extend(request['cmd'] for request, _ in pairs)
        test.assertTrue(all(response['ok'] is True for _, response in pairs))
    for command in ('status', 'step_frames', 'read_memory', 'screenshot',
                    'save_checkpoint', 'load_checkpoint', 'quit'):
        test.assertIn(command, commands)
    return {'result': 'pass', 'pending_pcm_frames': pending,
            'strict_paused_pairs': 4, 'fresh_restoring_processes': 1,
            'wire_requests': len(commands), 'wire_commands': sorted(set(commands)),
            'roundtrip_complete_file_bytes_equal': True,
            'continued_complete_file_bytes_equal': True,
            'frontier': saved, 'endpoint': end_saved,
            'writer_final': writer_final, 'restorer_final': restorer_final}


@unittest.skipUnless(DESKTOP.is_file(), 'Build the optional desktop runner')
class LivePausedObservationTests(unittest.TestCase):
    def test_live_wire_evidence_pending_pcm_and_fresh_checkpoint(self):
        evidence = os.environ.get('PCE_TEST_OBSERVATION_EVIDENCE')
        if evidence:
            root = Path(evidence)
            source = Path(__file__).resolve().parents[1]
            self.assertTrue(root.is_absolute())
            self.assertTrue(root.resolve().is_relative_to(source / '.local'))
            root.mkdir(parents=True)  # Existing evidence must never be replaced.
            result = exercise_live_observation(self, DESKTOP, root)
            from scripts import dev_client, dev_journal, dev_journal_audit, dev_observation
            bound = [Path(__file__).resolve(), Path(dev_client.__file__),
                     Path(dev_journal.__file__), Path(dev_journal_audit.__file__), Path(dev_observation.__file__),
                     DESKTOP.resolve(), *sorted(root.rglob('*'))]
            dll = DESKTOP.resolve().with_name('SDL3.dll')
            if dll.is_file():
                bound.append(dll)
            result['bindings'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in bound if p.is_file()}
            (root / 'qualification.json').write_text(json.dumps(result, indent=2) + '\n')
        else:
            with tempfile.TemporaryDirectory() as temporary:
                exercise_live_observation(self, DESKTOP, Path(temporary))


if __name__ == '__main__':
    unittest.main()
