import unittest
from unittest.mock import Mock

from scripts.dev_client import DevClient, ProtocolError


class DiscOriginClientTests(unittest.TestCase):
    def client(self, report):
        client = object.__new__(DevClient)
        client.call = Mock(return_value={"disc_origin": report})
        client.close = Mock()
        return client

    def report(self):
        return dict(schema=1, epoch=1, address=0x100000, length=2,
                    reads=12, writes=8, offsets=[2048, None])

    def test_exact_range_and_unknown_offsets(self):
        report = self.report()
        client = self.client(report)
        self.assertEqual(client.disc_origins(0x100000, 2), report)
        client.call.assert_called_once_with("disc_origin", address=0x100000, length=2)

    def test_wrong_shape_values_or_range_close_session(self):
        for update in ({"address":0}, {"length":1}, {"schema":True},
                       {"offsets":[True,None]}, {"offsets":[-1,None]},
                       {"epoch":False}, {"offsets":[]}, {"reads":-1}):
            with self.subTest(update=update):
                client = self.client(self.report() | update)
                with self.assertRaises(ProtocolError):
                    client.disc_origins(0x100000, 2)
                client.close.assert_called_once()

    def test_invalid_query_does_not_send(self):
        client = self.client(self.report())
        for address, length in ((0,0), (0,257), (0x1FFFFF,2), (True,2)):
            with self.assertRaises(ValueError):
                client.disc_origins(address,length)
        client.call.assert_not_called()
