"""Optional independent CPU check through an isolated Geargrafx MCP instance.

Supply a project-local portable emulator executable; no software is downloaded
or installed by this script. Only authored synthetic media and RAM are used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from generate_fixture import make_fixture


class Mcp:
    def __init__(self, port):
        self.url = f"http://127.0.0.1:{port}/mcp"
        self.headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        self.sequence = 0

    def rpc(self, method, params=None):
        self.sequence += 1
        request = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not method.startswith("notifications/"):
            request["id"] = self.sequence
        req = urllib.request.Request(self.url, data=json.dumps(request).encode(), headers=self.headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.headers.get("Mcp-Session-Id"):
                self.headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
            data = response.read(2*1024*1024+1)
        if len(data) > 2*1024*1024:
            raise RuntimeError("MCP response exceeded 2 MiB")
        result = json.loads(data) if data else {}
        if "error" in result:
            raise RuntimeError(f"MCP protocol error: {result['error']}")
        return result.get("result", {})

    def call(self, tool, **arguments):
        result = self.rpc("tools/call", {"name": tool, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(f"Reference tool failed: {tool}: {result.get('content')}")
        blocks = [b["text"] for b in result.get("content", []) if b["type"] == "text"]
        if len(blocks) != 1:
            raise RuntimeError(f"Unexpected reference response for {tool}")
        return json.loads(blocks[0])


def state(result):
    return {key: int(result[external], 16) for key, external in
            (("pc", "PC"), ("a", "A"), ("x", "X"), ("y", "Y"), ("sp", "S"), ("p", "P"))} | {
                "mpr": [int(x["value"], 16) for x in sorted(result["MPR"], key=lambda x: x["index"])]}


def run(args):
    exe = args.exe.resolve()
    if not exe.is_relative_to(ROOT / ".deps"):
        raise ValueError("Use a dedicated portable executable under this checkout's .deps directory")
    if not exe.is_file() or not args.probe.is_file():
        raise ValueError("Missing emulator/probe; see docs/REFERENCE.md")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "result.json").write_text(json.dumps({"schema": 1, "result": "incomplete",
                                                    "note": "Only a completed run may replace this with pass"})+"\n")
    # No retail cartridge or firmware. This tiny bootstrap sets every MPR
    # deterministically before any test. Reset state in Geargrafx is randomized.
    setup = bytes.fromhex("78 D4 A9 FF 53 01 A9 F8 53 02 A9 80 53 04 A9 81 53 08 A9 82 53 10 A9 83 53 20 A9 84 53 40 80 FE")
    rom = bytearray([0xEA]*8192)
    rom[:len(setup)] = setup
    rom[-2:] = bytes([0, 0xE0])
    image = args.out / "synthetic.pce"
    image.write_bytes(rom)
    (exe.parent / "portable.ini").touch(exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    command = [str(exe), "--headless", "--portable", "--mcp-http", "--mcp-http-port", str(port)]
    started = time.monotonic()
    snapshot, cases = make_fixture(oracle=True)
    counts = {"native": 0, "interpreter": 0}
    with (args.out / "process.log").open("wb") as log:
        process = subprocess.Popen(command, cwd=exe.parent, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        client = Mcp(port)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Isolated reference exited during startup")
                try:
                    info = client.rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                                      "clientInfo": {"name": "pcenginerecomp-reference", "version": "0.1"}})
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("Reference did not initialize within the startup budget")
            client.headers["MCP-Protocol-Version"] = info["protocolVersion"]
            client.rpc("notifications/initialized")
            available = {t["name"] for t in client.rpc("tools/list")["tools"]}
            required = {"load_media", "debug_pause", "debug_step_into", "get_huc6280_status", "list_memory_areas",
                        "read_memory", "write_memory", "write_huc6280_register"}
            if not required <= available:
                raise RuntimeError("Reference lacks required tools: " + str(required-available))
            client.call("load_media", file_path=str(image.resolve()))
            client.call("debug_pause")

            def restore_mapping():
                client.call("write_huc6280_register", name="PC", value="E000")
                for _ in range(17):
                    client.call("debug_step_into")
                current = client.call("get_huc6280_status")
                if state(current)["mpr"] != list(snapshot.mpr) or current["SPEED"] != "7.16 MHz":
                    raise RuntimeError("Reference bootstrap mapping/speed mismatch")
                if current["TIMER"] or any(current[key] for key in ("IRQ1_asserted", "IRQ2_asserted", "TIQ_asserted")):
                    raise RuntimeError("Reference has active timer/interrupt state outside this check's scope")

            restore_mapping()
            areas = client.call("list_memory_areas")["areas"]
            area = next(a["id"] for a in areas if a["name"] == "SYSTEM RAM" and a["byte_size"] == 8192)
            for pc, opcode in cases:
                for variant, flags in enumerate((0x00, 0xFF, 0x55, 0xAA)):
                    if time.monotonic()-started > 180:
                        raise RuntimeError("Reference check exceeded its 180-second work budget")
                    ram = bytearray((i*37+variant*17) & 255 for i in range(8192))
                    for pa, value in snapshot.memory.items():
                        ram[pa-0x1F0000] = value
                    client.call("write_memory", area=area, offset="0000", bytes=ram.hex(" "))
                    registers = {"PC": pc, "A": (0x80+variant*43) & 255,
                                 "X": (0xFF-variant*61) & 255, "Y": variant*67,
                                 "S": (0, 1, 254, 255)[variant], "P": flags}
                    for name, value in registers.items():
                        client.call("write_huc6280_register", name=name, value=f"{value:X}")
                    before = state(client.call("get_huc6280_status"))
                    if any(before[k] != registers[v] for k, v in (("pc", "PC"), ("a", "A"), ("x", "X"), ("y", "Y"), ("sp", "S"), ("p", "P"))):
                        raise RuntimeError("Reference register setup was not applied exactly")
                    client.call("debug_step_into")
                    expected = state(client.call("get_huc6280_status"))
                    expected["ram"] = bytes.fromhex(client.call("read_memory", area=area, offset="0000", size=8192)["data"]).hex()
                    for tier in ("native", "interpreter"):
                        result = subprocess.run([str(args.probe.resolve()), *[str(registers[k]) for k in ("PC", "A", "X", "Y", "S", "P")],
                                                 str(variant), tier], capture_output=True, text=True, check=True, timeout=5)
                        actual = json.loads(result.stdout)
                        if actual != expected:
                            mismatch = {k: {"actual": actual.get(k), "expected": expected[k]} for k in expected if actual.get(k) != expected[k]}
                            # Retain one synthetic failing case, never a full trace.
                            (args.out / "failure.json").write_text(json.dumps({"opcode": opcode, "variant": variant, "tier": tier,
                                                                            "mismatch": mismatch}, indent=2)+"\n")
                            raise RuntimeError(f"Reference mismatch: opcode {opcode:02X}, variant {variant}, {tier}")
                        counts[tier] += 1
                    if expected["mpr"] != list(snapshot.mpr):
                        restore_mapping()
            report = {"schema": 1, "result": "pass", "oracle": info["serverInfo"],
                      "oracle_exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                      "opcodes": len(cases), "variants_per_opcode": 4, "comparisons": counts,
                      "scope": "single-step registers, flags, PC, MPRs and all 8 KiB work RAM; synthetic code only",
                      "not_checked": ["cycles/bus phases", "IRQ delivery", "video/audio", "CD", "gameplay"]}
            (args.out / "result.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
            print(json.dumps(report, indent=2))
        finally:
            # Terminate only the child process created by this invocation.
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / ".local/geargrafx-check")
    arguments = parser.parse_args()
    try:
        run(arguments)
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
