"""Authored observed-code identities and strict offline capture boundaries."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from pcerecomp.capture import load_capture, validate_capture
from pcerecomp.emitter import emit_capture
from pcerecomp.isa import decode
from pcerecomp.cli import main

MPR = [255,248,128,129,130,131,132,0]


def observation(pc=0x4000, raw=(0xa9, 42), mpr=None, native=0, interpreted=1):
    mpr = MPR.copy() if mpr is None else mpr
    ins = decode(lambda address: raw[(address-pc)&65535], pc, tuple(mpr))
    return {'pc': pc, 'mpr': list(mpr), 'physical': list(ins.physical), 'data': list(raw),
            'native_hits': native, 'interpreted_hits': interpreted}


def capture(items=None, capacity=64, dropped=0, unreadable=0):
    items = [observation()] if items is None else items
    return {'schema': 1, 'runtime_abi': 12, 'capacity': capacity,
            'dropped_instructions': dropped, 'unreadable_instructions': unreadable,
            'retired_instructions': dropped+unreadable+sum(i['native_hits']+i['interpreted_hits'] for i in items),
            'complete': not (dropped or unreadable), 'observations': items}


class CaptureTests(unittest.TestCase):
    def test_variants_contexts_overlap_and_wrap_preserved(self):
        second = MPR.copy(); second[3] = 140
        items = [observation(), observation(raw=(0xa9, 43)), observation(mpr=second),
                 observation(0x4001, (0xea,)), observation(0xffff, (0xa9, 29)),
                 observation(0x5fff, (0xad, 0x11, 0x22))]
        decoded = validate_capture(capture(items))
        self.assertEqual(len(decoded), 6)
        self.assertIn((8191, 0x1fe000), [tuple(i['physical']) for i in decoded])
        self.assertIn((0x101fff, 0x102000, 0x102001), [tuple(i['physical']) for i in decoded])

    def test_direct_emission_and_context_dispatch(self):
        second = MPR.copy(); second[3] = 140
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'new'
            manifest = emit_capture(capture([observation(), observation(raw=(0xa9, 43)), observation(mpr=second)]), out)
            code = (out/'module.cpp').read_text()
            self.assertEqual(manifest['native_instructions_emitted'], 3)
            self.assertEqual(manifest['native_contexts'], 2)
            self.assertEqual(code.count('case 16384:'), 2)
            self.assertIn('s.a=42;', code)
            self.assertNotIn('interpret_step(', code)
            self.assertIn('switch(mapping)', code)
            self.assertLess(code.index('if(s.ticks >= deadline)'), code.index('switch(mapping)'))

    def test_deterministic_order(self):
        items = [observation(), observation(raw=(0xa9, 43))]
        with tempfile.TemporaryDirectory() as temp:
            first, second = Path(temp)/'one', Path(temp)/'two'
            # Equal provenance yields equal generated text despite input order.
            emit_capture(capture(items), first, 'a'*64)
            emit_capture(capture(list(reversed(items))), second, 'a'*64)
            self.assertEqual((first/'module.cpp').read_bytes(), (second/'module.cpp').read_bytes())
            self.assertEqual((first/'module.json').read_bytes(), (second/'module.json').read_bytes())

    def test_unsupported_explicit_and_empty(self):
        for items in ([], [observation(raw=(0,))]):
            with tempfile.TemporaryDirectory() as temp:
                out = Path(temp)/'new'
                manifest = emit_capture(capture(items), out)
                self.assertEqual(manifest['native_instructions_emitted'], 0)
                self.assertIn('return Exit::miss;', (out/'module.cpp').read_text())

    def test_runtime_length_table_matches_all_decoder_opcodes(self):
        import re
        header=(Path(__file__).resolve().parent.parent/'runtime/include/pce/code_capture.hpp').read_text()
        match=re.search(r'lengths\{([0-9,]+)\}',header)
        self.assertIsNotNone(match)
        lengths=[int(value) for value in match.group(1).split(',')]
        self.assertEqual(len(lengths),256)
        for opcode,length in enumerate(lengths):
            instruction=decode(lambda address: opcode if address==0x4000 else 0,
                               0x4000,tuple(MPR))
            self.assertEqual(length,len(instruction.data),f'opcode {opcode:02X}')

    def test_all_native_encodings_decode_emit(self):
        from pcerecomp.isa import NATIVE, _ROWS, _LENGTH
        items = [observation(0x4000+i*8, (i,)+tuple([0]*(_LENGTH[_ROWS[i].split('.')[1]]-1))) for i in NATIVE]
        with tempfile.TemporaryDirectory() as temp:
            manifest = emit_capture(capture(items, capacity=512), Path(temp)/'new')
        self.assertEqual(manifest['native_instructions_emitted'], len(NATIVE))

    def test_metadata_and_boolean_rejections(self):
        valid = capture()
        for field, value in [('schema', True), ('schema', 2), ('runtime_abi', True), ('runtime_abi', 13),
                             ('capacity', True), ('capacity', 0), ('capacity', 65537),
                             ('dropped_instructions', -1), ('retired_instructions', 0),
                             ('unreadable_instructions', 1<<64), ('complete', 1), ('complete', False)]:
            with self.subTest(field=field, value=value):
                broken=copy.deepcopy(valid);broken[field]=value
                with self.assertRaises(ValueError): validate_capture(broken)
        for field in valid:
            broken=copy.deepcopy(valid);del broken[field]
            with self.assertRaises(ValueError): validate_capture(broken)
        broken=copy.deepcopy(valid);broken['extra']=0
        with self.assertRaises(ValueError): validate_capture(broken)

    def test_identity_and_numeric_rejections(self):
        valid=capture()
        for field, value in [('pc', True), ('pc', 65536), ('mpr', [0]*7), ('mpr', [True]*8),
                             ('data', []), ('data', [0xa9]), ('data', [0xea, 0]),
                             ('data', [256]), ('physical', [0x200000, 0]),
                             ('physical', [0x100001, 0x100002]), ('native_hits', True),
                             ('native_hits', -1), ('interpreted_hits', 1<<64)]:
            with self.subTest(field=field,value=value):
                broken=copy.deepcopy(valid);broken['observations'][0][field]=value
                with self.assertRaises(ValueError): validate_capture(broken)
        for field in valid['observations'][0]:
            broken=copy.deepcopy(valid);del broken['observations'][0][field]
            with self.assertRaises(ValueError): validate_capture(broken)

    def test_zero_duplicate_and_capacity_rejected(self):
        with self.assertRaises(ValueError): validate_capture(capture([observation(),observation()]))
        with self.assertRaises(ValueError): validate_capture(capture([observation(interpreted=0)]))
        with self.assertRaises(ValueError): validate_capture(capture([observation(),observation(raw=(0xea,))],capacity=1))

    def test_incomplete_retirement_accounting(self):
        report=capture(dropped=42,unreadable=7)
        self.assertFalse(report['complete'])
        self.assertEqual(len(validate_capture(report)),1)
        report['retired_instructions']-=1
        with self.assertRaises(ValueError):validate_capture(report)

    def test_fresh_output_and_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'existing';out.mkdir()
            with self.assertRaises(ValueError):emit_capture(capture(),out)
            self.assertFalse(list(out.iterdir()))
            for digest in ('A'*64,'a'*63,False):
                with self.assertRaises(ValueError):emit_capture(capture(),Path(temp)/'new',digest)

    def test_load_digest_cli_and_duplicate_json(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'capture.json';raw=json.dumps(capture()).encode();source.write_bytes(raw)
            report,digest=load_capture(source)
            self.assertEqual(digest,hashlib.sha256(raw).hexdigest())
            out=Path(temp)/'module'
            self.assertEqual(main(['emit-capture',str(source),'--out',str(out)]),0)
            self.assertEqual(json.loads((out/'module.json').read_text())['code_capture_sha256'],digest)
            self.assertEqual(source.read_bytes(),raw)
            source.write_text('{"schema":1,"schema":1}')
            with self.assertRaises(ValueError):load_capture(source)

    def test_file_size_bound(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'capture.json';source.write_text(json.dumps(capture()))
            with patch('pcerecomp.capture.MAX_CAPTURE_BYTES',32):
                with self.assertRaises(ValueError):load_capture(source)


if __name__=='__main__':unittest.main()
