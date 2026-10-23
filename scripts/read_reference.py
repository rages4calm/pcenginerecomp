"""Bounded READ(6) checks against an isolated Geargrafx child.

All media and guest programs are authored here. Sector payloads are checked in
full; settled observations deliberately do not qualify seek timing or individual
bus access phases. No owner firmware, disc, save, or settings are loaded.
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from generate_scsi_fixture import make_fixture
from scripts.reference_geargrafx import Mcp, state
from scripts.scsi_reference import cd_state
from scripts.raster_reference import delay_program

STREAM = 65536
SETTLE = 1_400_000  # 8.4 million master ticks at high CPU speed.


def sector(lba):
    return bytes((lba * 29 + offset * 17 + (offset >> 8) * 7 + 0x53) & 255
                 for offset in range(2048))


def media(out):
    """A cooked MODE1 image avoids making claims about EDC/ECC decoding."""
    out.mkdir(parents=True, exist_ok=True)
    setup = bytes.fromhex("78 D4 A9 FF 53 01 A9 F8 53 02 A9 80 53 04 A9 81 53 08 A9 82 53 10 A9 83 53 20 A9 84 53 40 80 FE")
    bios = bytearray([0xEA] * 262144)
    bios[:len(setup)] = setup
    bios[8190:8192] = bytes((0, 0xE0))
    contents = {"synthetic-read.bin": b"".join(sector(lba) for lba in range(24)),
                "synthetic-read.cue": b'FILE "synthetic-read.bin" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n',
                "synthetic-syscard.pce": bytes(bios)}
    for name, data in contents.items():
        path = out / name
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError("Existing authored READ input differs; use a new output folder")
        else:
            path.write_bytes(data)
    return out / "synthetic-read.cue", out / "synthetic-syscard.pce"


def plans():
    _, cases = make_fixture()
    sites = {(op, address): pc for pc, op, address in cases}

    def access(address, value=-1, nops=0):
        return sites[0xAD if value < 0 else 0x8D, address], value, nops

    def command(lba, count, high=0):
        ops = [access(0x1802, 0x60), access(0x1800, 0, 12510)]
        for i, byte in enumerate((8, high | (lba >> 16), (lba >> 8) & 255, lba & 255, count, 0)):
            ops += [access(0x1801, byte), access(0x1802, 0xE0),
                    access(0x1802, 0x60, 510 if i < 5 else 0)]
        return ops

    finish = [access(0x1800, nops=510), access(0x1800), access(0x1801),
              access(0x1802, 0xE0), access(0x1802, 0x60, 260),
              access(0x1800), access(0x1801), access(0x1802, 0xE0),
              access(0x1802, 0x60, 260), access(0x1800)]
    definitions = [
        ("read-one-manual", command(0, 1) + [(STREAM, 0, SETTLE)] + finish, [0]),
        ("read-one-auto-high-cdb-bits", command(1, 1, 0xE0) + [(STREAM, 1, SETTLE)] + finish, [1]),
        ("read-two-auto-backpressure", command(2, 2) + [(STREAM, 1, SETTLE),
             access(0x1800), (STREAM, 1, SETTLE)] + finish, [2, 3]),
        ("read-two-manual-backpressure", command(4, 2) + [(STREAM, 0, SETTLE),
             access(0x1800), (STREAM, 0, SETTLE)] + finish, [4, 5]),
        ("read-cross-leadout-check-condition", command(23, 2) + [(STREAM, 0, SETTLE),
             access(0x1800, nops=SETTLE), access(0x1800), access(0x1801)], [23]),
        ("read-count-zero-reset-pending", command(0, 0) + [access(0x1804, 2),
             access(0x1804, 0, SETTLE), access(0x1800), access(0x1801)], []),
        ("read-reset-buffered", command(0, 2) + [access(0x1800, nops=SETTLE),
             access(0x1804, 2), access(0x1804, 0, SETTLE), access(0x1800), access(0x1801)], []),
    ]
    return [{"id": name, "seed": i, "a": 0, "x": 0, "y": 0,
             "sp": 255, "p": 4, "steps": ops, "sectors": sectors}
            for i, (name, ops, sectors) in enumerate(definitions)]


def stream_program(automatic):
    """Eight authored 256-byte loops; no self-modifying code or block opcodes."""
    program = bytearray()
    for page in range(8):
        program += bytes((0xA2, 0))  # LDX #0
        start = len(program)
        program += bytes((0xAD, 8 if automatic else 1, 0x18,
                          0x9D, 0, 0x20 + page))
        if not automatic:
            program += bytes.fromhex("A9 E0 8D 02 18 A9 60 8D 02 18")
        program += bytes((0xE8, 0xD0, (start - (len(program) + 3)) & 255))
    # Allow automatic ACK to fall before observing settled port state.
    return bytes(program) + bytes((0xEA,)) * 8


def run(args):
    exe, probe, out = args.exe.resolve(), args.probe.resolve(), args.out.resolve()
    if not exe.is_relative_to(ROOT / ".deps") or not exe.is_file() or not probe.is_file():
        raise ValueError("Use existing project-local .deps Geargrafx and compiled READ probe")
    if not 1 <= args.shard_count <= 16 or not 0 <= args.shard_index < args.shard_count:
        raise ValueError("Invalid shard bounds")
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text('{"result":"incomplete"}\n')
    image, bios = media(out.parent / "read-media")
    selected = plans()[args.shard_index::args.shard_count]
    if not selected:
        raise ValueError("Empty READ shard")
    (exe.parent / "portable.ini").touch(exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    started = time.monotonic()
    snapshot, cases = make_fixture()
    sites = {(op, address): pc for pc, op, address in cases}
    counts = {tier: {"states": 0, "sectors": 0, "payload_bytes": 0,
                     "native_steps": 0, "interpreter_steps": 0} for tier in ("native", "interpreter")}
    with (out / "process.log").open("wb") as log:
        process = subprocess.Popen([str(exe), "--headless", "--portable", "--mcp-http", "--mcp-http-port", str(port)],
            cwd=exe.parent, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        client = Mcp(port)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Isolated reference exited")
                try:
                    info = client.rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": {"name": "pcenginerecomp-read-reference", "version": "0.1"}})
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("Reference startup exceeded budget")
            client.headers["MCP-Protocol-Version"] = info["protocolVersion"]
            client.rpc("notifications/initialized")
            client.call("load_bios", file_path=str(bios), type="syscard")
            client.call("load_media", file_path=str(image))
            client.call("debug_pause")
            client.call("write_huc6280_register", name="PC", value="E000")
            for _ in range(17):
                client.call("debug_step_into")
            tracks = client.call("list_cdrom_tracks")
            if (tracks["track_count"], tracks["sector_count"]) != (1, 24):
                raise RuntimeError("Authored READ geometry differs")
            areas = client.call("list_memory_areas")["areas"]
            ram_area = next(a["id"] for a in areas if a["name"] == "SYSTEM RAM" and a["byte_size"] == 8192)

            def guard():
                if time.monotonic() - started > 180 or (out / "process.log").stat().st_size > 256 * 1024:
                    raise RuntimeError("READ reference exceeded time or diagnostic budget")

            def execute(pc, value=-1):
                client.call("write_huc6280_register", name="PC", value=f"{pc:X}")
                if value >= 0:
                    client.call("write_huc6280_register", name="A", value=f"{value:X}")
                client.call("debug_step_into")

            def run_code(code):
                client.call("write_memory", area=ram_area, offset="1000", bytes=code.hex(" "))
                client.call("write_huc6280_register", name="PC", value="3000")
                endpoint = f"{0x3000 + len(code):04X}"
                client.call("debug_run_to_cursor", address=endpoint)
                for _ in range(100):
                    position = client.call("debug_get_status")
                    if position["paused"] and position["pc"] == endpoint:
                        return
                    time.sleep(0.01)
                raise RuntimeError("Finite READ guest program failed to stop")

            def restore(cpu):
                for name, key in (("PC", "pc"), ("A", "a"), ("X", "x"), ("Y", "y"), ("S", "sp"), ("P", "p")):
                    client.call("write_huc6280_register", name=name, value=f"{cpu[key] & (~0x20 if key == 'p' else 65535):X}")

            def settle(nops):
                if nops:
                    cpu = state(client.call("get_huc6280_status"))
                    while nops:
                        part = min(nops, 100000)
                        run_code(delay_program(part * 6))
                        nops -= part
                    restore(cpu)

            payload_hashes = []
            for plan in selected:
                guard()
                ram = bytearray((i * 37 + plan["seed"] * 17) & 255 for i in range(8192))
                for pa, value in snapshot.memory.items():
                    ram[pa - 0x1F0000] = value
                client.call("write_memory", area=ram_area, offset="0000", bytes=ram.hex(" "))
                client.call("write_huc6280_register", name="PC", value="2700")
                for _ in range(16):
                    client.call("debug_step_into")
                for address, value in ((0x1807, 128), (0x1804, 2), (0x1804, 0), (0x1802, 0)):
                    execute(sites[0x8D, address], value)
                restore({k: plan[k] for k in ("a", "x", "y", "sp", "p")} | {"pc": plan["steps"][0][0]})
                cpu_setup = client.call("get_huc6280_status")
                if state(cpu_setup)["mpr"] != list(snapshot.mpr) or cpu_setup["SPEED"] != "7.16 MHz" or cpu_setup["TIMER"]:
                    raise RuntimeError("Reference mapping/speed/timer differs")
                expected = []
                streamed = 0
                for pc, value, nops in plan["steps"]:
                    guard()
                    payload = None
                    if pc == STREAM:
                        settle(nops)
                        before = state(client.call("get_huc6280_status"))
                        run_code(stream_program(bool(value)))
                        payload = bytes.fromhex(client.call("read_memory", area=ram_area, offset="0000", size=2048)["data"])
                        wanted = sector(plan["sectors"][streamed])
                        if payload != wanted:
                            raise RuntimeError(f"Authored READ payload differs: {plan['id']} sector {streamed}")
                        streamed += 1
                        payload_hashes.append(hashlib.sha256(payload).hexdigest())
                        restore(before)
                    else:
                        execute(pc, value)
                        settle(nops)
                    cpu = client.call("get_huc6280_status")
                    row = {"cpu": state(cpu), "cd": cd_state(client.call("get_cdrom_status"), cpu)}
                    if payload is not None:
                        row["payload"] = payload.hex()
                    expected.append(row)
                plan_path = out / "sequence.txt"
                header = [plan[k] for k in ("seed", "a", "x", "y", "sp", "p")] + [len(plan["steps"])]
                plan_path.write_text(" ".join(map(str, header)) + "\n" + "".join(f"{pc} {value} {nops}\n" for pc, value, nops in plan["steps"]), encoding="ascii")
                for tier in counts:
                    actual = json.loads(subprocess.run([str(probe), "--probe", str(plan_path), tier],
                        capture_output=True, text=True, check=True, timeout=30).stdout)
                    if actual["states"] != expected:
                        mismatch = next((i for i, (a, b) in enumerate(zip(actual["states"], expected)) if a != b), -1)
                        (out / "failure.json").write_text(json.dumps({"plan": plan["id"], "tier": tier,
                            "index": mismatch, "actual": actual["states"][mismatch], "expected": expected[mismatch]}, indent=2) + "\n")
                        raise RuntimeError(f"READ reference mismatch: {plan['id']}, {tier}, action {mismatch}")
                    if (actual["native_steps"] == 0) == (tier == "native") or (actual["interpreter_steps"] == 0) == (tier == "interpreter"):
                        raise RuntimeError("READ probe executed the wrong route")
                    counts[tier]["states"] += len(expected)
                    counts[tier]["sectors"] += streamed
                    counts[tier]["payload_bytes"] += streamed * 2048
                    for key in ("native_steps", "interpreter_steps"):
                        counts[tier][key] += actual[key]
                print(f"Qualified {plan['id']}: {len(expected)} checkpoints, {streamed} full sectors", flush=True)
            report = {"schema": 1, "result": "pass", "oracle": info["serverInfo"],
                "oracle_exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                "probe_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(),
                "checked_sequences": [p["id"] for p in selected], "comparisons": counts,
                "payload_sha256": payload_hashes,
                "authored_inputs_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (image, bios, image.with_suffix('.bin'))},
                "scope": "Full authored 2048-byte READ payloads and settled CPU/observable CD states; manual/auto ACK, multisector backpressure, high CDB bits, reset and crossing leadout",
                "not_checked": ["Exact seek, initial jitter or access-phase timing", "ECC/EDC decoding", "IRQ delivery", "Hardware", "Owner game or firmware"]}
            (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report, indent=2))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    run(parser.parse_args())
