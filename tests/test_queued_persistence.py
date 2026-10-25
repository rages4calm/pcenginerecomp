"""Actual native queued-VDC work and isolated guest BRAM persistence.

Every firmware byte and translation input is authored here. The counter layout
is a test contract, not a System Card filesystem or a game save format.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import project
from pcerecomp.capture import load_capture
from pcerecomp.emitter import emit_capture
from pcerecomp.isa import physical

ROOT = Path(__file__).resolve().parent.parent
COMPILER = shutil.which('clang++') or shutil.which('g++')


def prepare(directory):
    """Emit a real program: one blocked VRR read, then a BRAM counter update."""
    directory.mkdir()
    operations = [(0x78,), (0xD4,), (0xA9, 255), (0x53, 1),
                  (0xA9, 248), (0x53, 2), (0xA9, 247), (0x53, 8),
                  (0xA9, 0x80), (0x8D, 7, 0x18)]
    def reg(index, value):
        operations.extend(((3,index), (0x13,value&255), (0x23,value>>8)))
    reg(0, 4)
    reg(2, 0xCAFE)
    reg(1, 4)
    reg(16, 4)
    reg(17, 0x100)
    reg(18, 127)  # A genuine 128-word DMA blocks the CPU VRAM read.
    reg(1, 0x100)
    operations += [(3,2), (0xAD,0,0), (0x8D,2,0x60),
                   (0xAD,2,0), (0x8D,1,0x60),
                   (0xAD,3,0), (0x8D,0xFF,0x67), (0xA8,),
                   (0xEE,0,0x60), (0xAD,0,0x60), (0xAA,),
                   (0xAD,3,0x18), (0xAD,1,0x60), (0x80,0xFE)]
    raw = bytearray(262144)
    raw[0x1FFE:0x2000] = b'\x00\xE1'
    mpr, pc, observations = [0]*8, 0xE100, []
    for data in operations:
        addresses = [physical(pc+i, mpr) for i in range(len(data))]
        for address, byte in zip(addresses, data):
            raw[address] = byte
        observations.append(dict(pc=pc, mpr=list(mpr), physical=addresses,
                                 data=list(data), native_hits=0, interpreted_hits=1))
        if data[0] == 0x53:
            page = {1:0, 2:1, 8:3}[data[1]]
            mpr[page] = {0:255, 1:248, 3:247}[page]
        pc += len(data)
    card = directory/'authored-card.pce'
    card.write_bytes(raw)
    authored = dict(schema=1, runtime_abi=project.ABI, capacity=128, complete=True,
                    dropped_instructions=0, unreadable_instructions=0,
                    retired_instructions=len(observations), observations=observations)
    manifest = emit_capture(authored, directory/'module', single_unit=True)
    identity = project.source_identity(ROOT)
    if identity['revision'] is None:
        raise ValueError('Consumer test requires a committed toolkit checkout')
    descriptor = directory/'project.toml'
    descriptor.write_text(f'''schema = 1
name = "authored-queued-bram-counter"
[tool]
path = {json.dumps(ROOT.as_posix())}
revision = "{identity['revision']}"
source_sha256 = "{identity['source_sha256']}"
runtime_abi = {project.ABI}
[module.source]
path = "module/module.cpp"
sha256 = "{project.sha256(directory/'module/module.cpp')}"
[module.manifest]
path = "module/module.json"
sha256 = "{project.sha256(directory/'module/module.json')}"
[boot]
mode = "system-card-reset"
profile = "standard"
[bios]
path = "authored-card.pce"
sha256 = "{project.sha256(card)}"
[runtime]
tier = "native"
video = "continuous"
vdc_access = "queued"
cd_unknown_status = "fault"
joypad = 2
region = "usa"
multitap = "off"
audio = "off"
[limits]
steps = 200
ticks = 100000
wall_seconds = 5
''', encoding='utf-8')
    return descriptor, manifest


def isolated_environment():
    environment = dict(os.environ)
    if os.name == 'nt':
        system = Path(os.environ['SystemRoot'])
        environment['PATH'] = os.pathsep.join((str(system), str(system/'System32'),
                                              str(Path(shutil.which('git')).parent)))
    return environment


@unittest.skipUnless(shutil.which('cmake') and shutil.which('ninja') and
                     shutil.which('git') and COMPILER,
                     'CMake/Ninja/Git/C++ compiler required for actual native consumer')
class QueuedPersistenceTests(unittest.TestCase):
    def test_native_dma_waits_survive_two_save_sessions_and_a_volatile_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            descriptor, manifest = prepare(root/'project')
            self.assertFalse(manifest['execution_evidence'])
            self.assertFalse(manifest['excluded_observations'])
            self.assertFalse(manifest['unsupported_observations'])
            source = (descriptor.parent/'module/module.cpp').read_text(encoding='utf-8')
            self.assertIn('bus.write_vdc(s,', source)
            self.assertIn('bus.read(s,', source)
            self.assertNotIn('interpret_step(', source)
            self.assertNotIn('interpret_block(', source)
            build = root/'build'
            built = project.build(descriptor, build, generator='Ninja',
                                  cmake_args=(f'-DCMAKE_CXX_COMPILER={COMPILER}',))
            savedir = root/'isolated saves'
            savedir.mkdir()
            contract = hashlib.sha256(b'authored-queued-bram-v1: counter0, vrr1, busy2, high2047').hexdigest()
            envelope = savedir/'counter.bram.json'
            previous = None
            firmware = (descriptor.parent/'authored-card.pce').read_bytes()
            for counter in (1, 2):
                receipt_path = root/f'run-{counter}.json'
                capture_path = root/f'actual-native-{counter}.json'
                with patch.dict(os.environ, isolated_environment(), clear=True):
                    result = project.run(descriptor, build, receipt_path,
                        save_root=savedir, save_namespace='counter', save_contract=contract,
                        code_capture=capture_path, capture_limit=128)
                self.assertTrue(result['qualified'], result)
                self.assertEqual(result['boot_validation'], {'valid': True})
                self.assertEqual(result['vdc_access_validation'], {'valid': True})
                state = result['result']
                self.assertEqual((state['a'], state['x'], state['y']), (255, counter, 0xCA))
                self.assertEqual((state['native_steps'], state['interpreter_steps'], state['guard_misses']),
                                 (200, 0, 0))
                self.assertEqual(state['vdc_access']['profile'], 'queued')
                self.assertGreater(state['vdc_access']['wait_ticks'], 0)
                self.assertEqual(state['vdc_access']['wait_ticks'] % 3, 0)
                self.assertFalse(state['cd_control']['bram_unlocked'])
                self.assertEqual(state['vdc']['dma_words'], 128)
                self.assertEqual(state['vdc']['mawr'], 5)
                session = result['bram_session']
                self.assertTrue(session['committed'])
                self.assertEqual(session['seeded'], counter == 2)
                self.assertEqual(session['previous_payload_sha256'], previous)
                expected = bytearray(2048)
                expected[0], expected[1], expected[2], expected[-1] = counter, 0xFE, 0x40, 0xCA
                stored = json.loads(envelope.read_text(encoding='utf-8'))
                payload = base64.b64decode(stored['payload_base64'], validate=True)
                self.assertEqual(payload, expected)
                previous = hashlib.sha256(expected).hexdigest()
                self.assertEqual(stored['payload_sha256'], previous)
                self.assertEqual(session['payload_sha256'], previous)
                capture, _ = load_capture(capture_path)
                self.assertEqual(capture['runtime_abi'], project.ABI)
                self.assertTrue(capture['complete'])
                self.assertEqual(capture['dropped_instructions'], 0)
                self.assertEqual(capture['unreadable_instructions'], 0)
                self.assertEqual(sum(row['native_hits'] for row in capture['observations']), 200)
                self.assertEqual(sum(row['interpreted_hits'] for row in capture['observations']), 0)
                self.assertEqual((descriptor.parent/'authored-card.pce').read_bytes(), firmware)
            preserved = envelope.read_bytes()
            with patch.dict(os.environ, isolated_environment(), clear=True):
                volatile = project.run(descriptor, build, root/'volatile.json')
            self.assertTrue(volatile['qualified'], volatile)
            self.assertNotIn('bram_session', volatile)
            self.assertEqual((volatile['result']['native_steps'],
                              volatile['result']['interpreter_steps'],
                              volatile['result']['guard_misses']), (200, 0, 0))
            self.assertEqual(volatile['result']['vdc']['dma_words'], 128)
            self.assertEqual((volatile['result']['a'], volatile['result']['x'], volatile['result']['y']),
                             (255, 1, 0xCA))
            self.assertGreater(volatile['result']['vdc_access']['wait_ticks'], 0)
            self.assertEqual(envelope.read_bytes(), preserved)
            self.assertEqual({p.name for p in savedir.iterdir()}, {'counter.bram.json','counter.lock'})
            for name, digest in built['output_files'].items():
                self.assertEqual(project.sha256(Path(built['binary']).parent/name), digest)


if __name__ == '__main__':
    unittest.main()
