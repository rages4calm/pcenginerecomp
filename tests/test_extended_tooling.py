"""Explicit extended capture boundaries in live, raw and discovery tooling."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp.capture import EXTENDED_MAGIC
from pcerecomp.native_catalog import NativeCatalog
from pcerecomp.native_gaps import report_native_gaps
from scripts.dev_client import DevClient, _capture_view
from scripts.dev_audit_relation import encoded_map


def original():
    row = dict(pc=0x4000, mpr=[248]*8, physical=[0x1F0000], data=[0xEA], native_hits=0, interpreted_hits=1)
    return dict(schema=2, format='pce-code-capture-2', runtime_abi=29, capacity=131072,
        dropped_instructions=0, unreadable_instructions=0, retired_instructions=1,
        complete=True, observations=[row], checkpoint_origin=dict(sha256='a'*64,
            frame=0, ticks=0, native_steps=0, interpreter_steps=0))


def framed(value):
    header = {k:v for k,v in value.items() if k not in ('schema','format','observations')}
    return EXTENDED_MAGIC+b''.join((json.dumps(v,separators=(',', ':'))+'\n').encode()
        for v in (header,*value['observations'],dict(record='end',observations=len(value['observations']))))


def live():
    return dict(schema=1,runtime_abi=29,enabled=True,capture_schema=2,
        capture_format='pce-code-capture-2',capacity=131072,identity_count=1,
        retired_instructions=1,native_instructions=0,interpreted_instructions=1,
        retained_native_instructions=0,retained_interpreted_instructions=1,
        dropped_instructions=0,unreadable_instructions=0,complete=True,
        window=dict(requested_start_frame=0,started=True,current_frame=0,current_ticks=3,
            current_native_steps=0,current_interpreter_steps=1,actual_start_frame=0,
            actual_start_ticks=0,native_steps_before=0,interpreter_steps_before=0))


class ExtendedToolingTests(unittest.TestCase):
    def test_extended_live_page_above_legacy_offset_requires_explicit_profile(self):
        value=live()
        value.update(identity_count=65537,retired_instructions=65537,
            interpreted_instructions=65537,retained_interpreted_instructions=65537)
        value['window'].update(current_ticks=65537*3,current_interpreter_steps=65537)
        page=dict(value,offset=65536,limit=1,next_offset=65537,done=True,
            sources=[dict(source_id=65536,pc=0x4000,mpr=[248]*8,
                          physical=[0x1F0000],native_hits=0,interpreted_hits=1)])
        client=object.__new__(DevClient)
        with patch.object(client,'call',return_value=dict(capture=page)) as call:
            with self.assertRaises(ValueError): client.capture_sources(65536+1,1,65537)
            call.assert_not_called()
            self.assertEqual(client.capture_sources(65536,1,65537,capture_profile='extended'),page)
        value['capacity']=65537
        page=dict(value,offset=65537,limit=1,next_offset=65537,done=True,sources=[])
        with patch.object(client,'call',return_value=dict(capture=page)):
            self.assertEqual(client.capture_sources(65537,1,65537,capture_profile='extended'),page)

    def test_live_profile_is_explicit_and_preserves_legacy_capacity(self):
        value=live(); self.assertEqual(_capture_view(value),value)
        for mutate in (lambda c:c.pop('capture_schema'),lambda c:c.pop('capture_format'),
                       lambda c:c.update(capture_schema=True),lambda c:c.update(capture_format='unknown'),
                       lambda c:c.update(runtime_abi=28),lambda c:c.update(capacity=1048577)):
            changed=copy.deepcopy(value); mutate(changed)
            with self.subTest(value=changed), self.assertRaises(ValueError): _capture_view(changed)
        value.pop('capture_schema');value.pop('capture_format')
        with self.assertRaises(ValueError): _capture_view(value)
        value['capacity']=65536
        self.assertEqual(_capture_view(value),value)

    def test_encoded_relation_preserves_abi_origin_and_full_mapping(self):
        value=original(); expected=value['checkpoint_origin']
        rows=encoded_map(value,expected,expected_abi=29)
        self.assertEqual(list(rows.values()),[(0,1)])
        for mutation in ({'schema':True},{'format':'unknown'},{'runtime_abi':28},{'capacity':1048577}):
            changed=copy.deepcopy(value); changed.update(mutation)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): encoded_map(changed,expected,expected_abi=29)
        changed=copy.deepcopy(value);changed['schema']=1;changed.pop('format')
        with self.assertRaises(ValueError): encoded_map(changed,expected,expected_abi=29)

    def test_discovery_requires_opt_in_and_does_not_invent_execution(self):
        value=original(); row=value['observations'][0]
        key=(row['pc'],tuple(row['mpr']),tuple(row['physical']),tuple(row['data']))
        catalog=NativeCatalog(runtime_abi=29,observed=frozenset([key]),emitted=frozenset([key]),
            excluded=frozenset(),unsupported=frozenset(),counts={},provenance={})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'actual-format.jsonl';raw=framed(value);path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'explicit extended'): report_native_gaps(catalog,[path])
            report=report_native_gaps(catalog,[path],capture_profile='extended')
            self.assertEqual((report['format'],report['schema']),('pce-native-gap-report-2',2))
            self.assertFalse(report['qualification'])
            self.assertEqual(report['summary']['emitted_observed'],1)
            self.assertEqual(report['inputs'][0]['capture_schema'],2)
            self.assertEqual(path.read_bytes(),raw)
            with self.assertRaises(ValueError): report_native_gaps(catalog,[path],capture_profile=True)
            path.write_bytes(raw.rsplit(b'\n',2)[0]+b'\n')
            with self.assertRaises(ValueError): report_native_gaps(catalog,[path],capture_profile='extended')
