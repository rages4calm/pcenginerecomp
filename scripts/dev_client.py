"""Bounded persistent client for the optional loopback development server.

Only game-owned guest/SDL render targets are available, never the host desktop.
Keep a DevClient context open while holding input; disconnect releases its mask.
Uses only Python's standard library and writes captures with exclusive creation.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import json
from pathlib import Path
import socket
import struct
import sys
import threading
import time
import zlib

MAX_REQUEST = 8192
MAX_RESPONSE = 17 * 1024 * 1024
MAX_PIXELS = 4_000_000


class DevError(RuntimeError):
    """A rejected command or invalid development-server response."""


class ProtocolError(DevError):
    """A corrupt connection, closed before returning control to the caller."""


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer in {low}..{high}")
    return value


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate response field")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("non-finite JSON number")


def _geometry(width, height, source="present"):
    _integer(width, 1, MAX_PIXELS, "width")
    _integer(height, 1, MAX_PIXELS, "height")
    if width * height > MAX_PIXELS:
        raise ValueError("capture exceeds four-million-pixel limit")
    if source == "guest" and (width > 1024 or height > 512):
        raise ValueError("guest capture geometry out of range")
    return width * height * 3


class DevClient:
    """One persistent, request-serialized loopback connection.

    Protocol failures close the socket. A server command rejection keeps the
    connection open, allowing the caller to release input or inspect status.
    Each call has one total timeout, including fragmented response reads.
    """

    def __init__(self, port, host="127.0.0.1", timeout=30.0):
        _integer(port, 1, 65535, "port")
        if host == "localhost":
            host = "127.0.0.1"
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError("development client requires a loopback address")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 600:
            raise ValueError("timeout must be in (0,600] seconds")
        self.timeout = float(timeout)
        self._socket = socket.create_connection((host, port), self.timeout)
        self._buffer = bytearray()
        self._next_id = 1
        self._lock = threading.Lock()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        sock, self._socket = self._socket, None
        if sock is not None:
            sock.close()
        self._buffer.clear()

    def call(self, cmd, **args):
        return self._request(cmd, args, self.timeout)

    def _request(self, cmd, args, timeout):
        if not isinstance(cmd, str) or not cmd.isascii() or not cmd or len(cmd) > 64:
            raise ValueError("command must contain 1..64 ASCII characters")
        if "id" in args or "cmd" in args:
            raise ValueError("reserved request field")
        with self._lock:
            if self._socket is None:
                raise DevError("development connection is closed")
            identity = self._next_id
            _integer(identity, 1, (1 << 53) - 1, "request ID")
            request = json.dumps({"id": identity, "cmd": cmd, **args}, ensure_ascii=True,
                                 separators=(",", ":"), allow_nan=False).encode("ascii") + b"\n"
            if len(request) > MAX_REQUEST:
                raise ValueError("request exceeds 8192-byte limit")
            self._next_id += 1
            deadline = time.monotonic() + timeout
            try:
                self._socket.settimeout(timeout)
                self._socket.sendall(request)
                while True:
                    newline = self._buffer.find(b"\n")
                    if newline >= 0:
                        if newline + 1 > MAX_RESPONSE:
                            raise ValueError("response exceeds 17-MiB limit")
                        line = bytes(self._buffer[:newline])
                        del self._buffer[:newline + 1]
                        break
                    if len(self._buffer) >= MAX_RESPONSE:
                        raise ValueError("response exceeds 17-MiB limit")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("development response timed out")
                    self._socket.settimeout(remaining)
                    block = self._socket.recv(min(65536, MAX_RESPONSE - len(self._buffer)))
                    if not block:
                        raise ValueError("development server disconnected before a complete response")
                    self._buffer.extend(block)
                response = json.loads(line.decode("utf-8"), object_pairs_hook=_object,
                                      parse_constant=_constant)
                if not isinstance(response, dict) or type(response.get("id")) is not int or response["id"] != identity:
                    raise ValueError("response ID does not match request")
                if type(response.get("ok")) is not bool:
                    raise ValueError("response must contain boolean ok")
            except (OSError, ValueError, RecursionError) as error:
                self.close()
                raise ProtocolError(str(error)) from error
            if not response["ok"]:
                message = response.get("error", "command rejected")
                raise DevError(message if isinstance(message, str) else "command rejected")
            return response

    def capture(self, source="guest"):
        if source not in ("guest", "present"):
            raise ValueError("capture source must be guest or present")
        response = self.call("screenshot", source=source)
        try:
            if response.get("source") != source:
                raise ValueError("capture source does not match request")
            if response.get("encoding") != "rgb24-base64":
                raise ValueError("unsupported capture encoding")
            expected = _geometry(response.get("width"), response.get("height"), source)
            _integer(response.get("frame"), 0, (1 << 64) - 1, "frame")
            _integer(response.get("ticks"), 0, (1 << 64) - 1, "ticks")
            _integer(response.get("frame_ticks"), 0, response["ticks"], "frame ticks")
            data = response.get("data")
            if not isinstance(data, str) or len(data) != ((expected + 2) // 3) * 4:
                raise ValueError("capture base64 extent differs from geometry")
            rgb = base64.b64decode(data, validate=True)
            if len(rgb) != expected:
                raise ValueError("capture RGB extent differs from geometry")
        except (ValueError, binascii.Error) as error:
            self.close()
            raise ProtocolError(str(error)) from error
        metadata = {key: response[key] for key in ("width", "height", "frame", "ticks", "frame_ticks", "source")}
        return metadata, rgb

    def advance(self, frames):
        """Advance a paused simulation and wait until its requested frame ends."""
        _integer(frames, 1, 600, "frames")
        deadline = time.monotonic() + self.timeout
        queued = self._request("step_frames", {"frames": frames}, self.timeout)
        try:
            target = _integer(queued.get("target_frame"), 0, (1 << 64) - 1, "target frame")
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DevError("frame advancement timed out")
                status = self._request("status", {}, remaining)
                current = _integer(status.get("frame"), 0, (1 << 64) - 1, "frame")
                if type(status.get("paused")) is not bool:
                    raise ValueError("status must contain boolean paused")
                if current >= target and status["paused"]:
                    return status
                time.sleep(min(0.01, max(0, deadline - time.monotonic())))
        except ValueError as error:
            self.close()
            raise ProtocolError(str(error)) from error


def encode_png(width, height, rgb):
    expected = _geometry(width, height)
    if not isinstance(rgb, bytes) or len(rgb) != expected:
        raise ValueError("invalid RGB24 payload")

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    stride = width * 3
    rows = b"".join(b"\0" + rgb[start:start + stride] for start in range(0, len(rgb), stride))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def write_capture(path, metadata, rgb):
    """Write a user-selected new PNG/PPM directly, with no intermediate file."""
    path = Path(path)
    width, height = metadata["width"], metadata["height"]
    expected = _geometry(width, height)
    if not isinstance(rgb, bytes) or len(rgb) != expected:
        raise ValueError("invalid RGB24 payload")
    if path.suffix.lower() == ".png":
        data = encode_png(width, height, rgb)
    elif path.suffix.lower() == ".ppm":
        data = f"P6\n{width} {height}\n255\n".encode("ascii") + rgb
    else:
        raise ValueError("capture extension must be .png or .ppm")
    with path.open("xb") as stream:
        stream.write(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--timeout", type=float, default=30)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("ping", "status", "pause", "resume", "clear_input"):
        commands.add_parser(command)
    shot = commands.add_parser("screenshot")
    shot.add_argument("output", type=Path)
    shot.add_argument("--source", choices=("guest", "present"), default="guest")
    frames = commands.add_parser("frames")
    frames.add_argument("count", type=int)
    frames.add_argument("--resume", action="store_true")
    inputs = commands.add_parser("input")
    inputs.add_argument("mask", type=lambda value: int(value, 0))
    inputs.add_argument("--slot", type=int, default=0)
    duration = inputs.add_mutually_exclusive_group(required=True)
    duration.add_argument("--frames", type=int)
    duration.add_argument("--seconds", type=float)
    inputs.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        with DevClient(args.port, timeout=args.timeout) as client:
            if args.command == "screenshot":
                metadata, rgb = client.capture(args.source)
                write_capture(args.output, metadata, rgb)
                result = {**metadata, "output": str(args.output)}
            elif args.command == "frames":
                client.call("pause")
                result = client.advance(args.count)
                if args.resume:
                    client.call("resume")
            elif args.command == "input":
                _integer(args.mask, 0, 0xFFF, "mask")
                _integer(args.slot, 0, 4, "slot")
                if args.frames is not None:
                    _integer(args.frames, 1, 600, "frames")
                    client.call("pause")
                elif not 0 < args.seconds <= 600:
                    raise ValueError("seconds must be in (0,600]")
                client.call("set_input", port=args.slot, mask=args.mask)
                try:
                    if args.frames is not None:
                        result = client.advance(args.frames)
                    else:
                        until = time.monotonic() + args.seconds
                        while time.monotonic() < until:
                            time.sleep(min(1, until - time.monotonic()))
                            client.call("ping")  # Preserve the server's bounded idle lease.
                        result = client.call("status")
                finally:
                    client.call("clear_input")
                if args.resume:
                    client.call("resume")
            else:
                result = client.call(args.command)
            print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (DevError, OSError, ValueError) as error:
        print(f"development client: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
