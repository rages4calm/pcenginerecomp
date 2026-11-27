"""Independent client-envelope timings; no guessed network-only RTT."""
import json
import unittest
from unittest.mock import patch

from scripts.dev_client import DevClient, DevError, ProtocolError
from tests.test_dev_client import Server, ok


class Clock:
    now = 0

    def read(self):
        return self.now

    def spend(self, duration):
        self.now += duration


class ProfileTests(unittest.TestCase):
    def test_stage_attribution_counts_exact_wire_bytes_and_detaches_snapshot(self):
        clock = Clock()
        reply = b'{"id":1,"ok":true,"value":7}\n'

        class Socket:
            def settimeout(self, _): pass
            def sendall(self, data):
                self.request = data
                clock.spend(11)
            def recv(self, _):
                clock.spend(7 if self.first else 5)
                result = reply[:9] if self.first else reply[9:]
                self.first = False
                return result
            def close(self): pass
            first = True

        class Journal:
            def wire(self, event, *_):
                clock.spend(3 if event == 'request' else 13)
            def close(self): pass

        loads = json.loads
        def admit(*args, **kwargs):
            clock.spend(17)
            return loads(*args, **kwargs)

        sock = Socket()
        with patch('scripts.dev_client.socket.create_connection', return_value=sock), \
             patch('scripts.dev_client.time.perf_counter_ns', side_effect=clock.read), \
             DevClient(12345, profile=True) as client:
            client._journal = Journal()
            with patch('scripts.dev_client.json.loads', side_effect=admit):
                self.assertEqual(client.call('status')['value'], 7)
            report = client.profile_report()
            row = report['commands']['status']
            self.assertEqual(row, dict(count=1, accepted=1, rejected=0, failed=0,
                request_bytes=len(sock.request), response_bytes=len(reply), elapsed_ns=56,
                minimum_ns=56, maximum_ns=56, stages_ns=dict(lock_wait=0, prepare=0,
                    request_journal=3, exchange=23, response_journal=13, admission=17)))
            row['stages_ns']['exchange'] = -1
            self.assertEqual(client.profile_report()['commands']['status']['stages_ns']['exchange'], 23)
            self.assertNotIn('value', json.dumps(client.profile_report()))

    def test_rejected_and_invalid_replies_and_closed_calls_are_distinct(self):
        def respond(request):
            if request['id'] == 1:
                return dict(id=1, ok=False, error='authored rejection')
            return b'{"id":999,"ok":true}\n'
        with Server(respond) as server, DevClient(server.port, profile=True) as client:
            with self.assertRaisesRegex(DevError, 'authored rejection'):
                client.call('status')
            with self.assertRaises(ProtocolError):
                client.call('status')
            with self.assertRaisesRegex(DevError, 'closed'):
                client.call('status')
            row = client.profile_report()['commands']['status']
            self.assertEqual((row['count'], row['accepted'], row['rejected'], row['failed']), (3, 0, 1, 2))
            self.assertGreater(row['response_bytes'], 0)

    def test_partial_failure_does_not_invent_complete_response_bytes(self):
        class Socket:
            def settimeout(self, _): pass
            def sendall(self, _): pass
            def recv(self, _):
                result, self.data = self.data, b''
                return result
            def close(self): pass
            data = b'{"id":1'
        with patch('scripts.dev_client.socket.create_connection', return_value=Socket()), \
             DevClient(12345, profile=True) as client:
            with self.assertRaises(ProtocolError):
                client.call('status')
            self.assertEqual(client.profile_report()['commands']['status']['response_bytes'], 0)

    def test_default_is_opt_in_and_invalid_options_do_not_contact_host(self):
        with patch('scripts.dev_client.socket.create_connection') as connect:
            for option in (None, 1, 'yes'):
                with self.subTest(option=option), self.assertRaises(ValueError):
                    DevClient(12345, profile=option)
            connect.assert_not_called()
        with Server(ok) as server, DevClient(server.port) as client:
            client.call('ping')
            with self.assertRaisesRegex(DevError, 'not enabled'):
                client.profile_report()

    def test_command_cardinality_is_bounded_and_accounting_conserves(self):
        with Server(ok) as server, DevClient(server.port, profile=True) as client:
            for index in range(75):
                client.call(f'authored-{index}')
            commands = client.profile_report()['commands']
            self.assertEqual(len(commands), 65)
            self.assertEqual(commands['<other>']['count'], 11)
            self.assertEqual(sum(row['count'] for row in commands.values()), 75)
            self.assertTrue(all(row['accepted'] == row['count'] for row in commands.values()))


if __name__ == '__main__':
    unittest.main()
