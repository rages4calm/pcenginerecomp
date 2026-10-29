"""Authored streaming ledger relations, not captured game/protocol fixtures."""
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.dev_journal_audit import (
    JournalValidationError, MAX_LINE, MAX_METADATA, audit_wire_journal, main,
)
from scripts.dev_client import DevClient, ProtocolError
from tests.test_dev_client import Server, ok


def frame(value):
    return json.dumps(value, separators=(',', ':')).encode() + b'\n'


def encoded(data):
    return base64.b64encode(data).decode('ascii')


def session():
    return dict(schema=1, sequence=0, event='session', host='127.0.0.1', port=12345)


def request(identity=1, command='status'):
    return dict(schema=1, sequence=2*identity-1, event='request', request_id=identity,
                wire_base64=encoded(frame(dict(id=identity, cmd=command))))


def response(identity=1, *, ok=True, raw=None):
    return dict(schema=1, sequence=2*identity, event='response', request_id=identity,
                wire_base64=encoded(frame(dict(id=identity, ok=ok)) if raw is None else raw))


def failure(sequence, *, identity=1, phase='request', partial=b''):
    return dict(schema=1, sequence=sequence, event='failure', request_id=identity,
                phase=phase, error_type='ValueError', error='authored diagnostic',
                partial_base64=encoded(partial))


class JournalAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'wire.jsonl'

    def write(self, rows, tail=b''):
        self.path.write_bytes(b''.join(frame(row) for row in rows) + tail)
        return self.path

    def test_complete_frames_are_not_client_admission_or_clean_shutdown(self):
        self.write([session(), request(), response()])
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        seen = []
        result = audit_wire_journal(self.path, expected_sha256=digest, visit=seen.append)
        self.assertEqual((result['records'], result['request_intents'], result['response_frames']), (3, 1, 1))
        self.assertEqual(result['positive_server_replies'], 1)
        self.assertEqual(result['ending'], 'paired-frames')
        self.assertEqual(result['sha256'], digest)
        self.assertFalse(result['forensic_prefix'])
        self.assertNotIn('successful_requests', result)
        self.assertNotIn('connection_closed', result)
        self.assertNotIn('run_passed', result)
        self.assertEqual(seen[2].wire, frame(dict(id=1, ok=True)))
        with self.assertRaises(AttributeError):
            seen[2].event = 'accepted'

    def test_arbitrarily_many_records_use_bounded_line_reads_not_read_all(self):
        self.write([session(), *[r for i in range(1, 501) for r in (request(i), response(i))]])
        original = Path.open
        requests = []
        class BoundedStream:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *_): self.stream.close()
            def fileno(self): return self.stream.fileno()
            def readline(self, size):
                requests.append(size)
                return self.stream.readline(size)
            def read(self, *_): raise AssertionError('read-all is forbidden')
        def opening(path, *args, **kwargs):
            return BoundedStream(original(path, *args, **kwargs))
        with patch.object(Path, 'open', opening):
            result = audit_wire_journal(self.path)
        self.assertEqual(result['response_frames'], 500)
        self.assertEqual(result['commands'], {'status': 500})
        self.assertEqual(set(requests), {MAX_LINE+1})

    def test_unique_extension_names_do_not_grow_summary_command_storage(self):
        self.write([session(), *[r for i in range(1, 501)
                                for r in (request(i, f'extension-{i}'), response(i))]])
        result = audit_wire_journal(self.path)
        self.assertEqual(result['commands'], {})
        self.assertEqual(result['other_command_intents'], 500)

    def test_protocol_sized_record_can_exceed_one_mib_metadata_assumption(self):
        raw = frame(dict(id=1, ok=True, data='a'*(1024*1024+17)))
        self.write([session(), request(), response(raw=raw)])
        result = audit_wire_journal(self.path)
        self.assertGreater(result['bytes'], 1024*1024)
        self.assertEqual(result['positive_server_replies'], 1)

    def test_server_rejection_can_be_followed_by_another_intent(self):
        self.write([session(), request(), response(ok=False), request(2, 'ping'), response(2)])
        result = audit_wire_journal(self.path)
        self.assertEqual((result['positive_server_replies'], result['server_rejections']), (1, 1))

    def test_invalid_raw_protocol_is_retained_only_with_terminal_failure(self):
        for raw in (b'\xff\n', b'[]\n', b'{"id":1,"id":1,"ok":true}\n',
                    b'{"id":2,"ok":true}\n', b'{"id":true,"ok":true}\n',
                    b'{"id":1,"ok":1}\n', b'{"id":1,"ok":true,"x":NaN}\n'):
            with self.subTest(raw=raw):
                self.write([session(), request(), response(raw=raw), failure(3)])
                result = audit_wire_journal(self.path)
                self.assertEqual(result['protocol_invalid_responses'], 1)
                self.assertEqual(result['positive_server_replies'], 0)
                self.assertEqual(result['ending'], 'recorded-failure')
                self.assertFalse(result['forensic_prefix'])

    def test_overflow_floats_are_not_finite_json_intents_or_positive_replies(self):
        row = request()
        row['wire_base64'] = encoded(b'{"id":1,"cmd":"status","x":1e9999}\n')
        self.write([session(), row])
        with self.assertRaises(JournalValidationError): audit_wire_journal(self.path)
        self.write([session(), request(), response(raw=b'{"id":1,"ok":true,"x":1e9999}\n'), failure(3)])
        result = audit_wire_journal(self.path)
        self.assertEqual((result['protocol_invalid_responses'], result['positive_server_replies']), (1, 0))
        self.path.write_bytes(b'{"schema":1,"sequence":0,"event":"session","host":"127.0.0.1","port":1e9999}\n')
        with self.assertRaises(JournalValidationError): audit_wire_journal(self.path)

    def test_invalid_protocol_reply_without_failure_requires_forensic_mode(self):
        self.write([session(), request(), response(raw=b'not json\n')])
        with self.assertRaises(JournalValidationError): audit_wire_journal(self.path)
        result = audit_wire_journal(self.path, allow_incomplete=True)
        self.assertTrue(result['forensic_prefix'])
        self.assertEqual(result['ending'], 'invalid-response-without-failure')
        self.write([session(), request(), response(raw=b'not json\n'), request(2)])
        with self.assertRaises(JournalValidationError): audit_wire_journal(self.path, allow_incomplete=True)

    def test_admission_timeout_after_positive_raw_reply_is_not_success(self):
        self.write([session(), request(), response(), failure(3, partial=b'leftover next frame')])
        result = audit_wire_journal(self.path)
        self.assertEqual((result['response_frames'], result['positive_server_replies'], result['failure_records']), (1, 1, 1))
        self.assertEqual(result['failure_partial_buffer_bytes'], 19)
        self.assertEqual(result['ending'], 'recorded-failure')

    def test_partial_disconnect_is_unanswered_intent_not_fake_paired_reply(self):
        self.write([session(), request(), failure(2, partial=b'{"id":1')])
        result = audit_wire_journal(self.path)
        self.assertEqual((result['request_intents'], result['response_frames'], result['unanswered_intents']), (1, 0, 1))
        self.assertEqual(result['failure_partial_buffer_bytes'], 7)
        self.assertEqual(result['ending'], 'recorded-failure')

    def test_connect_failure_must_precede_all_requests_and_have_no_partial_frame(self):
        self.write([session(), failure(1, identity=0, phase='connect')])
        self.assertEqual(audit_wire_journal(self.path)['request_intents'], 0)
        for rows in ([session(), failure(1, identity=1, phase='connect')],
                     [session(), failure(1, identity=0, phase='connect', partial=b'x')],
                     [session(), request(), failure(2, identity=0, phase='connect')]):
            self.write(rows)
            with self.assertRaises(JournalValidationError): audit_wire_journal(self.path)

    def test_unpaired_intent_and_partial_outer_record_are_explicit_forensic_prefixes(self):
        self.write([session(), request()])
        with self.assertRaises(JournalValidationError): audit_wire_journal(self.path)
        result = audit_wire_journal(self.path, allow_incomplete=True)
        self.assertEqual(result['unpaired_request_id'], 1)
        self.assertTrue(result['forensic_prefix'])
        tail = b'{"schema":1,"sequence":2'
        self.write([session(), request()], tail)
        with self.assertRaises(JournalValidationError): audit_wire_journal(self.path)
        result = audit_wire_journal(self.path, allow_incomplete=True)
        self.assertEqual(result['ending'], 'truncated-record')
        self.assertEqual(result['trailing_record_bytes'], len(tail))
        self.assertEqual(result['trailing_record_sha256'], hashlib.sha256(tail).hexdigest())
        self.assertFalse(result['record_stream_complete'])

    def test_unknown_extra_missing_boolean_and_duplicate_outer_fields_refused(self):
        for field, value in (('schema', True), ('sequence', False), ('event', 'other'),
                             ('host', '8.8.8.8'), ('port', True), ('port', 0)):
            row = session(); row[field] = value; self.write([row])
            with self.subTest(field=field), self.assertRaises(JournalValidationError): audit_wire_journal(self.path)
        for change in ('extra', 'missing'):
            row = request()
            if change == 'extra': row['extra'] = 1
            else: row.pop('request_id')
            self.write([session(), row])
            with self.assertRaises(JournalValidationError): audit_wire_journal(self.path)
        for raw in (b'{"schema":1,"schema":1}\n', b'{"schema":NaN}\n', b'\xff\n'):
            self.path.write_bytes(raw)
            with self.assertRaises(JournalValidationError): audit_wire_journal(self.path, allow_incomplete=True)

    def test_impossible_order_reused_ids_and_postfailure_records_refused(self):
        bad = [
            [session(), response()], [session(), request(), request(2)],
            [session(), request(), response(), request()],
            [session(), request(), response(), response()],
            [session(), failure(1)],
            [session(), failure(1, identity=0, phase='connect'), request()],
        ]
        for rows in bad:
            self.write(rows)
            with self.subTest(rows=rows), self.assertRaises(JournalValidationError): audit_wire_journal(self.path)
        self.write([session(), failure(1, identity=0, phase='connect')], b'{"unfinished":')
        with self.assertRaisesRegex(JournalValidationError, 'terminal'):
            audit_wire_journal(self.path, allow_incomplete=True)

    def test_noncanonical_base64_multiline_and_malformed_intent_refused(self):
        for raw in (b'{}', b'{}\n{}\n', b'not json\n', frame(dict(id=True, cmd='status')),
                    frame(dict(id=1, cmd='')), frame(dict(id=1, cmd='x'*65))):
            row = request(); row['wire_base64'] = encoded(raw); self.write([session(), row])
            with self.subTest(raw=raw), self.assertRaises(JournalValidationError): audit_wire_journal(self.path)
        row = request(); row['wire_base64'] = 'AB=='  # Decodes, but nonzero padding bits.
        self.write([session(), row])
        with self.assertRaises(JournalValidationError): audit_wire_journal(self.path)

    def test_request_and_metadata_limits_are_per_record_not_a_batch_quota(self):
        row = request(); row['wire_base64'] = encoded(b'x'*8193)
        self.write([session(), row])
        with self.assertRaises(JournalValidationError): audit_wire_journal(self.path)
        row = failure(1, identity=0, phase='connect'); row['error'] = 'x'*(MAX_METADATA+1)
        self.write([session(), row])
        with self.assertRaisesRegex(JournalValidationError, 'metadata'): audit_wire_journal(self.path)
        self.write([session(), request(), response()])
        with patch('scripts.dev_journal_audit.MAX_LINE', 20):
            with self.assertRaises(JournalValidationError): audit_wire_journal(self.path)

    def test_wrong_external_digest_and_file_growth_invalidate_visitor_results(self):
        self.write([session(), request(), response()])
        seen = []
        with self.assertRaisesRegex(JournalValidationError, 'SHA256'):
            audit_wire_journal(self.path, expected_sha256='0'*64, visit=seen.append)
        self.assertEqual(len(seen), 3)  # Explicitly provisional; no summary returned.
        def append(event):
            if event.event == 'response':
                with self.path.open('ab') as stream: stream.write(frame(request(2)))
        with self.assertRaises(JournalValidationError): audit_wire_journal(self.path, visit=append)

    def test_same_length_file_replacement_is_refused(self):
        self.write([session(), request(), response()])
        def replace(event):
            if event.event == 'response':
                other = self.path.with_suffix('.new')
                other.write_bytes(self.path.read_bytes())
                os.replace(other, self.path)
        # Windows can deny replacing this open file; POSIX permits replacement
        # and the reader then refuses its changed inode. Neither yields a
        # successfully audited snapshot.
        with self.assertRaises((JournalValidationError, PermissionError)):
            audit_wire_journal(self.path, visit=replace)

    def test_visitor_exception_and_cli_failure_return_no_success_summary(self):
        self.write([session(), request(), response()])
        def stop(_): raise RuntimeError('authored visitor failure')
        with self.assertRaisesRegex(RuntimeError, 'visitor'): audit_wire_journal(self.path, visit=stop)
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(main([str(self.path)]), 0)
            self.assertEqual(json.loads(out.getvalue())['response_frames'], 1)
        with patch('sys.stdout', new_callable=io.StringIO) as out, patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(main([str(self.path), '--sha256', '0'*64]), 1)
            self.assertEqual(out.getvalue(), '')

    def test_real_client_helper_failure_can_still_leave_a_paired_raw_snapshot(self):
        with Server(lambda r: ok(r, address=7, length=1, data='zz')) as server, \
             DevClient(server.port, journal=self.path) as client:
            with self.assertRaises(ProtocolError):
                client.read_memory(7, 1)
        result = audit_wire_journal(self.path)
        self.assertEqual((result['positive_server_replies'], result['failure_records']), (1, 0))
        self.assertEqual(result['ending'], 'paired-frames')
        self.assertNotIn('client_accepted', result)

    def test_real_client_records_and_refuses_overflow_response_before_return(self):
        raw = b'{"id":1,"ok":true,"value":1e9999}\n'
        with Server(lambda _: raw) as server, DevClient(server.port, journal=self.path) as client:
            with self.assertRaises(ProtocolError):
                client.call('status')
        result = audit_wire_journal(self.path)
        self.assertEqual((result['protocol_invalid_responses'], result['positive_server_replies'],
                          result['failure_records']), (1, 0, 1))


if __name__ == '__main__':
    unittest.main()
