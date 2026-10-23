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
from pcerecomp.isa import BIT_OPCODES, STACK_OPCODES, DATA_OPCODES, RMW_OPCODES, INDIRECT_JUMP_OPCODES, TEST_OPCODES, BIT_BRANCH_OPCODES, _ROWS


def vectors_for_opcode(opcode):
    """Directed inputs for each supported instruction family."""
    if opcode in TEST_OPCODES | BIT_BRANCH_OPCODES | {0x44}:
        values = (0, 255, 0x55, 0xAA, 0x40, 0x80, 0xC0, 1)
        return [{"variant": i, "seed": i, "flags": (4, 255, 0x55, 0xAE)[i%4],
                 "sp": (0, 1, 254, 255)[i%4], "a": 255 if i&1 else 0,
                 "x": (0, 1, 0xE0, 0xFF)[(i//2)%4], "y": 0xA7,
                 "patch": None, "operand": values[i//2]} for i in range(16)]
    if opcode in RMW_OPCODES | INDIRECT_JUMP_OPCODES:
        values = (0, 1, 2, 0x7F, 0x80, 0x81, 0xFE, 0xFF)
        return [{"variant": i, "seed": i, "flags": (0x06, 0xDE, 0x96, 0x4E)[(i//2)%4] |
                 (i&1) | ((i&2)<<4), "sp": 255, "a": values[i//2],
                 "x": (0, 1, 0xE0, 0xFF)[(i//2)%4], "y": 0xA7,
                 "patch": None, "operand": values[i//2],
                 "target": (0x2000, 0x20FF, 0x3000, 0x3FFF, 0x4000, 0x7FFF, 0xE000, 0xFFFF)[i//2]}
                for i in range(16)]
    if opcode in DATA_OPCODES:
        values = (0x00, 0x01, 0x09, 0x0A, 0x7F, 0x80, 0x99, 0xFF,
                  0x50, 0x49, 0x90, 0xF0, 0x0F, 0xFA, 0x10, 0xFF)
        return [{"variant": i, "seed": i, "flags": 0x96 | (i&1) | ((i&2)<<2) |
                 ((i&4)<<3) | ((i&8)<<3), "sp": (0, 1, 254, 255)[i%4],
                 "a": values[i], "x": (0, 1, 0xE0, 0xFF)[i%4],
                 "y": (0, 0xFF, 1, 0xE0)[i%4], "patch": None,
                 "operand": values[15-i], "left": values[(i+5)%16]}
                for i in range(16)]
    result = []
    for variant, flags in enumerate((0x00, 0xFF, 0x55, 0xAA)):
        sp = (0, 1, 254, 255)[variant]
        patch = None
        if opcode in BIT_OPCODES:
            patch = (0x20, (0x00, 0xFF, 0x55, 0xAA)[variant])
        elif opcode in (0x28, 0x68, 0x7A, 0xFA):
            patch = (0x100 + ((sp+1) & 255), (0x00, 0x7F, 0x80, 0xFF)[variant])
        result.append({"variant": variant, "seed": variant, "flags": flags, "sp": sp,
                       "a": (0x80+variant*43) & 255, "x": (0xFF-variant*61) & 255,
                       "y": variant*67, "patch": patch})
    if opcode in STACK_OPCODES:
        for variant, value in enumerate((0x00, 0x7F, 0x80, 0xFF)):
            sp = (0, 1, 254, 255)[variant]
            patch = None
            if opcode in (0x28, 0x68, 0x7A, 0xFA):
                pulled = (0x20, 0x10, 0xEF, 0xCF)[variant] if opcode==0x28 else value
                patch = (0x100 + ((sp+1) & 255), pulled)
            result.append({"variant": variant+4, "seed": variant+4, "flags": 0xE7,
                           "sp": sp, "a": value, "x": value, "y": value, "patch": patch})
    return result


def patches_for_vector(opcode, vector):
    """Input bytes only; identical overrides go to both independent processes.

    Pointer setup follows the T byte so idx's high-byte/T-destination alias
    remains a valid pointer and explicitly exercises that alias.
    """
    patches = [] if vector["patch"] is None else [vector["patch"]]
    if opcode==0x44:
        return []
    if opcode in BIT_BRANCH_OPCODES:
        return [(255, vector["operand"])]
    if opcode in TEST_OPCODES:
        mode = _ROWS[opcode].split(".")[1]
        if mode=="imm": return []
        target = (255+vector["x"])&255 if mode in ("zpx","izx") else 255 if mode in ("zpg","imz") else 0x2FF+vector["x"] if mode in ("abx","imx") else 0x2FF
        return [(target, vector["operand"])]
    if opcode in INDIRECT_JUMP_OPCODES:
        pointer = 0x2FF + (vector["x"] if opcode==0x7C else 0)
        return [(pointer, vector["target"]&255), (pointer+1, vector["target"]>>8)]
    if opcode in RMW_OPCODES:
        mode = _ROWS[opcode].split(".")[1]
        if mode in ("imp", "acc"):
            return []
        target = {"zpg": 255, "zpx": (255+vector["x"])&255,
                  "abs": 0x2FF, "abx": 0x2FF+vector["x"]}[mode]
        return [(target, vector["operand"])]
    if opcode not in DATA_OPCODES:
        return patches
    mnemonic, mode = _ROWS[opcode].split(".")
    if mnemonic in ("ORA", "AND", "EOR", "ADC") and vector["flags"] & 0x20:
        patches.append((vector["x"], vector["left"]))
    if mode == "imm":
        return patches  # Immediate is source guarded: keep its compiled 0x20.
    if mode in ("idx", "idy", "zpi"):
        pointer = (0xFF+vector["x"]) & 255 if mode == "idx" else 0xFF
        patches += [(pointer, 0xFF), ((pointer+1)&255, 0x22)]
        target = 0x2FF + (vector["y"] if mode == "idy" else 0)
    else:
        target = {"zpg": 0xFF, "zpx": (0xFF+vector["x"])&255,
                  "zpy": (0xFF+vector["y"])&255, "abs": 0x2FF,
                  "abx": 0x2FF+vector["x"], "aby": 0x2FF+vector["y"]}[mode]
    patches.append((target, vector["operand"]))
    return patches


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
    if not 1 <= args.shard_count <= 32 or not 0 <= args.shard_index < args.shard_count:
        raise ValueError("Require 1..32 shards and 0 <= shard-index < shard-count")
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
    bios=None
    if args.suite == "cd-control":
        from scripts.cd_reference import prepare_media
        image,bios=prepare_media(args.out.parent / "synthetic-media",setup)
    (exe.parent / "portable.ini").touch(exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    command = [str(exe), "--headless", "--portable", "--mcp-http", "--mcp-http-port", str(port)]
    started = time.monotonic()
    snapshot, cases = make_fixture(oracle=True)
    if args.suite == "bit-stack":
        cases = [(pc, op) for pc, op in cases if op in BIT_OPCODES | STACK_OPCODES]
    elif args.suite == "data":
        cases = [(pc, op) for pc, op in cases if op in DATA_OPCODES]
    elif args.suite == "rmw-jump":
        cases = [(pc, op) for pc, op in cases if op in RMW_OPCODES | INDIRECT_JUMP_OPCODES]
    elif args.suite == "bit-test-bsr":
        cases = [(pc, op) for pc, op in cases if op in TEST_OPCODES | BIT_BRANCH_OPCODES | {0x44}]
    suite_opcodes = len(cases)
    cases = cases[args.shard_index::args.shard_count]
    if not cases:
        raise ValueError("Selected shard has no opcodes")
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
            if args.suite == "speed":
                required |= {"set_trace_log", "get_trace_log"}
            if args.suite == "cd-control":
                required |= {"load_bios", "get_cdrom_status", "get_media_info"}
            if args.suite == "vdc":
                required |= {"get_huc6270_registers", "write_huc6270_register", "get_media_info"}
            if not required <= available:
                raise RuntimeError("Reference lacks required tools: " + str(required-available))
            if bios is not None:
                client.call("load_bios",file_path=str(bios.resolve()),type="syscard")
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
            if args.suite == "cd-control":
                from scripts.cd_reference import run_cd_matrix
                run_cd_matrix(client,areas,args,started,info)
                return
            if args.suite == "vdc":
                from scripts.vdc_reference import run_vdc_matrix
                run_vdc_matrix(client, areas, args, started, info)
                return
            if args.suite == "mpr":
                from scripts.mpr_reference import run_mpr_matrix
                run_mpr_matrix(client, area, snapshot, args, started, info)
                return
            if args.suite == "speed":
                from scripts.speed_reference import run_speed_matrix
                run_speed_matrix(client, area, snapshot, args, started, info)
                return
            for pc, opcode in cases:
                for vector in vectors_for_opcode(opcode):
                    variant, flags, seed = vector["variant"], vector["flags"], vector["seed"]
                    if time.monotonic()-started > 180:
                        raise RuntimeError("Reference check exceeded its 180-second work budget")
                    ram = bytearray((i*37+seed*17) & 255 for i in range(8192))
                    for pa, value in snapshot.memory.items():
                        ram[pa-0x1F0000] = value
                    patches = patches_for_vector(opcode, vector)
                    for offset, value in patches:
                        ram[offset] = value
                    client.call("write_memory", area=area, offset="0000", bytes=ram.hex(" "))
                    registers = {"PC": pc, "A": vector["a"], "X": vector["x"], "Y": vector["y"],
                                 "S": vector["sp"], "P": flags}
                    for name, value in registers.items():
                        client.call("write_huc6280_register", name=name, value=f"{value:X}")
                    before = state(client.call("get_huc6280_status"))
                    if any(before[k] != registers[v] for k, v in (("pc", "PC"), ("a", "A"), ("x", "X"), ("y", "Y"), ("sp", "S"), ("p", "P"))):
                        raise RuntimeError("Reference register setup was not applied exactly")
                    client.call("debug_step_into")
                    expected = state(client.call("get_huc6280_status"))
                    expected["ram"] = bytes.fromhex(client.call("read_memory", area=area, offset="0000", size=8192)["data"]).hex()
                    for tier in ("native", "interpreter"):
                        probe_command = [str(args.probe.resolve()), *[str(registers[k]) for k in ("PC", "A", "X", "Y", "S", "P")], str(seed), tier]
                        probe_command += [str(value) for patch in patches for value in patch]
                        result = subprocess.run(probe_command, capture_output=True, text=True, check=True, timeout=5)
                        actual = json.loads(result.stdout)
                        if actual != expected:
                            mismatch = {k: {"actual": actual.get(k), "expected": expected[k]} for k in expected if actual.get(k) != expected[k]}
                            # Retain one synthetic failing case, never a full trace.
                            (args.out / "failure.json").write_text(json.dumps({"opcode": opcode, "variant": variant, "tier": tier,
                                                                            "mismatch": mismatch}, indent=2)+"\n")
                            raise RuntimeError(f"Reference mismatch: opcode {opcode:02X}, variant {variant}, {tier}")
                        counts[tier] += 1
                    if expected["mpr"] != list(snapshot.mpr) or opcode in (0x54,0xD4):
                        restore_mapping()
                if sum(counts.values()) % 256 == 0:
                    print(f"Compared {counts['native']} cases per tier", file=sys.stderr, flush=True)
            report = {"schema": 1, "result": "pass", "oracle": info["serverInfo"],
                      "oracle_exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                      "suite": args.suite, "opcodes": len(cases),
                      "suite_opcodes": suite_opcodes,
                      "shard": {"index": args.shard_index, "count": args.shard_count},
                      "checked_opcodes": [op for _, op in cases],
                      "variants": {"data_opcode": 16, "rmw_or_indirect_jump_opcode": 16,
                                   "test_bit_branch_or_bsr_opcode": 16,
                                   "stack_opcode": 8, "other_opcode": 4},
                      "comparisons": counts,
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
    parser.add_argument("--suite", choices=("all", "bit-stack", "data", "rmw-jump", "bit-test-bsr", "mpr", "speed", "cd-control", "vdc"), default="all")
    parser.add_argument("--shard-index", type=int, default=0, help="Zero-based shard index")
    parser.add_argument("--shard-count", type=int, default=1, help="Partition opcode coverage into bounded runs")
    arguments = parser.parse_args()
    try:
        run(arguments)
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
