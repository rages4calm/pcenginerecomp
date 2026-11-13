# Address-selected cartridge bank discovery

`discover-roots --mapper-facts` extends the [memory-flow policy](MEMORY_FLOW.md)
for the explicit **SF2 2.5 MiB board profile**. It requires `--memory-flow`,
`--block-transfer-limit N`, WRAM permissions, ALU/branch/saved-stack facts and
explicit call depth. Python uses `mapper_facts=True` with those same options.
Other board profiles refuse this option; it does not add new cartridge hardware.

The identifier is `bounded-source-qualified-mapper-flow-v1`. Omission preserves
previous policy bytes; old readers refuse the new identifier. All existing
source/state/context/stack/copy/table/report bounds remain enforced. Existing
discovery-backed consumers canonically rederive the complete three-file closure,
including every new option, write witness, intermediate selector and target.
No observation hits or runtime memory values are manufactured by the analysis.

## Scalar writes and source context

Only physical bank zero offsets $1FF0–$1FFF select this board's window. The
written **address's low four bits** select the latch; the data byte is ignored.
The lower two latch bits choose which 512 KiB region appears at physical
$80000–$FFFFF. Fixed ROM below that window keeps its existing mapping.

A scalar store/RMW can continue when its effective address is proven from
current facts and separately permitted pointer bytes. This includes known
indexed and indirect addresses. The stored value need not be known. Other writes
preserve the selector; unknown addresses retain the mapper frontier.

The next instruction is decoded under the new full selector/MPR context and
requires its own ROM source permission. Decoding, operand loads and vectors cannot
reuse stale bytes from the previous window. Calls retain their original caller
provenance, while a return uses the current selector and mapping. Conflicting
index joins retract stale inferred continuations. No PC-only cache is introduced.

`mapper_effect` records the instruction's selector before/after, address-based
selection and modeled write/transition counts. Four-bit latch transitions and
effective two-bit window changes are counted separately; alias selectors can
change the latch without changing visible ROM. These are analysis witnesses,
not electrical bus events or a replacement for the bus-trace observer.

## Changes within a block transfer

Safe TII/TDD/TIA/TAI/TIN still require canonical stack mapping, temporary-save
capacity and a complete destination span disjoint from every stack-page alias.
Their decoded operand words belong to the entry source view. A later bank change
does not reinterpret the already decoded operation or operands.

Every byte is processed in order: read under the current selector, perform its
write, then apply any address-selected latch change before the next source read.
WRAM overlap/aliases keep their existing sequential semantics. Unknown or denied
source bytes lose affected data facts, but do not prevent a selector change whose
write address is proven. A stack hazard stops before inferring preserved state.

`block_effect` retains each transfer's selector before/after, mapper-write marker,
logical/physical addresses, permitted source offset/value and tracked WRAM effect.
Internal latch/window transitions are counted even when an instruction returns
to its entry window. The 65,536 aggregate expanded-byte bound remains unchanged.

## Dynamic native operations and state

Generated operations still read/write live guest memory and board state. Inferred
selectors do not become hardcoded runtime bank selections or bypass source guards.
A changed live index can select another window and stop at an omitted source
identity. No runtime C++, emitter, ABI 29 or checkpoint-format change is made.
Exact new SDK/source/package/build contexts still require fresh checkpoints.

## Authored and reference evidence

The [original reusable workflow](../examples/mapper-flow/README.md) derives 9,009
exact identities across 150 selector/MPR contexts from 609 seeds, without
frontiers. All identities execute across the main and separate preset windows.
The previous memory-flow policy admits 5,032 identities and 609 mapper frontiers
on the same source/permissions; its main stops at eight operations instead of 17.
These counts are candidate recovery, not a whole-game coverage or speed result.

The official main executes 17 native / zero interpreted / zero guards, 104 cycles
/ 1,248 ticks. It switches code windows and changes the source window twice
inside a TII before copying RAM bytes. The 608 separate cases cover 192 direct
store/RMW writes, 96 indexed/indirect stores, and 320 block geometries including
all five operations, every latch address, four initial selectors, four lengths,
logical aliases and entering/leaving the latch range. They execute 8,992
instructions per tier. Each case saves the pre-witness status byte and reads a
distinct ROM-window byte, then checks CPU/flags/MPR/clocks, all 8 KiB RAM and
encoded keys/hits. The changed-index negative stops after ten native instructions
with one guard and no additional guest effects. Windows probes use a system-only
PATH. Separate presets are not arbitrary power-on or hardware-reset proof.

Fresh unmodified Geargrafx 1.8.4 passes **608 fixed-ROM CPU/full-WRAM
endpoints and 8,992 instruction points**. All 61,280 known incoming /
66,752 known outgoing register/status components and 7,256 known WRAM
byte checks agree. Unknown components remain unknown. Every selected source/data
byte matches the original fixture with disjoint reference setup; all 608 original
8 KiB RAM endpoints are retained losslessly. Post-close review checks every known
fact, 1,120 ordered source/selector witnesses and the effective-window reads.
The hidden full four-bit latch is not directly inspected through Gear's API;
its upper-bit behavior has source-review and native literal-check evidence.

The original main's block remaps its executing code window. Two fresh Gear
processes time out at that instruction and remain **failed reference attempts**.
A smaller authored original input reproduces the failure; changing one previously
inactive opcode byte makes a fresh Gear process complete. No reference-core patch
or changed-input result is counted as original-image parity. The issue is reported
upstream as [Geargrafx #214](https://github.com/drhelius/Geargrafx/issues/214).

A separately compiled **original full Beetle PCE core** at
`b96c11e095b6a40a412d2da02766ae1c3f4fd539` completes the original main: all 17
known-fact boundaries, literal RAM hashes/clocks and final original 8 KiB RAM
match. Its exact original image is unchanged; no mirrored opcode is needed.
The minimal original reproducer also completes in seven instructions, 44 cycles /
528 ticks. CPU/device/frontend source bodies remain unchanged; a separate authored
observer supplies explicit register/MPR/RAM presets. These are CPU/RAM and selected
literal clock checks, not physical-hardware, external bus/device timing or general
reset qualification. No emulator body is copied into the toolkit.

Fresh Rondo TCP boot/file/introduction again retires 404,669,933 native /
zero interpreted / zero guards, matching 25,621 exact keys/hits and 17 paused
state/full-WRAM/CD-RAM/RGB samples. Own same-build checkpoint forks match 59,672
new instructions / 753 keys; the imported 379,716,149-native prefix is separate.
Post-close paired/no-write journals, original memory and independent PNG CRC/pixel
review pass. This is existing captured-route regression, not retail use of the
new static policy, playable action, full-game, listening or hardware proof.
Audio is off; Ys III stays parked. Original producers remain original.

Frozen **f14bd0bf2b9873ba453112af21be1455a5874a06** passes **2,312 Python tests
without skips, 74 C++ suites and 12 fresh-process audio cases**, with all
815 tracked inputs unchanged through the required unmodified checker.
SDK source `fbb98ccbbd256529943917e6e209ff3a6e16cdb835722b2c7fd9e20533418ac4`
covers 100 files. Later publication changes nine Markdown files only. All 98
legacy graph combinations byte-match `3a203400`, including both previous
memory-flow profiles; its reader refuses the new mapper policy. Runtime C++,
emitter, ABI 29 and checkpoint encoding remain unchanged.

Behavioral sources include [Gear's SF2 mapper](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/sf2_mapper.cpp),
[Gear's block implementation](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/huc6280_opcodes_inline.h),
[Mesen's block implementation](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceCpu.Instructions.cpp)
and the separately compiled original Beetle core. Implementation and fixture
bytes are original; no reference-core bodies are copied into this toolkit.

General RAM/CD-code recovery, untracked writable memory, absolute stack/modified
return reasoning, interrupt closure, further cartridge boards and broader
library/hardware/player qualification remain separate gates. This policy does
not establish complete SF2 or general PC Engine game compatibility.
