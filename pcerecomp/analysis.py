"""Bounded recursive control-flow recovery for an explicit bank snapshot."""

from collections import deque
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tomllib

from .isa import BRANCHES, decode, physical


@dataclass
class Snapshot:
    mpr: tuple[int, ...]
    memory: dict[int, int]
    entries: tuple[int, ...]
    identity: str

    def read(self, pc: int) -> int:
        return self.memory[physical(pc, self.mpr)]

    @classmethod
    def load(cls, path: Path):
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        if config.get("schema") != 1:
            raise ValueError("Expected snapshot schema = 1")
        mpr = tuple(config["mpr"])
        entries = tuple(config["entry_points"])
        if len(mpr) != 8 or any(type(x) is not int or not 0 <= x <= 255 for x in mpr):
            raise ValueError("mpr must have eight byte values")
        if not entries or any(type(x) is not int or not 0 <= x <= 65535 for x in entries):
            raise ValueError("entry_points must contain logical 16-bit addresses")
        segments = config.get("segments", [])
        if not isinstance(segments, list) or not segments:
            raise ValueError("At least one segment is required")
        memory = {}
        identity = hashlib.sha256()
        identity.update(json.dumps({"schema": 1, "mpr": mpr, "entries": entries}, sort_keys=True).encode())
        for segment in segments:
            if not isinstance(segment, dict):
                raise ValueError("Each segment must be a table")
            start = segment["physical"]
            if type(start) is not int or not isinstance(segment["file"], str) or not isinstance(segment["sha256"], str):
                raise ValueError("Segment physical/file/sha256 types are invalid")
            file = path.parent / segment["file"]
            if file.stat().st_size > 2*1024*1024:
                raise ValueError("Segment exceeds physical address space")
            data = file.read_bytes()
            if not data or not 0 <= start < 0x200000 or start+len(data) > 0x200000:
                raise ValueError("Segment outside physical address space")
            if hashlib.sha256(data).hexdigest() != segment["sha256"]:
                raise ValueError("Segment SHA256 mismatch")
            for offset, value in enumerate(data, start):
                if offset in memory:
                    raise ValueError("Overlapping segments")
                memory[offset] = value
            identity.update(start.to_bytes(4, "little")); identity.update(data)
        return cls(mpr, memory, entries, identity.hexdigest())


def analyze(snapshot: Snapshot, limit: int = 10000) -> dict:
    if not 1 <= limit <= 100000:
        raise ValueError("Instruction limit must be 1..100000")
    pending = deque(snapshot.entries)
    instructions = {}
    edges, unresolved = [], []
    occupied = {}
    while pending:
        pc = pending.popleft()
        if pc in instructions:
            continue
        if len(instructions) >= limit:
            unresolved.append({"pc": pc, "reason": "instruction_limit"})
            break
        try:
            ins = decode(snapshot.read, pc, snapshot.mpr)
        except KeyError:
            unresolved.append({"pc": pc, "reason": "bytes_not_in_snapshot"})
            continue
        instructions[pc] = ins
        for address in ins.physical:
            if address in occupied and occupied[address] != pc:
                unresolved.append({"pc": pc, "reason": "overlapping_instruction", "other": occupied[address]})
            occupied[address] = pc
        m = ins.mnemonic
        successors = []
        if m in BRANCHES or ins.mode == "zrl":
            successors = [(ins.target, "taken"), (ins.next_pc, "fallthrough")]
        elif m in ("JSR", "BSR"):
            successors = [(ins.target, "call"), (ins.next_pc, "return_site")]
        elif m in ("JMP", "BRA") and ins.target is not None:
            successors = [(ins.target, "jump")]
        elif m in ("RTS", "RTI", "BRK", "ILL") or (m == "JMP" and ins.target is None):
            unresolved.append({"pc": pc, "reason": {"RTS": "dynamic_return", "RTI": "interrupt_return",
                              "BRK": "interrupt_vector", "ILL": "unassigned_opcode"}.get(m, "indirect_jump")})
        elif m == "TAM":
            # No speculative propagation of A or MPR values at this baseline.
            unresolved.append({"pc": pc, "reason": "mapping_change", "resume_pc": ins.next_pc, "mask": ins.data[1]})
        else:
            successors = [(ins.next_pc, "fallthrough")]
        for target, kind in successors:
            edges.append({"from": pc, "to": target, "kind": kind})
            pending.append(target)
    return {"schema": 1, "snapshot_sha256": snapshot.identity, "mpr": snapshot.mpr,
            "entry_points": snapshot.entries,
            "instructions": [instructions[pc].report() for pc in sorted(instructions)],
            "edges": edges, "unresolved": unresolved,
            "summary": {"instructions": len(instructions), "native_supported": sum(i.native for i in instructions.values()),
                        "unresolved": len(unresolved), "execution_evidence": False}}
