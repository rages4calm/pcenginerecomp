"""Exact-clock raster checks using authored code in an isolated Geargrafx child.

The emulator executes finite CPU loops to advance time. No rendered frame,
retail program, firmware, owner settings, or save is used. Device checks are
separate from instruction-boundary CPU integration expectations.
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
from scripts.reference_geargrafx import Mcp

H_STATES = {name: i for i, name in enumerate(("HDS", "HDW", "HDE", "HSW"))}
V_STATES = {name: i for i, name in enumerate(("VDS", "VDW", "VCR", "VSW"))}


def delay_program(ticks, divisor=3):
    """Finite HuC6280 loop: outer iteration 1542 cycles, NOP two cycles.

    LDY #n; [LDX #0; DEX; BNE -3; DEY; BNE -8] costs n*1542
    cycles including the final untaken branch and initial LDY. Maximum output
    is 781 bytes and maximum time is two default video frames.
    """
    if divisor not in (3, 12) or not 0 <= ticks <= 2 * 1365 * 263 or ticks % (2 * divisor):
        raise ValueError("Delay requires a bounded even number of CPU cycles")
    cycles = ticks // divisor
    outer, rest = divmod(cycles, 1542)
    if outer > 255:
        raise ValueError("Delay outer loop exceeds one byte")
    code = bytes((0xA0, outer, 0xA2, 0, 0xCA, 0xD0, 0xFD, 0x88, 0xD0, 0xF8)) if outer else b""
    return code + bytes((0xEA,)) * (rest // 2)


def plans():
    result = []
    # Deliberately include display-off, short/zero vertical phases, delayed
    # horizontal display, masked interrupts, and maximum VDR width.
    for name, hsr, hdr, vsr, vdr, vcr in (
        ("standard", 0x0202, 0x041F, 0x0F02, 239, 4),
        ("short", 0, 0x001F, 0, 0, 0),
        ("narrow", 0x0000, 0x0000, 0x0301, 7, 2),
        ("delayed", 0x0603, 0x0217, 0x0503, 31, 0),
        ("tall", 0x0101, 0x001F, 0x0000, 511, 255),
    ):
        for cr in (0, 0x0C, 0x8C):
            registers = [0] * 20
            for index, value in ((5, cr), (6, 67), (10, hsr), (11, hdr),
                                 (12, vsr), (13, vdr), (14, vcr)):
                registers[index] = value
            # Capture startup and two settled frames. Fixed master-clock
            # checkpoints sample both sides of horizontal/vertical edges.
            times = {24, 24 + 6, 24 + 48, 24 + 96, 24 + 192, 24 + 1362, 24 + 1368}
            frame = 1365 * 262
            for line in (0, 1, 2, 3, 5, 8, 10, 16, 17, 18, 19, 20, 31, 32, 33,
                         35, 36, 37, 240, 241, 242, 255, 256, 257, 258, 259, 260, 261):
                for x in (0, 90, 96, 120, 128, 192, 1008, 1092, 1098, 1362):
                    absolute = frame + line * 1365 + x
                    times.add(24 + ((absolute - 24) // 6) * 6)
            # Acknowledge well inside a line. The previous final sample was
            # immediately before line wrap, where a valid new RCR event may
            # arrive between the CPU's read phase and instruction completion.
            times.add(2 * frame + 600)
            result.append({"id": f"{name}-cr-{cr:02x}", "registers": registers,
                           "times": sorted(times)})
    return result


def observed(client):
    vce = client.call("get_huc6260_status")
    vdc = client.call("get_huc6270_status", vdc=1)
    cpu = client.call("get_huc6280_status")
    rows = client.call("get_huc6270_registers", vdc=1)["registers"]
    if rows[-1][0] != "SR":
        raise RuntimeError("Unexpected VDC status-register schema")
    return {"hclock": vce["x"], "line": vce["y"], "dot": vdc["x"],
            "vdc_line": vdc["y"], "h_state": H_STATES[vdc["h_state"]],
            "v_state": V_STATES[vdc["v_state"]], "status": int(rows[-1][1], 16),
            "irq1": cpu["IRQ1_asserted"]}


def run(args):
    exe, probe, out = args.exe.resolve(), args.probe.resolve(), args.out.resolve()
    if not exe.is_relative_to(ROOT / ".deps") or not exe.is_file() or not probe.is_file():
        raise ValueError("Require a dedicated .deps portable emulator and built raster probe")
    if not 1 <= args.shard_count <= 32 or not 0 <= args.shard_index < args.shard_count:
        raise ValueError("Invalid shard")
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps({"result": "incomplete"}) + "\n")
    rom = bytearray([0xEA] * 8192)
    # CSH nine clocks, then TAM #1 fifteen clocks. This permits a real guest
    # status-port read at the end while keeping every observed phase exact.
    rom[:3] = bytes((0xD4, 0x53, 1))
    rom[16:19] = bytes((0xAD, 0, 0))
    rom[-2:] = bytes((0, 0xE0))
    image = out / "synthetic-raster.pce"
    image.write_bytes(rom)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = [str(exe), "--headless", "--portable", "--mcp-http", "--mcp-http-port", str(port)]
    started = time.monotonic()
    selected = plans()[args.shard_index::args.shard_count]
    if not selected:
        raise ValueError("Empty shard")
    checkpoints = 0
    summaries = []
    with (out / "process.log").open("wb") as log:
        process = subprocess.Popen(command, cwd=exe.parent, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        client = Mcp(port)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Reference exited at startup")
                try:
                    info = client.rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": {"name": "pcerecomp-raster-reference", "version": "1"}})
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("Reference startup timeout")
            client.headers["MCP-Protocol-Version"] = info["protocolVersion"]
            client.rpc("notifications/initialized")
            for plan in selected:
                # One bounded plan per shard is the recommended live use.
                # An unsharded invocation is also finite: 180 seconds per
                # selected plan, plus the shared startup budget.
                deadline = min(time.monotonic() + 180, started + 180 * len(selected) + 5)
                client.call("load_media", file_path=str(image))
                client.call("debug_pause")
                media = client.call("get_media_info")
                if media["is_sgx"] or media["is_cdrom"] or media["rom_size"] != 8192:
                    raise RuntimeError("Unexpected reference hardware profile")
                initial = observed(client)
                if any(initial[key] for key in ("hclock", "line", "dot", "vdc_line", "status", "irq1")):
                    raise RuntimeError("Reference did not start at reset phase")
                area = next(a["id"] for a in client.call("list_memory_areas")["areas"] if a["name"] == "ROM")
                for index, value in enumerate(plan["registers"]):
                    client.call("write_huc6270_register", register=index, value=f"{value:04X}", vdc=1)
                client.call("write_huc6280_register", name="P", value="04")
                client.call("write_huc6280_register", name="PC", value="E000")
                client.call("debug_step_into")
                client.call("write_huc6280_register", name="A", value="FF")
                client.call("debug_step_into")
                elapsed = 24
                expected = []
                for target in plan["times"]:
                    if time.monotonic() > deadline:
                        raise RuntimeError("Raster plan exceeded its 180-second work budget")
                    if (out / "process.log").stat().st_size > 256 * 1024:
                        raise RuntimeError("Reference process diagnostics exceeded 256 KiB")
                    if target != elapsed:
                        code = delay_program(target - elapsed)
                        client.call("write_memory", area=area, offset="0100", bytes=code.hex(" "))
                        client.call("write_huc6280_register", name="PC", value="E100")
                        end = f"{0xE100 + len(code):04X}"
                        client.call("debug_run_to_cursor", address=end)
                        # Run-to-cursor schedules execution; fast headless
                        # loops often finish before the response, while
                        # display-enabled loops can still be running.
                        for _ in range(100):
                            position = client.call("debug_get_status")
                            if position["paused"] and position["pc"] == end:
                                break
                            time.sleep(0.01)
                        if not position["paused"] or position["pc"] != end:
                            raise RuntimeError("Finite raster delay failed to stop at its endpoint")
                    value = observed(client)
                    if value["hclock"] != target % 1365 or value["line"] != (target // 1365) % 262:
                        raise RuntimeError("Authored delay/master-clock observation disagreement")
                    expected.append(value)
                    elapsed = target
                client.call("write_huc6280_register", name="PC", value="E010")
                client.call("debug_step_into")
                ack = {"value": int(client.call("get_huc6280_status")["A"], 16),
                       "state": observed(client)}
                path = out / "clock-plan.txt"
                path.write_text(" ".join(map(str, plan["registers"])) + "\n" +
                                str(len(plan["times"])) + "\n" +
                                "\n".join(map(str, plan["times"])) + "\n", encoding="ascii")
                result = subprocess.run([str(probe), "--clock", str(path)], capture_output=True, text=True,
                                        timeout=10, check=True)
                actual = json.loads(result.stdout)["states"]
                if actual != expected:
                    mismatch = [{"time": t, "actual": a, "expected": e} for t, a, e in
                                zip(plan["times"], actual, expected) if a != e]
                    (out / "failure.json").write_text(json.dumps({"plan": plan["id"], "mismatch": mismatch[:8],
                        "actual_count": len(actual), "expected_count": len(expected)}, indent=2) + "\n")
                    raise RuntimeError(f'Exact-clock raster mismatch: {plan["id"]}')
                actual_ack = json.loads(result.stdout)["ack"]
                if actual_ack != ack:
                    (out / "failure.json").write_text(json.dumps({"plan": plan["id"], "ack": {
                        "actual": actual_ack, "expected": ack}}, indent=2) + "\n")
                    raise RuntimeError(f'Raster status acknowledgement mismatch: {plan["id"]}')
                checkpoints += len(expected)
                summaries.append({"plan": plan["id"], "states": len(expected),
                                  "vblank_observed": any(x["status"] & 32 for x in expected),
                                  "rcr_observed": any(x["status"] & 4 for x in expected)})
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    report = {"schema": 1, "result": "pass", "suite": "raster", "oracle": info["serverInfo"],
              "oracle_exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
              "probe_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(), "checkpoints": checkpoints,
              "shard": {"index": args.shard_index, "count": args.shard_count}, "plans": summaries,
              "profile": {"single_vdc": True, "vce_divider": 4, "frame_lines": 262},
              "scope": "Exact elapsed master clocks, VCE/VDC positions, horizontal/vertical states, sticky VBlank/RCR flags and IRQ1; one stable guest status acknowledgement per plan; authored finite CPU delays",
              "not_checked": ["CPU sub-instruction port timing", "CPU IRQ delivery", "rendering", "DMA", "hardware qualification", "gameplay"]}
    (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / ".local/raster-check/live")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    arguments = parser.parse_args()
    try:
        run(arguments)
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
