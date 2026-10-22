"""Synthetic speed/state checks and explicit Geargrafx transition differences.

CPU trace timestamps are sampled at instruction entry. One sentinel instruction
provides the end timestamp of the last measured instruction. No device/bus trace
or retail program is captured.
"""
import hashlib
import json
import re
import subprocess
import time

from generate_fixture import MPR_DEFAULT, make_fixture, mpr_cases


def plans():
    _, cases = make_fixture(oracle=True)
    primary = {op:pc for pc,op in cases}
    observe = next(pc for pc,op,mask in mpr_cases(True) if op==0x43 and mask==0)
    result = []
    for divisor in (3,12):
        for flags in (0,255,0x55,0xAA):
            for ops in ((0x54,0xEA), (0xD4,0xEA), (0x54,0x54,0xEA,0xD4,0xD4,0xEA,0x54,0xEA)):
                i=len(result)
                result.append({"id":f"speed-{divisor}-{flags:02x}-{'mixed' if len(ops)>2 else f'{ops[0]:02x}'}",
                               "divisor":divisor,"a":(i*43+0x80)&255,"x":(i*61)&255,
                               "y":(i*67)&255,"sp":(0,1,254,255)[i%4],"p":flags,"seed":i,
                               "steps":[(primary[op],op) for op in ops]+[(observe,0x43)]})
    return result


def trace_deltas(trace, pcs):
    if trace.get("overrun") or trace.get("count")!=len(pcs) or len(trace.get("lines",[]))!=len(pcs):
        raise RuntimeError("Missing, extra or overwritten speed trace entries")
    entries=[]
    for line,pc in zip(trace["lines"],pcs):
        match=re.match(r"^@(\d+)\s+.*?\b([0-9A-Fa-f]{2}):([0-9A-Fa-f]{4})\s",line)
        if not match or int(match[2],16)!=0xF8 or int(match[3],16)!=pc:
            raise RuntimeError("Unexpected speed trace timestamp/bank/PC")
        entries.append(int(match[1]))
    deltas=[b-a for a,b in zip(entries,entries[1:])]
    if any(d<=0 for d in deltas):
        raise RuntimeError("Empty or non-monotonic speed trace")
    return deltas


def timing(opcode, old):
    """Literal split-cycle expectations and pinned Geargrafx's observed rule."""
    if opcode in (0x54,0xD4):
        new=12 if opcode==0x54 else 3
        split={(3,3):9,(3,12):18,(12,3):27,(12,12):36}[old,new]
        return new,3,split,3*new
    cycles=4 if opcode==0x43 else 2
    return old,cycles,cycles*old,cycles*old


def run_speed_matrix(client, area, snapshot, args, started, info):
    from scripts.reference_geargrafx import state
    selected=plans()[args.shard_index::args.shard_count]
    if not selected:
        raise ValueError("Selected speed shard has no sequences")
    primary={op:pc for pc,op in make_fixture(oracle=True)[1]}
    counts={tier:{"states":0,"ram_latch":0,"native_steps":0,"interpreter_steps":0,
                  "matching_tick_deltas":0,"documented_transition_differences":0} for tier in ("native","interpreter")}
    differences=[]
    input_path=args.out/"sequence.txt"
    for plan in selected:
        if time.monotonic()-started>180:
            raise RuntimeError("Reference check exceeded its 180-second work budget")
        ram=bytearray((i*37+plan["seed"]*17)&255 for i in range(8192))
        for pa,value in snapshot.memory.items():
            ram[pa-0x1F0000]=value
        client.call("write_memory",area=area,offset="0000",bytes=ram.hex(" "))
        # Actual CPU transfers restore mapping and the hidden transfer latch.
        client.call("write_huc6280_register",name="PC",value="2700")
        for _ in range(16):
            client.call("debug_step_into")
        client.call("write_huc6280_register",name="PC",value=f"{primary[0x54 if plan['divisor']==12 else 0xD4]:X}")
        client.call("debug_step_into")
        status=client.call("get_huc6280_status")
        if state(status)["mpr"]!=list(MPR_DEFAULT) or status["SPEED"]!=('7.16 MHz' if plan['divisor']==3 else '1.79 MHz'):
            raise RuntimeError("Reference speed/mapping setup failed")
        if status["TIMER"] or any(status[k] for k in ("IRQ1_asserted","IRQ2_asserted","TIQ_asserted")):
            raise RuntimeError("Active reference timer/interrupt is outside speed check scope")
        registers={"PC":plan["steps"][0][0],"A":plan["a"],"X":plan["x"],"Y":plan["y"],"S":plan["sp"],"P":plan["p"]}
        for name,value in registers.items():
            client.call("write_huc6280_register",name=name,value=f"{value:X}")
        before=state(client.call("get_huc6280_status"))
        if any(before[k]!=registers[v] for k,v in (("pc","PC"),("a","A"),("x","X"),("y","Y"),("sp","S"),("p","P"))):
            raise RuntimeError("Reference register setup was not applied exactly")
        client.call("set_trace_log",enabled=True,output="memory",memory_size="100K",filters=["cpu.instructions"])
        # next_sequence is a page cursor, not necessarily the logger tail.
        # Request the tail explicitly so a previous case cannot be reused.
        tail=client.call("get_trace_log",start=-1,count=1)
        sequence=tail["next_sequence"]
        if sequence!=tail["total_logged"]:
            raise RuntimeError("Reference trace cursor did not reach the current tail")
        expected=[]
        for pc,_ in plan["steps"]:
            client.call("write_huc6280_register",name="PC",value=f"{pc:X}")
            client.call("debug_step_into")
            status=client.call("get_huc6280_status")
            divisor={"7.16 MHz":3,"1.79 MHz":12}[status["SPEED"]]
            expected.append(state(status)|{"clock_divisor":divisor})
        # Entry of a sentinel NOP closes the final measured instruction.
        client.call("write_huc6280_register",name="PC",value=f"{primary[0xEA]:X}")
        client.call("debug_step_into")
        trace=client.call("get_trace_log",start=sequence,count=len(expected)+1)
        client.call("set_trace_log",enabled=False)
        pcs=[pc for pc,_ in plan["steps"]]+[primary[0xEA]]
        try:
            deltas=trace_deltas(trace,pcs)
        except RuntimeError:
            (args.out/"failure-trace.json").write_text(json.dumps({"plan":plan["id"],"expected_pcs":pcs,"trace":trace},indent=2)+"\n")
            raise
        expected_ram=bytes.fromhex(client.call("read_memory",area=area,offset="0000",size=8192)["data"]).hex()
        header=[plan[k] for k in ("a","x","y","sp","p","seed","divisor")]+[len(plan["steps"])]
        input_path.write_text(" ".join(map(str,header))+"\n"+"".join(f"{pc} -1\n" for pc,_ in plan["steps"]),encoding="ascii")
        for tier in counts:
            process=subprocess.run([str(args.probe.resolve()),"--speed",str(input_path.resolve()),tier],capture_output=True,text=True,check=True,timeout=5)
            actual=json.loads(process.stdout)
            if len(actual["states"])!=len(expected) or actual["ram"]!=expected_ram or actual["mpr_latch"]!=expected[-1]["a"]:
                raise RuntimeError(f"Speed sequence length/RAM/latch mismatch: {plan['id']}, {tier}")
            old=plan["divisor"]; ticks=cycles=0
            for index,((_,op),wanted,got,delta) in enumerate(zip(plan["steps"],expected,actual["states"],deltas)):
                new,c,t,g=timing(op,old); ticks+=t; cycles+=c
                if got!=wanted|{"ticks":ticks,"cycles":cycles} or delta!=g:
                    (args.out/"failure.json").write_text(json.dumps({"plan":plan["id"],"index":index,"tier":tier,"actual":got,"expected":wanted|{"ticks":ticks,"cycles":cycles},"oracle_ticks":delta,"expected_oracle_ticks":g},indent=2)+"\n")
                    raise RuntimeError(f"Unexpected speed state/timing result: {plan['id']}, {index}, {tier}")
                if t!=delta:
                    counts[tier]["documented_transition_differences"]+=1
                    if tier=="native":
                        differences.append({"plan":plan["id"],"index":index,"opcode":op,"entry_divisor":old,"exit_divisor":new,"split_ticks":t,"geargrafx_ticks":delta})
                else:
                    counts[tier]["matching_tick_deltas"]+=1
                old=new
            n,i=actual["native_steps"],actual["interpreter_steps"]
            expected_counts=(len(expected),0) if tier=="native" else (0,len(expected))
            if (n,i)!=expected_counts:
                raise RuntimeError("Speed route counters did not match selected tier")
            if actual["guard_misses"]!=0:
                raise RuntimeError("Unexpected native guard miss in stable speed mapping")
            counts[tier]["states"]+=len(expected); counts[tier]["ram_latch"]+=1
            counts[tier]["native_steps"]+=n; counts[tier]["interpreter_steps"]+=i
    report={"schema":1,"result":"architectural_pass_timing_discrepancy","suite":"speed","oracle":info["serverInfo"],
            "oracle_exe_sha256":hashlib.sha256(args.exe.read_bytes()).hexdigest(),"probe_sha256":hashlib.sha256(args.probe.read_bytes()).hexdigest(),
            "shard":{"index":args.shard_index,"count":args.shard_count},"checked_sequences":[p["id"] for p in selected],
            "comparisons":counts,"timing_differences":differences,
            "trace_schema":"cpu entry master-tick timestamps and bank/PC, followed by one sentinel; no bus events",
            "timing_contract":"two cycles at entry speed, final cycle at selected speed, source-cross-checked with Mesen and Beetle",
            "not_checked":["hardware verification","dummy bus accesses","clock alignment/wait states","IRQ delivery","devices","CD","gameplay"]}
    (args.out/"result.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("checked_sequences","timing_differences")},indent=2))
