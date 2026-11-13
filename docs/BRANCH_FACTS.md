# Source-qualified conditional discovery

Opt-in branch facts prevent impossible conditional arms from erasing bank facts
or creating false frontiers. Unknown conditions still retain both candidates.
This changes the analyzed graph, not runtime branch operations.

```sh
python -m pcerecomp discover-roots seeds.json --image card.pce --rom-range 0:32 --alu-facts --branch-facts --out new-branches
```

Supply actual code ranges for your image. Python callers pass both
`alu_facts=True, branch_facts=True`. Both options require real booleans; branch
facts require the register evaluator. Omitting/false preserves prior policies
and artifact bytes. Try the complete [authored workflow](../examples/branch-facts/README.md)
without game or firmware files.

## Status and branch rules

Seeds start with unknown A/X/Y/C/D/T/N/Z/V. Register facts are bytes or null;
status facts are integer 0/1 or null. Existing
[register evaluation](REGISTER_EVAL.md) supplies A/X/Y/C/D/T. This policy adds:

- N/Z from known loads, transfers, increments/decrements, arithmetic/logic,
  accumulator shifts/rotates and comparison differences.
- Binary ADC/SBC overflow from known inputs/results. Decimal operations retain
  prior V under the existing runtime/reference contract; unknown decimal or
  binary results lose dependent V. CLV sets V to 0.
- CLA/CLX/CLY, swaps and TMA preserve N/Z; register values alone do not define flags.
- Untracked T-memory destinations, restored status, memory shifts and memory/test
  effects remain conservative. BIT/TST/TSB/TRB currently lose N/Z/V rather than
  guessing their memory/test effects. Invalid BCD result facts remain unknown.

The eight flag conditions test C/Z/N/V: BCC/BCS, BNE/BEQ, BPL/BMI and BVC/BVS.
A known flag retains only the matching candidate arm. An unknown flag retains
both arms, refining only that tested bit on each outgoing edge. It does not
invent correlated register/memory facts. Conflicting predecessors join to
unknown and broaden decisions; stale dependent candidates are retracted.
Zero-displacement edges may immediately join their refined bits back to unknown.

BBR0..7/BBS0..7 can decide from an independently permitted immutable ROM byte
at logical `$2000 + operand`. The current image/header/encoding, mapper selector,
all eight MPRs and byte offset remain bound. The source byte needs separate
`rom_data_ranges` / `--rom-data-range` permission, as in
[ROM data analysis](ROM_DATA.md). RAM/I/O, undriven and writable sources remain
unknown even if a test host happens to initialize them to zero. Unknown bit
branches retain both arms without pretending to track writable memory bits.

A pruned target needs no code permission or instruction slot for that edge.
An explicitly declared seed at that address remains an independent root and
still needs ordinary source/code admission. Bounds and explicit unresolved
semantics remain in force; pruning is not routine or interrupt closure.

## Witnesses, composition and runtime

The new policy is `bounded-source-qualified-branches-v1`, with literal
`options.alu_facts: true` and `options.branch_facts: true`. It composes existing
ROM-load, synchronous-call, vector and unknown-index table options. Table-index
edge injection preserves all status components. Older readers reject the new
identifier. Prior report formats/policy bytes remain unchanged when omitted.

Each node retains incoming `register_facts` and six-bit `flag_facts`, plus
outgoing `register_evaluation`. A conditional node adds `conditional`:

- Flag branches: `flag`, expected bit, known/null value and decision
  (`taken`, `fallthrough`, `both`).
- Bit branches: `bit`, expected bit and decision. Successful `value` is the
  **whole source byte**, with a read witness containing logical address,
  physical address, decoded-ROM offset and byte value. Denied reads retain
  `reason`/`detail`; absent permissions remain explicit.

Summary `conditional_states`, `decided_conditionals`, `unknown_conditionals`
and `pruned_conditional_edges` count retained analysis states/decisions, not
retired instructions or unique source identities. All reads, status results,
conditions, edges, counts and options are independently rederived from original
seeds and bound image. Rehashing edited metadata cannot authenticate a graph.
The exact three-file closure survives [copying and consumer preparation](DISCOVERY_CONSUMERS.md)
without fabricated observations or hit counts.

Generated branch operations continue to read live CPU flags or memory. No branch
condition or destination is substituted from analysis. Changed runtime data can
reach an omitted identity and produce a normal source/mapping guard miss; hybrid
mode can interpret supported unseen code. Runtime C++/emitter, ABI 29 and checkpoint
encoding are unchanged. New source/package/build contexts need fresh exact-build
checkpoints. These are bounded synchronous candidates, not whole-game discovery.

## Verification

Frozen `cb47691fa7fc7e7645c35562e840ea6956856cb9` passes **2,227 Python/no skips,
74 C++ suites and 12 fresh-process audio cases**, all 789 tracked inputs unchanged.
SDK SHA256 `7a23ea8f83315bd5f13a40e7857dd012f37a34bb7a14f33041fa966a1e1dfd31`
covers 97 source files; later publication edits are Markdown only.

Ten status tests cover 542,336 mathematical binary/valid-BCD/logic/shift/compare/
load cases plus controls and unknowns. Fourteen discovery tests check known and
unknown arms, refinement, carry joins, mutable/denied bit reads, explicit roots,
code/slot bounds, 16-bit wrap, table/call composition, strict options and tamper
rederivation. Three workflow tests include actual compilation/execution. 48 old
default/vector/call/table/data/register graphs byte-match committed `82f43222`;
its reader separately refuses the new policy.

The authored main route expands nine candidates to 28 and runs 28 native/zero
interpreted/zero guards, 107 cycles/1284 ticks. The 97-seed graph has 1,068 identities,
99 decided conditions/pruned edges, 36 ROM-load and 32 ROM-bit witnesses. The old
both-path analysis overdeclares matrix arms and stops the main route's bank
change, producing 1,193 candidates. Separate 96-case matrices execute 1,040 instructions
per tier and exercise all eight flag and 16 bit-branch forms in both senses.
All 1,068 exact keys/hits, literal CPU/MPR/flags/clocks and 8192 WRAM bytes agree
across these distinct reset/preset windows, not one continuous guest route.

Changed private operand data changes the actual RAM result without fallback.
Carry/overflow/sign variants take omitted arms and stop after 5/14/22 native;
changed instruction bytes stop after 18. Each has zero interpreted/one guard,
with no added guest work/clocks or memory effects at refusal. Original inputs
stay unchanged. Windows probes use the official archive and checked packaged
DLLs without SDK PATH, qualified here with Windows x64 LLVM-MinGW/Ninja.

Fresh Geargrafx 1.8.4 passes 97 conditional and 281 arithmetic CPU/full-WRAM cases.
All 99 recorded conditional before/after points agree with the candidate decisions;
886 known incoming register/status components match, with five intentionally
unknown. Additional arithmetic endpoints match 2,209 known components, leaving 320
unknown. Across 380 compared program points, 3,095 known components match and 325
remain unknown. Reference-only setup preserves every compiled source/operand
byte; bootstrap/presets remain separate. These are independent software CPU/RAM
checks, not external clocks, bus/devices, audio/video, retail or hardware parity.

A fresh Rondo TCP/checkpoint regression separately repeats boot/file creation/
introduction: 404,669,933 native/zero interpreted/zero guards, 25,621 exact keys/hits,
17 reported-state/full-WRAM/full-CD-RAM/completed-RGB samples. Own same-build forks
match 59,672 new instructions/753 keys, with imported 379,716,149-native prefix work
separate. Closed raw paired journals/no writes, original memory bytes and independent
PNG CRC/pixel decoding pass. Original captures/expectations retain their producers.
This is existing-route regression, not retail branch-policy use, playable action,
complete-game or audio/hardware qualification. Host audio is off; Ys III stays parked.

Reference semantics were checked against the
[Geargrafx 1.8.4 instruction source](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/huc6280_opcodes_inline.h)
and separately executed through its MCP interface. No reference implementation
was copied across licenses. Hardware, live RAM/CD source and general status-stack/
interrupt reasoning remain separate gates.
