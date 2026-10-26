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


def analyze(snapshot: Snapshot, limit: int = 10000, *, follow_mappings: bool = False,
            context_limit: int = 256) -> dict:
    if type(limit) is not int or not 1 <= limit <= 100000:
        raise ValueError("Instruction limit must be 1..100000")
    if type(follow_mappings) is not bool:
        raise ValueError("follow_mappings must be a boolean")
    if type(context_limit) is not int or not 1 <= context_limit <= 4096:
        raise ValueError("Context limit must be 1..4096")
    if follow_mappings:
        return _analyze_contexts(snapshot, limit, context_limit)
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


def _register_facts(ins, facts, mpr):
    """Conservative A/X/Y facts used only for discovery, never execution guards.

    None is unknown. In particular, RAM loads and restored block-transfer
    registers cannot be inferred from the immutable source snapshot. TMA zero
    reads an untracked transfer latch, not the current MPRs.
    """
    values = dict(zip(('a', 'x', 'y'), facts))
    name = ins.mnemonic
    if name in ('LDA', 'LDX', 'LDY'):
        values[name[-1].lower()] = ins.data[1] if ins.mode == 'imm' else None
    elif name in ('CLA', 'CLX', 'CLY'):
        values[name[-1].lower()] = 0
    elif name in ('TAX', 'TAY', 'TXA', 'TYA'):
        values[name[-1].lower()] = values[name[1].lower()]
    elif name in ('SAX', 'SAY', 'SXY'):
        left, right = name[1:].lower()
        values[left], values[right] = values[right], values[left]
    elif name == 'TMA':
        selected = [bank for i, bank in enumerate(mpr) if ins.data[1] & (1 << i)]
        values['a'] = None
        if selected:
            value = 0
            for bank in selected:
                value |= bank
            values['a'] = value
    elif name in ('ADC', 'SBC', 'AND', 'ORA', 'EOR', 'PLA'):
        values['a'] = None
    elif name in ('PLX', 'TSX'):
        values['x'] = None
    elif name == 'PLY':
        values['y'] = None
    elif name in ('INA', 'DEA', 'INX', 'DEX', 'INY', 'DEY'):
        register = name[-1].lower()
        value = values[register]
        values[register] = None if value is None else (value + (1 if name.startswith('IN') else -1)) & 255
    elif ins.mode == 'acc':
        values['a'] = None
    elif ins.mode == 'blk':
        # A destination may alias the real stack saves before the final pops.
        values = dict.fromkeys(values)
    return tuple(values.values())


def _analyze_contexts(snapshot, limit, context_limit):
    if (len(snapshot.mpr) != 8 or
            any(type(bank) is not int or not 0 <= bank <= 255 for bank in snapshot.mpr)):
        raise ValueError('mpr must have eight byte values')
    if not snapshot.entries or any(type(pc) is not int or not 0 <= pc <= 65535
                                   for pc in snapshot.entries):
        raise ValueError('entry_points must contain logical 16-bit addresses')
    unknown = (None, None, None)
    initial_mpr = tuple(snapshot.mpr)
    roots = [(initial_mpr, pc) for pc in sorted(set(snapshot.entries))]
    pending, queued = deque(), set()
    facts, instructions, successors, problems = {}, {}, {}, {}
    contexts = set()

    def address(key):
        mpr, pc = key
        return dict(pc=pc, mpr=list(mpr))

    def offer(key, incoming):
        mpr, _ = key
        if key not in facts:
            if mpr not in contexts and len(contexts) >= context_limit:
                return 'context_limit'
            if len(facts) >= limit:
                return 'instruction_limit'
            contexts.add(mpr)
            facts[key] = incoming
        else:
            merged = tuple(a if a == b else None for a, b in zip(facts[key], incoming))
            if merged == facts[key]:
                return None
            facts[key] = merged
        if key not in queued:
            pending.append(key)
            queued.add(key)
        return None

    root_problems = []
    for key in roots:
        refused = offer(key, unknown)
        if refused:
            root_problems.append(address(key) | dict(reason=refused))
    while pending:
        key = pending.popleft()
        queued.remove(key)
        mpr, pc = key
        successors[key], problems[key] = [], []
        try:
            ins = decode(lambda logical: snapshot.memory[physical(logical, mpr)], pc, mpr)
        except KeyError:
            problems[key].append(dict(reason='bytes_not_in_snapshot'))
            continue
        instructions[key] = ins
        name = ins.mnemonic
        outgoing = _register_facts(ins, facts[key], mpr)
        targets = []
        if name in BRANCHES or ins.mode == 'zrl':
            targets = [(mpr, ins.target, 'taken'), (mpr, ins.next_pc, 'fallthrough')]
        elif name in ('JSR', 'BSR'):
            targets = [(mpr, ins.target, 'call')]
            problems[key].append(dict(reason='dynamic_return_site', resume_pc=ins.next_pc))
        elif name in ('JMP', 'BRA') and ins.target is not None:
            targets = [(mpr, ins.target, 'jump')]
        elif name in ('RTS', 'RTI', 'BRK', 'ILL') or name == 'JMP':
            reason = {'RTS':'dynamic_return', 'RTI':'interrupt_return',
                      'BRK':'interrupt_vector', 'ILL':'unassigned_opcode'}.get(name, 'indirect_jump')
            problems[key].append(dict(reason=reason))
        elif name == 'TAM':
            mask = ins.data[1]
            if mask and facts[key][0] is None:
                problems[key].append(dict(reason='mapping_change', resume_pc=ins.next_pc, mask=mask))
            else:
                mapped = tuple(facts[key][0] if mask & (1 << i) else bank
                               for i, bank in enumerate(mpr))
                targets = [(mapped, ins.next_pc, 'mapping_change' if mask else 'fallthrough')]
        else:
            targets = [(mpr, ins.next_pc, 'fallthrough')]
        for mapped, target_pc, kind in targets:
            target = (mapped, target_pc)
            refused = offer(target, outgoing)
            if refused:
                problems[key].append(dict(reason=refused, target=address(target), kind=kind))
            else:
                successors[key].append((target, kind))

    # Facts only lose precision. Replacing an earlier proven TAM edge with an
    # unresolved edge must also remove its now-unreachable optimistic subgraph.
    reachable, todo = set(), deque(key for key in roots if key in facts)
    while todo:
        key = todo.popleft()
        if key in reachable:
            continue
        reachable.add(key)
        todo.extend(target for target, _ in successors.get(key, ()))
    ordered = sorted(key for key in reachable if key in instructions)
    node_ids = {key: index for index, key in enumerate(ordered)}
    rows = [instructions[key].report() | address(key) | dict(node_id=node_ids[key])
            for key in ordered]
    edges, unresolved = [], list(root_problems)
    for key in sorted(reachable):
        source = address(key)
        if key in node_ids:
            source['node_id'] = node_ids[key]
        for problem in problems.get(key, ()):
            unresolved.append(source | problem)
        for target, kind in successors.get(key, ()):
            edge = dict(from_id=node_ids[key], **{'from':address(key), 'to':address(target)}, kind=kind)
            if target in node_ids:
                edge['to_id'] = node_ids[target]
            edges.append(edge)
    occupied = {}
    for key in ordered:
        for pa in instructions[key].physical:
            previous = occupied.setdefault((key[0], pa), key)
            if previous != key:
                unresolved.append(address(key) | dict(node_id=node_ids[key],
                    reason='overlapping_instruction', other=address(previous)))
    # Stable deduplication includes full context, not just PC/physical bank.
    unique = lambda values: [json.loads(value) for value in sorted({
        json.dumps(value, sort_keys=True, separators=(',', ':')) for value in values})]
    return dict(schema=2, analysis_policy='proven_mpr_constants',
        snapshot_sha256=snapshot.identity, mpr=list(initial_mpr),
        entry_points=list(snapshot.entries), context_limit=context_limit,
        instruction_limit=limit, instructions=rows, edges=unique(edges),
        unresolved=unique(unresolved),
        summary=dict(instructions=len(rows), native_supported=sum(ins['native_supported'] for ins in rows),
            unresolved=len(unique(unresolved)), contexts=len({key[0] for key in reachable}),
            explored_states=len(facts), explored_contexts=len(contexts),
            execution_evidence=False))
