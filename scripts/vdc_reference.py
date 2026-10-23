"""Settled functional VDC checks against an isolated Geargrafx instance.

Every observed operation is followed by sixteen authored NOPs. This deliberately
compares completed port effects, not the asynchronous VRAM busy interval,
contention, raster status, rendering, or instruction/device timing.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from generate_vdc_fixture import make_fixture


def vdc_state(result):
    """Read debugger state without touching guest ports or acknowledging IRQs."""
    rows = result["registers"]
    if [row[0] for row in rows] != list(range(20)) + ["AR", "SR"]:
        raise RuntimeError("Unexpected Geargrafx VDC register schema")
    values = [int(row[1], 16) for row in rows]
    return {"selected": values[20], "registers": values[:20]}


def plans():
    _, cases = make_fixture()
    sites = {(op, value): pc for pc, op, value in cases}

    def st(port, value):
        return sites[(3, 19, 35)[port], value], -1

    def access(port, value=-1, mirror=False):
        return sites[0xAD if value < 0 else 0x8D,
                     (0xA3FC if mirror else 0xA000) + port], value

    result = []

    def append(name, operations):
        i = len(result)
        result.append({"id": name, "seed": i, "a": (i * 43 + 0x80) & 255,
                       "x": (i * 37) & 255, "y": (i * 67) & 255,
                       "sp": (0, 1, 254, 255)[i % 4], "p": (0, 255)[i % 2],
                       "steps": operations})

    # Both byte lanes of every selector, including the twelve invalid values.
    # Keep live display/IRQ and automatic DMA disabled. Internal tests exercise
    # every mask bit separately without claiming a raster/video model.
    for selected in range(32):
        operations = [st(0, selected | 0xE0)]
        for value in (255, 0x55):
            low_mask = 0x30 if selected == 5 else 0x0C if selected == 15 else 255
            low = value & low_mask
            high = value & (0x18 if selected == 5 else 0x7F if selected == 1 else 255)
            operations += [st(1, low), access(1, value, mirror=True), access(1)]
            if selected not in (18, 19):
                second_low = (low ^ 0x55) & low_mask
                operations += [access(3, high, mirror=True), st(1, second_low)]
        operations += [access(0, selected, mirror=True), access(1, mirror=True)]
        append(f"selector-{selected:02x}", operations)

    for increment in range(4):
        for address in (0, 0x7FFF, 0x8000, 0xFFFF):
            value = (address ^ (increment * 0x53) ^ 0xA5) & 255
            read_address = 0 if address & 1 == 0 else 0x7D00
            operations = [st(0, 5), st(1, 0), st(2, increment << 3),
                          st(0, 0), access(2, address & 255), access(3, address >> 8, mirror=True),
                          st(0, 2), st(1, value), st(2, value ^ 255),
                          access(2, value ^ 0x55, mirror=True), access(3, value ^ 0xAA),
                          st(0, 1), st(1, read_address & 255), st(2, read_address >> 8),
                          st(0, 2), access(2), access(2, mirror=True), access(3), access(2),
                          st(0, 7), access(2, mirror=True), access(3, mirror=True), access(3),
                          st(0, 2), access(3, mirror=True), access(2),
                          access(1, value), access(1, mirror=True)]
            append(f"vram-inc-{increment}-address-{address:04x}", operations)
    return result


def run_vdc_matrix(client, areas, args, started, info):
    from scripts.reference_geargrafx import state

    snapshot, cases = make_fixture()
    sites = {(op, value): pc for pc, op, value in cases}
    ram_area = next(a["id"] for a in areas if a["name"] == "SYSTEM RAM" and a["byte_size"] == 8192)
    vram_area = next(a["id"] for a in areas if a["name"] == "VRAM" and a["byte_size"] == 65536 and a["unit_size"] == 2)
    media = client.call("get_media_info")
    if (not media["ready"] or media["is_sgx"] or media["is_cdrom"]
            or media["is_cdrom_hardware_enabled"] or media["mapper"] != "Standard"
            or media["rom_size"] != 8192):
        raise RuntimeError("Reference media/profile differs from the standard single-VDC HuCard check")
    selected = plans()[args.shard_index::args.shard_count]
    if not selected:
        raise ValueError("Selected VDC shard has no sequences")
    counts = {tier: {"states": 0, "ram_vram": 0, "native_steps": 0, "interpreter_steps": 0}
              for tier in ("native", "interpreter")}

    def execute(pc, value=-1):
        client.call("write_huc6280_register", name="PC", value=f"{pc:X}")
        if value >= 0:
            client.call("write_huc6280_register", name="A", value=f"{value:X}")
        client.call("debug_step_into")

    def settle():
        client.call("write_huc6280_register", name="PC", value="2600")
        for _ in range(16):
            client.call("debug_step_into")

    for plan in selected:
        if time.monotonic() - started > 180:
            raise RuntimeError("Reference check exceeded its 180-second work budget")
        ram = bytearray((i * 37 + plan["seed"] * 17) & 255 for i in range(8192))
        for pa, value in snapshot.memory.items():
            ram[pa - 0x1F0000] = value
        client.call("write_memory", area=ram_area, offset="0000", bytes=ram.hex(" "))
        client.call("write_huc6280_register", name="P", value="04")
        client.call("write_huc6280_register", name="PC", value="2700")
        for _ in range(16):
            client.call("debug_step_into")

        # Direct debugger writes intentionally initialize only storage. Prime
        # the hidden read buffer through real guest ports, before replacing
        # VRAM with its authored pattern; this starts both processes at zero.
        for register in range(21):
            response = client.call("write_huc6270_register", register=register, value="0000", vdc=1)
            if not response.get("success"):
                raise RuntimeError("Reference VDC initialization failed")
        client.call("write_memory", area=vram_area, offset="0000", bytes="00 00")
        execute(sites[3, 1]); execute(sites[19, 0]); execute(sites[35, 0]); settle()
        for register in (0, 1, 2, 20):
            client.call("write_huc6270_register", register=register, value="0000", vdc=1)
        vram = bytes((i * 13 + plan["seed"] * 7) & 255 for i in range(65536))
        client.call("write_memory", area=vram_area, offset="0000", bytes=vram.hex(" "))
        if vdc_state(client.call("get_huc6270_registers", vdc=1)) != {"selected": 0, "registers": [0] * 20}:
            raise RuntimeError("Reference VDC initial state differs")

        registers = {"PC": plan["steps"][0][0], "A": plan["a"], "X": plan["x"],
                     "Y": plan["y"], "S": plan["sp"], "P": plan["p"]}
        for name, value in registers.items():
            client.call("write_huc6280_register", name=name, value=f"{value:X}")
        status = client.call("get_huc6280_status")
        before = state(status)
        if (before["mpr"] != list(snapshot.mpr) or status["SPEED"] != "7.16 MHz"
                or status["TIMER"] or any(status[k] for k in ("IRQ1_asserted", "IRQ2_asserted", "TIQ_asserted"))):
            raise RuntimeError("Reference CPU mapping/speed/interrupt setup failed")
        if any(before[k] != registers[v] for k, v in (("pc", "PC"), ("a", "A"), ("x", "X"), ("y", "Y"), ("sp", "S"), ("p", "P"))):
            raise RuntimeError("Reference register setup was not applied exactly")

        expected = []
        for pc, value in plan["steps"]:
            if time.monotonic() - started > 180:
                raise RuntimeError("Reference check exceeded its 180-second work budget")
            execute(pc, value)
            next_pc = state(client.call("get_huc6280_status"))["pc"]
            settle()
            cpu = state(client.call("get_huc6280_status"))
            cpu["pc"] = next_pc
            expected.append({"cpu": cpu, "vdc": vdc_state(client.call("get_huc6270_registers", vdc=1))})
        memory = {}
        for name, area, size in (("ram", ram_area, 8192), ("vram", vram_area, 65536)):
            data = bytes.fromhex(client.call("read_memory", area=area, offset="0000", size=size)["data"])
            if len(data) != size:
                raise RuntimeError(f"Reference {name} snapshot is truncated")
            memory[name] = data.hex()
        header = [plan[k] for k in ("seed", "a", "x", "y", "sp", "p")] + [len(plan["steps"])]
        path = args.out / "sequence.txt"
        path.write_text(" ".join(map(str, header)) + "\n" + "".join(f"{pc} {value}\n" for pc, value in plan["steps"]), encoding="ascii")
        wanted = {"states": expected} | memory
        for tier in counts:
            process = subprocess.run([str(args.probe.resolve()), "--probe", str(path.resolve()), tier], capture_output=True, text=True, check=True, timeout=5)
            actual = json.loads(process.stdout)
            mismatch = {k: {"actual": actual.get(k), "expected": v} for k, v in wanted.items() if actual.get(k) != v}
            n, i = actual["native_steps"], actual["interpreter_steps"]
            total = len(expected) * 17
            if (n, i) != ((total, 0) if tier == "native" else (0, total)):
                mismatch["counters"] = {"native_steps": n, "interpreter_steps": i, "expected_steps": total}
            if mismatch:
                (args.out / "failure.json").write_text(json.dumps({"plan": plan["id"], "tier": tier, "mismatch": mismatch}, indent=2) + "\n")
                raise RuntimeError(f'Reference settled VDC mismatch: {plan["id"]}, {tier}')
            counts[tier]["states"] += len(expected)
            counts[tier]["ram_vram"] += 1
            counts[tier]["native_steps"] += n
            counts[tier]["interpreter_steps"] += i
    report = {"schema": 1, "result": "pass", "suite": "vdc", "oracle": info["serverInfo"],
              "oracle_exe_sha256": hashlib.sha256(args.exe.read_bytes()).hexdigest(),
              "probe_sha256": hashlib.sha256(args.probe.read_bytes()).hexdigest(),
              "shard": {"index": args.shard_index, "count": args.shard_count},
              "profile": {k: media[k] for k in ("is_sgx", "is_cdrom", "is_cdrom_hardware_enabled", "mapper", "rom_size")},
              "checked_sequences": [p["id"] for p in selected], "comparisons": counts,
              "inputs": "authored 8 KiB bootstrap and synthetic RAM/VRAM; no retail firmware/disc/save",
              "scope": "CPU and all twenty VDC register values after sixteen settling NOPs per operation; full 8 KiB RAM and 64 KiB VRAM in both execution tiers",
              "not_checked": ["busy interval/contention/device waits", "undriven VRAM read/open-bus state", "raster/status generation", "DMA", "rendering", "IRQ delivery", "hardware qualification", "gameplay"]}
    (args.out / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "checked_sequences"}, indent=2))
