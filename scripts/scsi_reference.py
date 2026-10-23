"""Settled CD command-bus checks through an isolated Geargrafx instance.

Authored CPU loops supply exactly the same master-clock delay as repeated
translated/interpreted NOPs in the probe. CPU registers touched only by those
reference delay loops are restored before observing the command-bus state.
This checks completed handshake behavior, not access-phase cycle alignment.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from generate_scsi_fixture import make_fixture
from scripts.raster_reference import delay_program

PHASES = {"BUS FREE": 0, "COMMAND": 3, "DATA IN": 4, "STATUS": 7, "MESSAGE IN": 6, "BUSY": 8}


def plans():
    _, cases = make_fixture()
    sites = {(op, address): pc for pc, op, address in cases}

    def access(address, value=-1, nops=0, mirror=False):
        return (sites[0xAD if value < 0 else 0x8D, address + (0xA000 if mirror else 0)], value, nops)

    result = []

    def append(name, operations, flags=4):
        i = len(result)
        result.append({"id": name, "seed": i, "a": (i * 43 + 0x80) & 255,
                       "x": (i * 37) & 255, "y": (i * 67) & 255,
                       "sp": (0, 1, 254, 255)[i % 4], "p": flags,
                       "steps": operations})

    # Host data latch remains readable in bus-free/command phase. Writes do
    # not themselves acknowledge a byte or start drive-side data transfer.
    for value in (0, 1, 0x7F, 0x80, 0xAA, 0xFF):
        append(f"latch-{value:02x}", [access(0x1801, value), access(0x1801),
            access(0x1808, mirror=True), access(0x1802, 0x80), access(0x1800),
            access(0x1802, 0), access(0x1801, value ^ 255, mirror=True), access(0x1801),
            access(0x1804, 2), access(0x1801), access(0x1804, 0), access(0x1800)],
            flags=(0, 255)[value & 1])

    # Complete TEST UNIT READY: six command bytes, status, message, bus free.
    # Different interrupt masks prove active versus enabled IRQ observability.
    for mask in (0, 0x20, 0x40, 0x60):
        for mirrored in (False, True):
            operations = [access(0x1802, mask), access(0x1801, 0xA5),
                          access(0x1800, 0xFF, 12490, mirrored), access(0x1800),
                          (sites[0xEA, 0], -1, 32), access(0x1800)]
            for byte in range(6):
                operations += [access(0x1801, 0, mirror=mirrored), access(0x1801),
                    access(0x1802, 0x80 | mask), access(0x1800),
                    access(0x1802, 0x80 | mask), access(0x1802, mask, 510 if byte < 5 else 75010),
                    access(0x1800)]
            operations += [access(0x1803), access(0x1801), access(0x1808),
                access(0x1802, mask | 0x80), access(0x1800), access(0x1802, mask, 260),
                access(0x1800), access(0x1801), access(0x1802, mask | 0x80),
                access(0x1802, mask, 260), access(0x1800), access(0x1801)]
            append(f"tur-mask-{mask:02x}-mirror-{int(mirrored)}", operations)

    # Reset aborts pending selection, partial command, held ACK and status.
    for point in ("selection", "command", "ack", "status"):
        operations = [access(0x1800, 0, 0 if point == "selection" else 12510)]
        if point != "selection":
            for byte in range(6 if point == "status" else 1):
                operations += [access(0x1801, 0), access(0x1802, 0xE0)]
                if point != "ack":
                    operations += [access(0x1802, 0x60, 75010 if byte == 5 else 510)]
        operations += [access(0x1804, 2), access(0x1800), access(0x1801),
                       access(0x1802, 0xFF), access(0x1804), access(0x1802),
                       access(0x1804, 0), access(0x1800, nops=12510), access(0x1800)]
        append(f"reset-{point}", operations)

    # Consuming the single status byte schedules one message event. Further
    # ACK pulses while REQ is low must not postpone that already-pending event.
    # Twenty pulses widen the observation window well beyond access alignment.
    status_plan = next(p for p in result if p["id"] == "tur-mask-00-mirror-0")
    operations = list(status_plan["steps"][:53]) + [access(0x1802, 0)]
    for pulse in range(20):
        operations += [access(0x1802, 128), access(0x1802, 0, 180 if pulse == 19 else 0)]
    operations += [access(0x1800), access(0x1801), access(0x1802, 128),
                   access(0x1802, 0, 260), access(0x1800)]
    append("status-consumed-extra-ack", operations)

    # Selecting while already in COMMAND replaces the pending REQ timer. Its
    # eventual same-phase event changes no bus signal and must not restart REQ.
    append("selection-same-command", [access(0x1800, 0, 12510), access(0x1801, 0),
        access(0x1802, 128), access(0x1802, 0), access(0x1800, 0, 12510),
        access(0x1800), (sites[0xEA, 0], -1, 600), access(0x1800),
        access(0x1802, 128), access(0x1802, 0, 510), access(0x1800)])

    # RST is a bus signal, not a write-triggered reset command. An unchanged
    # signal preserves a latch written while held; a newly asserted ACK resets.
    append("reset-held-signal-edges", [access(0x1804, 2), access(0x1801, 0xA5),
        access(0x1804, 2), access(0x1801), access(0x1802, 0), access(0x1801),
        access(0x1802, 128), access(0x1801), access(0x1801, 0xAA),
        access(0x1804, 6), access(0x1804), access(0x1801), access(0x1802, 0x7F),
        access(0x1801), access(0x1804, 0), access(0x1801),
        access(0x1802, 128), access(0x1801)])
    return result


def toc_plans():
    """DE transfers against the authored twelve-track, 1,032-sector TOC."""
    _, cases = make_fixture()
    sites = {(op, address): pc for pc, op, address in cases}

    def access(address, value=-1, nops=0, mirror=False):
        return sites[0xAD if value < 0 else 0x8D, address + (0xA000 if mirror else 0)], value, nops

    def command(mode, track, mask=0x60, mirror=False):
        operations = [access(0x1802, mask), access(0x1801, 0xA5),
                      access(0x1800, 255, 12510, mirror), access(0x1800)]
        for index, value in enumerate([0xDE, mode, track] + [0] * 7):
            operations += [access(0x1801, value, mirror=mirror), access(0x1802, mask | 128),
                           access(0x1802, mask, 1510 if index == 9 else 510), access(0x1800)]
        return operations

    result = []

    def append(name, operations):
        i = len(result)
        result.append({"id": name, "seed": i, "a": (i * 43 + 0x80) & 255,
                       "x": (i * 37) & 255, "y": (i * 67) & 255,
                       "sp": (0, 1, 254, 255)[i % 4], "p": 4, "steps": operations})

    for index, (mode, track) in enumerate([(0, 0), (1, 0)] + [(2, t) for t in (0, 1, 2, 9, 0x10, 0x12, 0x13, 0x99, 0xAA)]):
        for automatic in (False, True):
            mask = (0, 0x40, 0x60)[(index + automatic) % 3]
            mirror = bool((index + automatic) & 1)
            operations = command(mode, track, mask, mirror)
            for byte in range(4):
                operations += [access(0x1803), access(0x1801),
                               access(0x1801, 0xA0 + byte), access(0x1801, mirror=mirror)]
                if automatic:
                    operations += [access(0x1808, nops=510 if byte == 3 else 160, mirror=mirror), access(0x1800)]
                else:
                    operations += [access(0x1802, mask | 128), access(0x1801),
                                   access(0x1802, mask, 510 if byte == 3 else 160), access(0x1800)]
            operations += [access(0x1801), access(0x1802, mask | 128), access(0x1802, mask, 260),
                           access(0x1800), access(0x1801), access(0x1802, mask | 128),
                           access(0x1802, mask, 260), access(0x1800), access(0x1801)]
            append(f"toc-mode-{mode}-track-{track:02x}-{'auto' if automatic else 'manual'}", operations)

    # Reselection in DATA IN changes immediately to an eight-byte status
    # response. Acknowledging it replaces the delayed selection event.
    operations = command(0, 0) + [access(0x1800, 0), access(0x1800)]
    for _ in range(8):
        operations += [access(0x1801), access(0x1802, 0xE0), access(0x1802, 0x60, 260), access(0x1800)]
    operations += [access(0x1802, 0xE0), access(0x1802, 0x60, 260), access(0x1800)]
    append("toc-reselect-eight-status", operations)
    operations = command(0, 0) + [access(0x1800, 0, 75010),
        (sites[0xEA, 0], -1, 75010), access(0x1800), access(0x1801)]
    append("toc-reselect-delayed-command", operations)

    operations = command(2, 0x10) + [access(0x1802, 0xE0), access(0x1802, 0xE0, 500),
        access(0x1800), access(0x1801), access(0x1804, 2), access(0x1800),
        access(0x1801), access(0x1804, 0), access(0x1800)]
    append("toc-reset-held-data-ack", operations)
    operations = command(2, 0x12) + [access(0x1808, nops=10), access(0x1804, 2, 510),
        access(0x1800), access(0x1801), access(0x1804, 0), access(0x1800)]
    append("toc-reset-auto-response-pending", operations)
    return result


def validate_toc(result):
    """Reject a different reference disc before comparing any command bytes."""
    if (result['track_count'], result['sector_count'], result['total_length_msf'],
            result['data_track_count'], result['audio_track_count']) != (12, 1032, '00:15:57', 2, 10):
        raise RuntimeError('Reference authored TOC summary differs')
    tracks = result['tracks']
    if len(tracks) != 12 or any((row['number'], row['start_lba'], row['sector_count'], row['is_audio']) !=
            (i + 1, i * 86, 86, i not in (0, 11)) for i, row in enumerate(tracks)):
        raise RuntimeError('Reference authored track starts/types differ')
    return {'count': 12, 'leadout_lba': 1032,
            'tracks': [{'index1_lba': i * 86, 'type': 4 if i in (0, 11) else 0} for i in range(12)]}


def cd_state(status, cpu):
    return {"bram_unlocked": status["bram_enabled"], "ack": status["scsi_ack"],
            "irq_enable": int(status["enabled_irqs"], 16), "irq_active": int(status["active_irqs"], 16),
            "reset": status["reset"], "irq2": cpu["IRQ2_asserted"],
            "phase": PHASES[status["scsi_phase"]],
            **{name: status["scsi_" + name] for name in ("bsy", "req", "msg", "cd", "io")},
            "data": int(status["scsi_data_bus"], 16)}


def unknown_plans():
    """Explicit reference quirk: unknown first bytes produce immediate GOOD."""
    _, cases = make_fixture()
    sites = {(op, address): pc for pc, op, address in cases}
    def access(address, value=-1, nops=0):
        return (sites[0xAD if value<0 else 0x8D,address],value,nops)
    result=[]
    for opcode,follow in ((255,False),(1,False),(255,True)):
        steps=[access(0x1802,0x60)]
        good=[]
        def command(bytes_,known=False):
            steps.extend([access(0x1800,0,12510),access(0x1800)])
            for i,value in enumerate(bytes_):
                steps.extend([access(0x1801,value),access(0x1802,0xE0),access(0x1800)])
                if i==len(bytes_)-1:good.append(len(steps))
                steps.append(access(0x1802,0x60,75010 if known and i==len(bytes_)-1 else 510 if known else 0))
            steps.extend([access(0x1800),access(0x1801),access(0x1802,0xE0),access(0x1802,0x60,260),
                access(0x1800),access(0x1801),access(0x1802,0xE0),access(0x1802,0x60,260),access(0x1800),access(0x1801)])
        command([opcode])
        if follow:command([0]*6,True)
        i=len(result)
        result.append(dict(id=f'unknown-{opcode:02x}'+('-then-tur' if follow else ''),seed=i,a=0x83+i,
            x=0x39,y=0xA7,sp=(0,255,254)[i],p=4,steps=steps,good_indices=good))
    return result


def bram_plans():
    """Gear's 1807 BRAM gate readback, including exact MPR alias ports."""
    _,cases=make_fixture()
    sites={(op,address):pc for pc,op,address in cases}
    definitions=[('bram-unlocked',[(0x1807,128),(0x1807,-1),(0xB807,-1),(0x1807,-1),(0x1807,0),(0x1807,-1)],{1:128,2:128,3:128,5:0}),
        ('bram-status-lock',[(0x1803,-1),(0x1807,-1),(0x1807,1),(0xB807,-1),(0xB807,255),(0x1807,-1)],{1:0,3:0,5:128}),
        ('bram-write-bits',[(0x1807,255),(0x1807,-1),(0x1803,0),(0x1807,-1),(0x1807,127),(0xB807,-1),(0xB807,128),(0x1807,-1)],{1:128,3:128,5:0,7:128}),
        ('bram-undecoded-hole',[(0x1901,-1),(0x1807,128),(0x1901,-1),(0x1807,-1),(0x1803,-1),(0x1901,-1),(0x1807,-1)],{0:255,2:255,3:128,5:255,6:0})]
    return [dict(id=name,seed=i,a=0x83,x=0x39,y=0xA7,sp=(0,255,254,1)[i],p=(4,255,0,0x55)[i],
        steps=[(sites[0xAD if value<0 else 0x8D,address],value,0) for address,value in operations],expected_reads=expected)
        for i,(name,operations,expected) in enumerate(definitions)]


def run_scsi_matrix(client, areas, args, started, info):
    from scripts.reference_geargrafx import state

    snapshot, cases = make_fixture()
    sites = {(op, address): pc for pc, op, address in cases}
    ram_area = next(a["id"] for a in areas if a["name"] == "SYSTEM RAM" and a["byte_size"] == 8192)
    bram_area = next(a["id"] for a in areas if a["name"] == "BRAM" and a["byte_size"] == 2048)
    media = client.call("get_media_info")
    if not media["is_cdrom"] or not media["is_cdrom_hardware_enabled"] or not media["loaded_bios"]:
        raise RuntimeError("Authored CD media failed to enable reference CD hardware")
    is_toc = args.suite == 'toc'
    is_unknown = args.suite == 'scsi-unknown'
    is_bram = args.suite == 'scsi-bram'
    toc = validate_toc(client.call('list_cdrom_tracks')) if is_toc else None
    selected = (toc_plans() if is_toc else unknown_plans() if is_unknown else bram_plans() if is_bram else plans())[args.shard_index::args.shard_count]
    if not selected:
        raise ValueError("Empty SCSI shard")
    counts = {tier: {"states": 0, "ram_bram": 0, "native_steps": 0, "interpreter_steps": 0}
              for tier in ("native", "interpreter")}
    vector_hashes=[]

    def execute(pc, value=-1):
        client.call("write_huc6280_register", name="PC", value=f"{pc:X}")
        if value >= 0:
            client.call("write_huc6280_register", name="A", value=f"{value:X}")
        client.call("debug_step_into")

    def settle(nops):
        if not nops:
            return
        cpu = state(client.call("get_huc6280_status"))
        code = delay_program(nops * 6)
        client.call("write_memory", area=ram_area, offset="1000", bytes=code.hex(" "))
        client.call("write_huc6280_register", name="PC", value="3000")
        endpoint = f"{0x3000 + len(code):04X}"
        client.call("debug_run_to_cursor", address=endpoint)
        for _ in range(100):
            position = client.call("debug_get_status")
            if position["paused"] and position["pc"] == endpoint:
                break
            time.sleep(0.01)
        else:
            raise RuntimeError("Finite command-bus delay failed to stop")
        for name, value in (("PC", cpu["pc"]), ("X", cpu["x"]), ("Y", cpu["y"]), ("P", cpu["p"] & ~0x20)):
            client.call("write_huc6280_register", name=name, value=f"{value:X}")

    for plan in selected:
        if time.monotonic() - started > 180:
            raise RuntimeError("SCSI reference run exceeded its 180-second budget")
        ram = bytearray((i * 37 + plan["seed"] * 17) & 255 for i in range(8192))
        for pa, value in snapshot.memory.items():
            ram[pa - 0x1F0000] = value
        client.call("write_memory", area=ram_area, offset="0000", bytes=ram.hex(" "))
        client.call("write_huc6280_register", name="PC", value="2700")
        for _ in range(16):
            client.call("debug_step_into")
        for address, value in ((0x1807, 128), (0x1804, 2), (0x1804, 0), (0x1802, 0)):
            execute(sites[0x8D, address], value)
        bram = bytes((i * 13 + plan["seed"] * 7) & 255 for i in range(2048))
        client.call("write_memory", area=bram_area, offset="0000", bytes=bram.hex(" "))
        registers = {"PC": plan["steps"][0][0], "A": plan["a"], "X": plan["x"], "Y": plan["y"], "S": plan["sp"], "P": plan["p"]}
        for name, value in registers.items():
            client.call("write_huc6280_register", name=name, value=f"{value:X}")
        before = client.call("get_huc6280_status")
        if state(before)["mpr"] != list(snapshot.mpr) or before["SPEED"] != "7.16 MHz" or before["TIMER"]:
            raise RuntimeError("Reference CPU setup differs from the fixed command-bus profile")
        if any(state(before)[key] != registers[name] for key, name in
               (("pc", "PC"), ("a", "A"), ("x", "X"), ("y", "Y"), ("sp", "S"), ("p", "P"))):
            raise RuntimeError("Reference register setup was not applied exactly")
        expected = []
        for index,(pc, value, nops) in enumerate(plan["steps"]):
            if time.monotonic() - started > 180 or (args.out / "process.log").stat().st_size > 256 * 1024:
                raise RuntimeError("SCSI reference exceeded its time or diagnostic budget")
            execute(pc, value)
            settle(nops)
            cpu = client.call("get_huc6280_status")
            expected.append({"cpu": state(cpu), "cd": cd_state(client.call("get_cdrom_status"), cpu)})
            if is_unknown and index in plan['good_indices']:
                observed=expected[-1]['cd']
                if observed['phase']!=7 or observed['data']!=0 or not observed['req']:
                    raise RuntimeError('Reference unknown-command quirk did not produce GOOD STATUS')
            if is_bram and index in plan['expected_reads'] and expected[-1]['cpu']['a']!=plan['expected_reads'][index]:
                raise RuntimeError('Reference BRAM gate readback differs from literal port expectation')
        # Restore only the authored delay scratch bytes before full-RAM proof.
        client.call("write_memory", area=ram_area, offset="1000", bytes=ram[0x1000:0x1400].hex(" "))
        memory = {"ram": bytes.fromhex(client.call("read_memory", area=ram_area, offset="0000", size=8192)["data"]).hex(),
                  "bram": bytes.fromhex(client.call("read_memory", area=bram_area, offset="0000", size=2048)["data"]).hex()}
        plan_path = args.out / "sequence.txt"
        header = [plan[k] for k in ("seed", "a", "x", "y", "sp", "p")] + [len(plan["steps"])]
        plan_path.write_text(" ".join(map(str, header)) + "\n" + "".join(f"{pc} {value} {nops}\n" for pc, value, nops in plan["steps"]), encoding="ascii")
        wanted = {"states": expected} | memory
        steps = len(expected) + sum(s[2] for s in plan["steps"])
        for tier in counts:
            mode="--probe-toc" if is_toc else "--probe-unknown" if is_unknown else "--probe"
            process = subprocess.run([str(args.probe.resolve()), mode, str(plan_path.resolve()), tier], capture_output=True, text=True, check=True, timeout=5)
            actual = json.loads(process.stdout)
            mismatch = {k: {"actual": actual.get(k), "expected": v} for k, v in wanted.items() if actual.get(k) != v}
            n, i = actual["native_steps"], actual["interpreter_steps"]
            if (n, i) != ((steps, 0) if tier == "native" else (0, steps)):
                mismatch["counters"] = {"native": n, "interpreter": i, "expected_steps": steps}
            if mismatch:
                (args.out / "failure.json").write_text(json.dumps({"plan": plan["id"], "tier": tier, "mismatch": mismatch}, indent=2) + "\n")
                raise RuntimeError(f"Reference SCSI mismatch: {plan['id']}, {tier}")
            counts[tier]["states"] += len(expected)
            counts[tier]["ram_bram"] += 1
            counts[tier]["native_steps"] += n
            counts[tier]["interpreter_steps"] += i
            if is_unknown or is_bram:
                vector_hashes.append(dict(id=plan['id'],tier=tier,sha256=hashlib.sha256(process.stdout.encode()).hexdigest()))
    report = {"schema": 1, "result": "pass", "suite": args.suite, "oracle": info["serverInfo"],
              "oracle_exe_sha256": hashlib.sha256(args.exe.read_bytes()).hexdigest(),
              "probe_sha256": hashlib.sha256(args.probe.read_bytes()).hexdigest(),
              "shard": {"index": args.shard_index, "count": args.shard_count},
              "checked_sequences": [p["id"] for p in selected], "comparisons": counts,
              "inputs": "Authored bootstrap, blank mixed twelve-track 1032-sector CUE/BIN, RAM and BRAM; no retail inputs" if is_toc else "Authored bootstrap, blank 300-sector CUE/BIN, RAM and BRAM; no retail inputs",
              "scope": "Settled CPU and observable SCSI state; actual authored TOC response bytes, DATA IN manual/auto ACK, data/status IRQ levels, reselection, reset and full RAM/BRAM" if is_toc else "Settled CPU and observable SCSI state; command latch, selection, REQ/ACK, TEST UNIT READY status/message, reset, IRQ level and full RAM/BRAM",
              "not_checked": ["Access-phase timing and exact event boundary", "READ/subcode/audio/media data commands" if is_toc else "READ/TOC/subcode/audio/media commands", "IRQ delivery", "hardware qualification", "gameplay"]}
    if is_toc:
        report['authored_toc'] = toc
        media_root = args.out.parent / 'synthetic-media'
        report['authored_media_sha256'] = {name: hashlib.sha256((media_root / name).read_bytes()).hexdigest()
            for name in ('synthetic-syscard.pce', 'synthetic-disc.bin', 'synthetic-disc.cue')}
    if is_unknown:
        report['scope']='Opt-in unknown first-byte GOOD response, ACK fall, status/message/free, subsequent TEST UNIT READY and complete CPU/RAM/BRAM observations'
        report['not_checked']=['Access-phase timing','exact event boundary','audio continuation','internal command-buffer state','IRQ delivery','hardware qualification','gameplay']
        report['vector_hashes']=vector_hashes
    if is_bram:
        report['scope']='Gear 1807 BRAM gate readback, lock-on-status-read, write bit7, repeated reads, MPR aliases and decoded unused CD port; complete CPU/RAM/BRAM observations'
        report['not_checked']=['Access-phase timing','CD subcode profile','persistent saves','hardware qualification','gameplay']
        report['vector_hashes']=vector_hashes
    (args.out / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
