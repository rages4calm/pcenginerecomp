"""Bounded, synthetic MPR sequences for the independent Geargrafx check.

The oracle exposes MPRs but not its transfer latch. Every sequence ends with
TMA #0, observing the latch through A without relying on private emulator APIs.
"""
import hashlib
import json
import subprocess
import time

from generate_fixture import MPR_DEFAULT, make_fixture, mpr_cases


def plans():
    _, cases = make_fixture(oracle=True)
    primary = {op: pc for pc, op in cases}
    transfer = {(op, mask): pc for pc, op, mask in mpr_cases(oracle=True)}
    read = (primary[0xA5], -1)
    write = (primary[0x85], -1)
    observe = (transfer[0x43, 0], -1)
    result = []

    def add(name, steps):
        i = len(result)
        result.append({"id": name, "a": (i*43+0x80)&255, "x": (i*61)&255,
                       "y": (i*67)&255, "sp": (0,1,254,255)[i%4],
                       "p": (0,255,0x55,0xAA)[i%4], "seed": i&255,
                       "steps": steps})

    for mask in range(256):
        add(f"tma-{mask:02x}", [(transfer[0x43, mask], -1), read, observe])
    for mask in range(256):
        # Keep the sequence/reset code's RAM window resident. Changing any
        # other MPR deliberately exercises conservative native guard yields.
        value = 0xF8 if mask&2 else (0,0x55,0xAA,0xFF)[(mask>>2)%4]
        add(f"tam-{mask:02x}", [(transfer[0x53, mask], value), read, observe])
    add("zero-preserves", [(transfer[0x43,4], -1), (transfer[0x53,0],0x55), write, read, observe])
    for i,value in enumerate(MPR_DEFAULT):
        add(f"same-map-{i}", [(transfer[0x53,1<<i],value), (transfer[0x53,0],value^255), write, read, observe])
    for mask in (0xFF,0x55,0xAA):
        steps = [(transfer[0x53,1<<i],value) for i,value in enumerate((1,0xF8,4,8,16,32,64,128))]
        add(f"basis-or-{mask:02x}", steps+[(transfer[0x43,mask],-1),read,observe])
    return result


def run_mpr_matrix(client, area, snapshot, args, started, info):
    from scripts.reference_geargrafx import state
    all_plans = plans()
    selected = all_plans[args.shard_index::args.shard_count]
    if not selected:
        raise ValueError("Selected MPR shard has no sequences")
    counts = {tier: {"states": 0, "ram": 0, "native_steps": 0, "interpreter_steps": 0, "guard_misses": 0}
              for tier in ("native", "interpreter")}
    input_path = args.out / "sequence.txt"
    for plan in selected:
        if time.monotonic()-started > 180:
            raise RuntimeError("Reference check exceeded its 180-second work budget")
        ram = bytearray((i*37+plan["seed"]*17)&255 for i in range(8192))
        for pa,value in snapshot.memory.items():
            ram[pa-0x1F0000] = value
        client.call("write_memory", area=area, offset="0000", bytes=ram.hex(" "))
        # Reset using actual LDA/TAM instructions in RAM. The last TAM sets
        # MPR7 and the latch to zero. Debug register setters cannot do this.
        client.call("write_huc6280_register", name="PC", value="2700")
        for _ in range(16):
            client.call("debug_step_into")
        reset = state(client.call("get_huc6280_status"))
        if reset["mpr"] != list(MPR_DEFAULT) or reset["a"] != 0:
            raise RuntimeError("Reference RAM-resident mapping reset failed")
        registers = {"PC": plan["steps"][0][0], "A": plan["a"], "X": plan["x"],
                     "Y": plan["y"], "S": plan["sp"], "P": plan["p"]}
        for name,value in registers.items():
            client.call("write_huc6280_register", name=name, value=f"{value:X}")
        before = state(client.call("get_huc6280_status"))
        if any(before[k] != registers[v] for k,v in (("pc","PC"),("a","A"),("x","X"),("y","Y"),("sp","S"),("p","P"))):
            raise RuntimeError("Reference register setup was not applied exactly")
        expected_states = []
        for pc,override_a in plan["steps"]:
            client.call("write_huc6280_register", name="PC", value=f"{pc:X}")
            if override_a >= 0:
                client.call("write_huc6280_register", name="A", value=f"{override_a:X}")
            client.call("debug_step_into")
            expected_states.append(state(client.call("get_huc6280_status")))
        expected = {"states": expected_states,
                    "ram": bytes.fromhex(client.call("read_memory",area=area,offset="0000",size=8192)["data"]).hex(),
                    "mpr_latch": expected_states[-1]["a"]}
        header = [plan[k] for k in ("a","x","y","sp","p","seed")]+[len(plan["steps"])]
        input_path.write_text(" ".join(map(str,header))+"\n"+"".join(f"{pc} {a}\n" for pc,a in plan["steps"]),encoding="ascii")
        for tier in counts:
            result = subprocess.run([str(args.probe.resolve()),"--mpr",str(input_path.resolve()),tier],
                                    capture_output=True,text=True,check=True,timeout=5)
            actual = json.loads(result.stdout)
            mismatch = {k:{"actual":actual.get(k),"expected":v} for k,v in expected.items() if actual.get(k)!=v}
            n,interpreted = actual.get("native_steps",-1),actual.get("interpreter_steps",-1)
            if n+interpreted != len(plan["steps"]) or (tier=="native" and n<1) or (tier=="interpreter" and n!=0):
                mismatch["counters"] = actual
            if mismatch:
                (args.out/"failure.json").write_text(json.dumps({"plan":plan,"tier":tier,"mismatch":mismatch},indent=2)+"\n")
                raise RuntimeError(f"Reference MPR sequence mismatch: {plan['id']}, {tier}")
            counts[tier]["states"] += len(plan["steps"])
            counts[tier]["ram"] += 1
            for key in ("native_steps","interpreter_steps","guard_misses"):
                counts[tier][key] += actual[key]
    report = {"schema":1,"result":"pass","oracle":info["serverInfo"],"suite":"mpr",
              "oracle_exe_sha256":hashlib.sha256(args.exe.read_bytes()).hexdigest(),
              "probe_sha256":hashlib.sha256(args.probe.read_bytes()).hexdigest(),
              "suite_sequences":len(all_plans),"shard":{"index":args.shard_index,"count":args.shard_count},
              "checked_sequences":[p["id"] for p in selected],"comparisons":counts,
              "scope":"per-instruction registers, flags, PC and MPRs; final 8 KiB RAM and latch observed through TMA #0; synthetic sequences",
              "native_scope":"native-first with counted interpreter fallback after MPR context changes; every sequence starts native",
              "not_checked":["cycles/bus phases","IRQ delivery","video/audio","CD","gameplay"]}
    (args.out/"result.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="checked_sequences"},indent=2))
