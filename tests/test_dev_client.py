"""Authored TCP development protocol, bounded image and output protection tests."""
import base64
import io
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zlib

from scripts.dev_client import DevClient, DevError, ProtocolError, encode_png, main, write_capture


class Server:
    def __init__(self, handler):
        self.handler = handler
        self.requests = []
        self.errors = []
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]
        self.socket.listen(1)
        self.socket.settimeout(2)
        self.thread = threading.Thread(target=self.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.socket.close()
        self.thread.join(3)
        if self.thread.is_alive():
            raise AssertionError("authored server did not terminate")
        if self.errors:
            raise self.errors[0]

    def run(self):
        try:
            with self.socket.accept()[0] as connection:
                connection.settimeout(2)
                pending = bytearray()
                while True:
                    data = connection.recv(8192)
                    if not data:
                        return
                    pending.extend(data)
                    while b"\n" in pending:
                        line, _, rest = pending.partition(b"\n")
                        pending[:] = rest
                        request = json.loads(line)
                        self.requests.append(request)
                        response = self.handler(request)
                        if response is None:
                            return
                        if isinstance(response, dict):
                            response = json.dumps(response).encode() + b"\n"
                        fragments = response if isinstance(response, list) else [response]
                        for fragment in fragments:
                            connection.sendall(fragment)
        except ConnectionError:
            pass  # Expected when a bounded client rejects an authored bad reply.
        except Exception as error:
            self.errors.append(error)


def ok(request, **fields):
    return {"id": request["id"], "ok": True, **fields}


def capture(request, **changes):
    return ok(request, **{"source": request.get("source", "guest"), "encoding": "rgb24-base64",
                         "width": 2, "height": 1, "frame": 7, "ticks": 2500000,
                         "frame_ticks": 2400000,
                         "data": base64.b64encode(bytes((1, 2, 3, 253, 254, 255))).decode(), **changes})


class DevelopmentClientTests(unittest.TestCase):
    def test_memory_roundtrip_preserves_physical_range_and_expected_bytes(self):
        def respond(request):
            fields = {'address': request['address'], 'length': request.get('length', len(request.get('data', ''))//2)}
            if request['cmd'] == 'read_memory':
                fields['data'] = '01ff00'
            return ok(request, **fields)
        with Server(respond) as server:
            with DevClient(server.port) as client:
                self.assertEqual(client.read_memory(0x1F0000, 3), b'\x01\xff\0')
                client.write_memory(0x1F0000, b'\x02\x03\x04', b'\x01\xff\0')
            self.assertEqual(server.requests[1], {'id': 2, 'cmd': 'write_memory', 'address': 0x1F0000, 'data': '020304', 'expected': '01ff00'})

    def test_memory_bad_replies_close_connection(self):
        for changes in ({'address': 2}, {'address': True}, {'length': True}, {'length': 2},
                        {'data': 'zz'}, {'data': 'AA'}, {'data': 'a'}, {'data': 1}):
            with self.subTest(changes=changes), Server(lambda r, changes=changes: ok(r, **{'address': 1, 'length': 1, 'data': 'ab', **changes})) as server:
                with DevClient(server.port) as client:
                    with self.assertRaises(ProtocolError):
                        client.read_memory(1, 1)
                    with self.assertRaisesRegex(DevError, 'closed'):
                        client.call('ping')
        with Server(lambda r: ok(r, address=1, length=2)) as server:
            with DevClient(server.port) as client:
                with self.assertRaises(ProtocolError):
                    client.write_memory(1, b'\1', b'\0')

    def test_memory_argument_validation_precedes_network(self):
        with Server(lambda r: ok(r)) as server:
            with DevClient(server.port) as client:
                for address, length in ((True, 1), (-1, 1), (0x200000, 1), (1, 0), (1, 257), (0x1FFFFF, 2)):
                    with self.assertRaises(ValueError):
                        client.read_memory(address, length)
                for address, data, expected in ((1, b'', b''), (1, b'\0'*257, b'\0'*257),
                                                (1, b'\0', b''), (1, bytearray([0]), b'\0'),
                                                (0x1FFFFF, b'\0\0', b'\0\0')):
                    with self.assertRaises(ValueError):
                        client.write_memory(address, data, expected)
                client.call('ping')
            self.assertEqual(len(server.requests), 1)

    def test_persistent_serial_requests_fragmented_reply_and_ids(self):
        def respond(request):
            data = json.dumps(ok(request, command=request["cmd"])).encode() + b"\n"
            return [data[n:n+1] for n in range(len(data))]
        with Server(respond) as server:
            with DevClient(server.port) as client:
                self.assertEqual(client.call("set_input", port=0, mask=8)["id"], 1)
                self.assertEqual(client.call("ping")["id"], 2)
                self.assertEqual(client.call("clear_input")["id"], 3)
            self.assertEqual([r["cmd"] for r in server.requests], ["set_input", "ping", "clear_input"])

    def test_command_error_keeps_connection_usable(self):
        with Server(lambda r: {"id": r["id"], "ok": False, "error": "not ready"} if r["cmd"] == "screenshot" else ok(r)) as server:
            with DevClient(server.port) as client:
                with self.assertRaisesRegex(DevError, "not ready"):
                    client.call("screenshot")
                self.assertEqual(client.call("ping")["id"], 2)

    def test_wire_protocol_refusals_close_connection(self):
        replies = [b"not JSON\n", b"[]\n", b'{"id":1,"id":1,"ok":true}\n',
                   b'{"id":1,"ok":true,"value":NaN}\n', b'{"id":true,"ok":true}\n',
                   b'{"id":2,"ok":true}\n', b'{"id":1,"ok":1}\n', b'\xff\n', None]
        for reply in replies:
            with self.subTest(reply=reply):
                with Server(lambda _, data=reply: data) as server:
                    with DevClient(server.port) as client:
                        with self.assertRaises(ProtocolError):
                            client.call("ping")
                        with self.assertRaisesRegex(DevError, "closed"):
                            client.call("ping")

    def test_response_budget_applies_before_json_or_complete_line(self):
        for response in (b"x" * 65, b"x" * 64 + b"\n"):
            with Server(lambda _, data=response: data) as server:
                with DevClient(server.port) as client, patch("scripts.dev_client.MAX_RESPONSE", 64):
                    with self.assertRaisesRegex(ProtocolError, "limit"):
                        client.call("ping")

    def test_request_budget_reserved_fields_and_nonfinite_numbers(self):
        with Server(lambda r: ok(r)) as server:
            with DevClient(server.port) as client:
                for command, args in (("", {}), ("é", {}), ("x"*65, {}), ("ping", {"id": 3}),
                                      ("ping", {"payload": "x"*8192}), ("ping", {"value": float("nan")})):
                    with self.subTest(command=command, args=list(args)):
                        with self.assertRaises((ValueError, TypeError)):
                            client.call(command, **args)
                self.assertEqual(client.call("ping")["id"], 1)
                self.assertEqual(len(server.requests), 1)

    def test_loopback_port_and_timeout_boundaries(self):
        for kwargs in ({"port": 0}, {"port": 65536}, {"port": True}, {"port": 1, "host": "8.8.8.8"},
                       {"port": 1, "timeout": 0}, {"port": 1, "timeout": float("nan")}, {"port": 1, "timeout": 601}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                DevClient(**kwargs)

    def test_capture_metadata_rgb_and_source_preserved(self):
        with Server(capture) as server:
            with DevClient(server.port) as client:
                for source in ("guest", "present"):
                    metadata, rgb = client.capture(source)
                    self.assertEqual(metadata, {"width": 2, "height": 1, "frame": 7, "ticks": 2500000, "frame_ticks": 2400000, "source": source})
                    self.assertEqual(rgb, bytes((1, 2, 3, 253, 254, 255)))
                with self.assertRaises(ValueError):
                    client.capture("desktop")

    def test_capture_geometry_encoding_and_base64_refusals(self):
        invalid = [{"source": "present"}, {"source": "desktop"}, {"encoding": "png"},
                   {"width": 0}, {"width": True}, {"width": 1025}, {"height": 513},
                   {"width": 4_000_001}, {"width": 2000, "height": 2001},
                   {"frame": -1}, {"ticks": 1 << 64}, {"frame": True},
                   {"frame_ticks": None}, {"frame_ticks": True}, {"frame_ticks": -1}, {"frame_ticks": 2500001},
                   {"data": "!!!!!!!!"}, {"data": "AQID"}, {"data": "AA==AA=="}, {"data": 7}]
        for changes in invalid:
            with self.subTest(changes=changes):
                with Server(lambda r, changes=changes: capture(r, **changes)) as server:
                    with DevClient(server.port) as client:
                        with self.assertRaises(ProtocolError):
                            client.capture()

    def test_present_capture_accepts_window_extent_larger_than_guest_limits(self):
        rgb = bytes((17, 29, 43)) * 513
        with Server(lambda r: capture(r, width=1, height=513, data=base64.b64encode(rgb).decode())) as server:
            with DevClient(server.port) as client:
                metadata, received = client.capture("present")
                self.assertEqual(metadata["height"], 513)
                self.assertEqual(received, rgb)

    def test_frame_advance_uses_acknowledged_target_and_waits_paused(self):
        calls = 0
        def respond(request):
            nonlocal calls
            if request["cmd"] == "step_frames":
                self.assertEqual(request["frames"], 3)
                return ok(request, target_frame=15)
            calls += 1
            return ok(request, frame=14 if calls == 1 else 15, paused=calls >= 3)
        with Server(respond) as server:
            with DevClient(server.port) as client:
                result = client.advance(3)
                self.assertEqual(result["frame"], 15)
                self.assertTrue(result["paused"])
                for count in (0, 601, True):
                    with self.assertRaises(ValueError):
                        client.advance(count)
        self.assertEqual(calls, 3)

    def test_fragmentation_does_not_reset_total_response_timeout(self):
        class SlowFragments(list):
            def __iter__(self):
                for piece in super().__iter__():
                    time.sleep(0.01)
                    yield piece
        def respond(request):
            data = json.dumps(ok(request)).encode()+b"\n"
            return SlowFragments([data[n:n+1] for n in range(len(data))])
        with Server(respond) as server:
            with DevClient(server.port, timeout=0.035) as client:
                with self.assertRaises(ProtocolError):
                    client.call("ping")

    def test_frame_advance_refuses_invalid_target_or_paused_metadata(self):
        for target, paused in ((True, True), (-1, True), (1, "yes")):
            with self.subTest(target=target, paused=paused):
                def respond(request):
                    return ok(request, target_frame=target) if request["cmd"] == "step_frames" else ok(request, frame=1, paused=paused)
                with Server(respond) as server:
                    with DevClient(server.port) as client:
                        with self.assertRaises(ProtocolError):
                            client.advance(1)

    def test_png_pixels_chunks_crc_and_exclusive_output(self):
        rgb = bytes((0, 1, 2, 253, 254, 255, 3, 4, 5, 250, 251, 252))
        data = encode_png(2, 2, rgb)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        offset = 8
        kinds = []
        while offset < len(data):
            length = int.from_bytes(data[offset:offset+4], "big")
            kind = data[offset+4:offset+8]
            payload = data[offset+8:offset+8+length]
            self.assertEqual(int.from_bytes(data[offset+8+length:offset+12+length], "big"), zlib.crc32(kind+payload) & 0xFFFFFFFF)
            kinds.append(kind)
            if kind == b"IHDR":
                self.assertEqual(struct.unpack(">IIBBBBB", payload), (2, 2, 8, 2, 0, 0, 0))
            if kind == b"IDAT":
                self.assertEqual(zlib.decompress(payload), b"\0"+rgb[:6]+b"\0"+rgb[6:])
            offset += length+12
        self.assertEqual(kinds, [b"IHDR", b"IDAT", b"IEND"])
        with tempfile.TemporaryDirectory(prefix="pce-authored-client-") as temporary:
            for extension in (".png", ".ppm"):
                path = Path(temporary)/("authored"+extension)
                write_capture(path, {"width": 2, "height": 2}, rgb)
                original = path.read_bytes()
                with self.assertRaises(FileExistsError):
                    write_capture(path, {"width": 2, "height": 2}, bytes(len(rgb)))
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(original, data if extension == ".png" else b"P6\n2 2\n255\n"+rgb)
            with self.assertRaises(ValueError):
                write_capture(Path(temporary)/"bad.jpg", {"width": 2, "height": 2}, rgb)
            self.assertFalse((Path(temporary)/"bad.jpg").exists())

    def test_cli_screenshot_writes_only_requested_new_file(self):
        with tempfile.TemporaryDirectory(prefix="pce-authored-client-cli-") as temporary:
            output = Path(temporary)/"authored.png"
            with Server(capture) as server, patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(main(["--port", str(server.port), "screenshot", str(output)]), 0)
                self.assertEqual(json.loads(stdout.getvalue())["source"], "guest")
            self.assertEqual(list(Path(temporary).iterdir()), [output])
            self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_cli_frame_input_keeps_session_until_clear(self):
        def respond(request):
            if request["cmd"] == "step_frames":
                return ok(request, target_frame=3)
            return ok(request, frame=3, paused=True)
        with Server(respond) as server, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(main(["--port", str(server.port), "input", "0x48", "--slot", "2", "--frames", "3", "--resume"]), 0)
        self.assertEqual([r["cmd"] for r in server.requests], ["pause", "set_input", "step_frames", "status", "clear_input", "resume"])
        self.assertEqual(server.requests[1]["mask"], 0x48)
        self.assertEqual(server.requests[1]["port"], 2)


if __name__ == "__main__":
    unittest.main()
