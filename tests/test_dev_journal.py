"""Authored loopback wire evidence, including failures before semantic admission."""
import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.dev_client import DevClient, DevError, ProtocolError, main
from scripts.dev_journal import JournalError, WireJournal
from tests.test_dev_client import Server, ok


def records(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row['sequence'] for row in rows] == list(range(len(rows)))
    assert all(type(row['schema']) is int and row['schema'] == 1 for row in rows)
    return rows


def wire(row):
    return base64.b64decode(row['wire_base64'], validate=True)


class DevJournalTests(unittest.TestCase):
    def test_every_successful_wire_record_is_fsynced_before_return(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'wire.jsonl'
            with Server(lambda r: ok(r, value=17)) as server, \
                 patch('scripts.dev_journal.os.fsync') as sync, \
                 DevClient(server.port, journal=path) as client:
                self.assertEqual(sync.call_count, 1)  # Session exists before contact.
                reply = client.call('status')
                self.assertEqual(sync.call_count, 3)
                rows = records(path)  # Visible even while the client/file remain open.
                self.assertEqual([r['event'] for r in rows], ['session', 'request', 'response'])
                self.assertEqual(json.loads(wire(rows[1])), server.requests[0])
                self.assertEqual(json.loads(wire(rows[2])), reply)
                self.assertTrue(wire(rows[1]).endswith(b'\n'))
                self.assertEqual(rows[1]['request_id'], rows[2]['request_id'])

    def test_default_client_opens_no_journal(self):
        with Server(ok) as server, patch('scripts.dev_client.WireJournal') as journal:
            with DevClient(server.port) as client:
                client.call('ping')
            journal.assert_not_called()

    def test_existing_file_is_untouched_and_refused_before_host_contact(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'existing.jsonl'
            path.write_bytes(b'preserve owner file')
            with patch('scripts.dev_client.socket.create_connection') as connect:
                with self.assertRaises(FileExistsError):
                    DevClient(12345, journal=path)
                connect.assert_not_called()
            self.assertEqual(path.read_bytes(), b'preserve owner file')

    def test_session_failure_prevents_contact(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('scripts.dev_journal.os.fsync', side_effect=OSError('authored fsync failure')), \
                 patch('scripts.dev_client.socket.create_connection') as connect:
                with self.assertRaises(JournalError):
                    DevClient(12345, journal=Path(folder) / 'failed.jsonl')
                connect.assert_not_called()

    def test_raw_invalid_utf8_duplicate_ids_and_bad_ack_are_retained(self):
        bad = [b'\xff\n', b'{"id":1,"id":1,"ok":true}\n',
               b'{"id":2,"ok":true}\n', b'{"id":1,"ok":0}\n']
        with tempfile.TemporaryDirectory() as folder:
            for index, raw in enumerate(bad):
                path = Path(folder) / f'bad-{index}.jsonl'
                with self.subTest(raw=raw), Server(lambda _: raw) as server, \
                     DevClient(server.port, journal=path) as client:
                    with self.assertRaises(ProtocolError):
                        client.call('status')
                    with self.assertRaisesRegex(DevError, 'closed'):
                        client.call('ping')
                rows = records(path)
                self.assertEqual([r['event'] for r in rows], ['session', 'request', 'response', 'failure'])
                self.assertEqual(wire(rows[2]), raw)

    def test_semantic_helper_failure_still_retains_complete_raw_reply(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad-memory.jsonl'
            with Server(lambda r: ok(r, address=7, length=1, data='zz')) as server, \
                 DevClient(server.port, journal=path) as client:
                with self.assertRaises(ProtocolError):
                    client.read_memory(7, 1)
            self.assertEqual(json.loads(wire(records(path)[2]))['data'], 'zz')

    def test_higher_level_failed_comparison_cannot_lose_the_after_response(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'pair.jsonl'
            with Server(lambda r: ok(r, paused=True, host={'counter': r['id']})) as server, \
                 DevClient(server.port, journal=path) as client:
                before, after = client.call('status'), client.call('status')
                with self.assertRaisesRegex(ValueError, 'authored comparison'):
                    if before['host'] != after['host']:
                        raise ValueError('authored comparison')
                replies = [json.loads(wire(r)) for r in records(path) if r['event'] == 'response']
                self.assertEqual(replies, [before, after])

    def test_server_rejection_keeps_journal_and_connection_usable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'rejected.jsonl'
            def respond(r):
                return dict(id=r['id'], ok=False, error='not ready') if r['id'] == 1 else ok(r)
            with Server(respond) as server, DevClient(server.port, journal=path) as client:
                with self.assertRaisesRegex(DevError, 'not ready'):
                    client.call('status')
                self.assertTrue(client.call('ping')['ok'])
            self.assertEqual([r['request_id'] for r in records(path) if r['event'] == 'response'], [1, 2])

    def test_partial_disconnect_is_saved_without_inventing_complete_response(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'partial.jsonl'
            class PartialSocket:
                def settimeout(self, _): pass
                def sendall(self, _): pass
                def recv(self, _):
                    value, self.data = self.data, b''
                    return value
                def close(self): pass
                data = b'{"id":1'
            with patch('scripts.dev_client.socket.create_connection', return_value=PartialSocket()), \
                 DevClient(12345, journal=path) as client:
                with self.assertRaises(ProtocolError):
                    client.call('status')
            rows = records(path)
            self.assertEqual([r['event'] for r in rows], ['session', 'request', 'failure'])
            self.assertEqual(base64.b64decode(rows[-1]['partial_base64']), b'{"id":1')

    def test_failed_request_fsync_stops_before_sending(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'request-failure.jsonl'
            with Server(ok) as server, DevClient(server.port, journal=path) as client:
                with patch('scripts.dev_journal.os.fsync', side_effect=OSError('authored failure')):
                    with self.assertRaises(ProtocolError):
                        client.call('set_input', mask=1)
                self.assertEqual(server.requests, [])
                with self.assertRaisesRegex(DevError, 'closed'):
                    client.call('ping')

    def test_response_fsync_failure_never_returns_ack_or_retries_command(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'response-failure.jsonl'
            with Server(ok) as server, DevClient(server.port, journal=path) as client:
                with patch('scripts.dev_journal.os.fsync', side_effect=[None, OSError('authored response failure')]):
                    with self.assertRaises(ProtocolError):
                        client.call('set_input', mask=1)
                with self.assertRaisesRegex(DevError, 'closed'):
                    client.call('ping')
            self.assertEqual([r['cmd'] for r in server.requests], ['set_input'])
            # The server may already have acted. A failed fsync is not rollback
            # or durable success proof, even if bytes remain readable locally.
            self.assertEqual([r['event'] for r in records(path)], ['session', 'request', 'response'])

    def test_expired_request_journal_deadline_sends_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'before-send-timeout.jsonl'
            with Server(ok) as server, DevClient(server.port, journal=path) as client:
                with patch('scripts.dev_client.time.monotonic', side_effect=[0.0, 31.0]):
                    with self.assertRaisesRegex(ProtocolError, 'before send'):
                        client.call('set_input', mask=1)
            self.assertEqual(server.requests, [])
            self.assertEqual(records(path)[-1]['error_type'], 'TimeoutError')

    def test_response_journal_deadline_overrun_is_refused_after_os_returns(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'response-timeout.jsonl'
            with Server(ok) as server, DevClient(server.port, journal=path) as client:
                calls = 0
                with patch('scripts.dev_client.time.monotonic', return_value=0.0) as now:
                    def sync(_):
                        nonlocal calls
                        calls += 1
                        if calls == 2:  # Request then response; session was already written.
                            now.return_value = 31.0
                    with patch('scripts.dev_journal.os.fsync', side_effect=sync):
                        with self.assertRaisesRegex(ProtocolError, 'admission timed out'):
                            client.call('status')
            self.assertEqual(len(server.requests), 1)
            self.assertEqual([r['event'] for r in records(path)], ['session', 'request', 'response', 'failure'])

    def test_short_regular_file_writes_are_completed_before_fsync(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'short.jsonl'
            journal = WireJournal(path, host='127.0.0.1', port=12345)
            original = journal._stream
            class ShortWrites:
                def write(self, view): return original.write(view[:3])
                def flush(self): return original.flush()
                def fileno(self): return original.fileno()
                def close(self): return original.close()
            journal._stream = ShortWrites()
            journal.wire('request', 1, b'{"id":1}\n')
            journal.close()
            self.assertEqual(wire(records(path)[1]), b'{"id":1}\n')

    def test_cli_opt_in_and_connection_failure_leave_private_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cli.jsonl'
            with Server(ok) as server, patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(['--port', str(server.port), '--wire-journal', str(path), 'ping']), 0)
            self.assertEqual(len(records(path)), 3)
            failed = Path(folder) / 'connect.jsonl'
            with patch('scripts.dev_client.socket.create_connection', side_effect=OSError('authored connect failure')):
                with self.assertRaises(OSError):
                    DevClient(12345, journal=failed)
            self.assertEqual(records(failed)[-1]['phase'], 'connect')


if __name__ == '__main__':
    unittest.main()
