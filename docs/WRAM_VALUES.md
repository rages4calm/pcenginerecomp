# WRAM values and mutable pointer discovery

The additional [memory-flow policy](MEMORY_FLOW.md) can infer safe ordered block
copies, refine SF2 write destinations and explicitly enumerate unknown-X mutable
tables. The conservative limits below describe WRAM policy without that opt-in;
its original qualification remains separate from the later policy's evidence.

`discover-roots --wram-facts --wram-data-range 0:32 --alu-facts --branch-facts
--stack-facts --call-depth 8` opts into bounded, synchronous writable-data facts.
The Python API uses `wram_facts=True`, explicit `wram_data_ranges=[(0,32)]` and
those same prerequisite options. The policy is
`bounded-source-qualified-wram-values-v1`. Older policies and bytes remain intact
when it is omitted; older readers reject the new identifier.

## Permitted memory and evidence

Ranges are canonical **base WRAM offsets** $0000–$1FFF, not logical or physical
bus addresses. Up to 256 bytes may be permitted, excluding the stack page
$0100–$01FF. Base-system banks $F8–$FB alias the same bytes. This does not add a
SuperGrafx profile. ROM operands and ROM vector bytes still need their separate
`--rom-data-range` and `--rom-vector-range` permissions, including mixed pointers.

Every seed starts with unknown memory. Deterministic host reset zeroing does not
become an assumption for arbitrary static roots. Known writes can establish full
bytes; conflicting predecessor values join to unknown. Equal values survive.
Facts are scoped by full selector/MPR/source and calling/depth state. Mutable
pointers are recomputed from the current facts, never cached by source PC alone.
Stale edges made invalid by a later join are retracted from reachability.

Nodes retain permitted `wram_facts`, `data_load` / `alu_operand` witnesses,
`wram_effect` records, and any `wram_vector`. Reads distinguish `storage=rom`
with a source offset from `storage=wram` with a canonical offset, preserving each
logical/physical address and known byte. Effects list old/new inferred values or
explicit invalidations. These are source-derived candidates, not observations,
retirement counts or permissions to mutate a running game.

## Operations and conservative loss of facts

- STA/STX/STY/STZ establish known bytes when their inputs and effective address
  are known. Unknown stored values replace older facts. Supported direct,
  indexed and indirect addressing uses proper byte/word wrapping and separately
  permitted pointer bytes. Known writes outside the tracked set leave unrelated
  bytes alone; uncertain destinations forget all possibly affected tracked data.
- Loads and ALU operands can use proven WRAM bytes. RAM/I/O/unpermitted reads
  never become zero guesses. Indirect pointer bytes can themselves be in WRAM
  or explicitly permitted ROM. Source fetch admission remains ROM-only.
- Memory ASL/LSR/ROL/ROR and INC/DEC update known bytes and C/N/Z as appropriate.
  Unknown carry can leave a rotate's result unknown while its outgoing carry is
  still known. RMB/SMB update full known bytes without inventing other bits.
- BIT/TST and TSB/TRB derive N/V from the old byte. TSB/TRB derive Z from the
  modified result under the HuC6280 rules, not a substituted 65C02 convention.
- T-routed ADC/AND/ORA/EOR update permitted direct-page memory and their status
  while preserving A. Binary and valid-BCD inference use the existing abstract
  arithmetic; invalid BCD remains unknown. SBC continues to use A regardless of T.
  Unknown T or X loses affected memory facts rather than choosing a destination.
- Known-index JMP indirect forms can follow proven WRAM pointers into permitted
  ROM code. Both bytes must be authorized and known. Unknown-index RAM tables
  remain an explicit frontier even when ROM table enumeration is enabled.

Stack accesses remain separate masked facts. A proven indirect store outside the
canonical stack page can cross an existing call frame; possible stack aliases,
unknown destinations or SP/mapping hazards still stop. Block transfers retain
runtime support but their data effects invalidate tracked WRAM; copied values are
not inferred. Existing conservative mapper barriers, including SF2 hazards, remain.

This model does not close asynchronous interrupt effects, external writes,
untracked writable memory, cartridge/CD RAM or modified return frames. No RAM
code fetches, device values or firmware services are invented. Explicit seeds,
code/data bounds, all existing limits and the serialized graph bound remain.

## Consumer and runtime contracts

`verify-discovery` recomputes the entire canonical three-file closure, including
permitted ranges, value/effect/read witnesses, joins, targets, flags and summaries.
Recomputed hashes alone cannot authorize fabricated facts. Discovery-backed
preparation carries this same closure into the existing declaration compiler.
No execution capture rows or hits are fabricated from static analysis.

Generated loads/stores, T-mode operations, branches and jumps retain actual
CPU/bus accesses and source guards. The analysis does not fold live WRAM into
compiled constants. Runtime C++, emitter, ABI 29 and checkpoint encoding are
unchanged. Re-pin/rebuild when adopting the SDK; exact source/package/build
identities and new checkpoints still matter. Original producers remain original.

## Qualified scope

The [original native workflow](../examples/wram-values/README.md) follows ROM →
WRAM → T-mode arithmetic → bank changes → a safe indirect store in a call → a
WRAM jump pointer. The main runs 45 native / zero interpreted / zero guards,
173 cycles / 2,076 ticks. Separate 354 reset/preset cases cover 208 memory RMW/bit
changes, 40 T-mode arithmetic/logic operations, 72 BIT/TST tests and all 34 scalar
memory addressing forms. Each tier retires 3,716 matrix instructions; every one
of the 3,761 declared identities executes across these distinct windows.

Literal CPU/flags/MPR/clocks, every WRAM byte and exact source keys/hits pass.
Changed live pointer/data bytes reach omitted source/mapping guards after 38/25
native instructions, each zero interpreted / one guard and no guest effects at
refusal. Only 13 canonical bytes are tracked; unknown initial bytes remain unknown.

Fresh independent Geargrafx 1.8.4 passes 355 CPU/full-WRAM endpoints and 3,761
before/after instruction points. All 21,008 known incoming and
24,203 known outgoing register/status components and 3,819 known WRAM-byte
checks agree. 16,602 incoming / 13,407 outgoing scalar components and
45,074 permitted-byte components remain explicitly unknown; they are not zero guesses.
Original source and permitted ROM operand bytes match the reference image with
separate setup. All 355 original 8 KiB RAM endpoints are retained losslessly and
reviewed against literal expectations. This is CPU/RAM evidence, not external
clocks, devices/interrupts, retail or hardware qualification. Behavioral sources:
[Gear ALU/test helpers](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/huc6280_opcodes_inline.h)
and [base WRAM mapping](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/memory.cpp).
Implementation and fixture bytes are original; no GPL reference code was copied.

Fresh Rondo TCP boot/file creation/introduction again retires 404,669,933 native /
zero interpreted / zero guards, with 25,621 exact keys/hits and 17 paused reported
state/full-WRAM/CD-RAM/RGB samples. Own same-build checkpoint forks match 59,672
new instructions/753 keys, imported 379,716,149-native prefix separate. Post-close
paired/no-write raw journals, all original memory bytes and independently decoded
PNG CRC/pixels pass. This is existing captured-route regression, not retail use of
WRAM analysis, playable action or whole-game/audio/hardware proof. Host audio is
off; Ys III stays parked. Original source/checkpoint producers stay original.

Frozen **62b9af8567b4bfada140e46d257938d0f95cb0c2** passes **2,275 Python tests
without skips, 74 C++ suites and 12 fresh-process audio cases**, with all
803 tracked inputs unchanged through the required unmodified checker.
SDK source `80b872b3ab967bb6c9e7c52865cdaedb783893199877c3099ec763cb8ab11499`
covers 99 files. Later publication edits are nine Markdown files only. All 84
legacy graph combinations byte-match `105c09d8`; its reader rejects the new policy.
Runtime C++, emitter, ABI 29 and checkpoint encoding are unchanged. Exact new
source/package/build contexts still require fresh checkpoints.

General live RAM/CD code recovery, unknown-index writable tables, broader mapper
precision, block-copy facts, interrupt closure and library/hardware/player gates
remain open. These bounded data facts do not establish complete-game compatibility.
