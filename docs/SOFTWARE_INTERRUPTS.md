# Synchronous software interrupts in static discovery

`discover-roots --software-interrupts` adds bounded BRK/RTI continuations to the
existing memory-flow analysis. The Python API appends `software_interrupts=True`.
The canonical policy is `bounded-source-qualified-software-interrupts-v1`.
Omitting the option preserves previous graph bytes and behavior.

This is candidate derivation. It does not observe execution or establish
asynchronous IRQ, routine, interrupt or whole-game closure. Runtime operations,
native lowering and ABI 29 are unchanged.

## Prerequisites and permissions

Enable `--memory-flow`, `--wram-facts`, `--stack-facts`, `--alu-facts` and
`--branch-facts`; supply explicit code/WRAM ranges, call-depth and block-transfer
limits as required by [memory flow](MEMORY_FLOW.md). Optional `--mapper-facts`
composes under the explicit SF2 profile. A plain base card needs no mapper mode.

BRK reads logical `$FFF6/$FFF7` through the current MPRs and selector. ROM vector
bytes require `--rom-vector-range OFFSET:LENGTH` permissions in decoded-ROM
coordinates. Proven tracked WRAM vector bytes use the existing WRAM permissions
and fact model; no initial zero RAM or reset-time mapping is assumed. Missing
permission, unknown values, unsupported memory or exhausted bounds stop the edge
with a reason. A known vector does not bypass target code/source permissions.

## Frame and status model

BRK has a two-byte source identity, including the signature byte. Its resume PC
is the next instruction, with 16-bit wrap. The relative saved stack receives
resume high, resume low and status. Saved status has B=1/T=0; other tracked
status bits retain their known values or unknown masks. Handler entry has
I=1/D=0/T=0. Canonical WRAM stack aliases, shared call-depth limits and all
three bytes of stack capacity are checked before entry.

RTI requires the matching innermost BRK frame, exact balanced relative depth and
a proven two-byte saved resume word. It restores saved status facts (including
I/D), clears B, and returns under the *current* MPR/selector view. A/X/Y remain
live unless the handler explicitly saves/restores them. Ordinary RTS and RTI
cannot consume each other's frame kinds. Nested calls and software interrupts
retain distinct caller provenance; protected frame pops/writes stop explicitly.

Unknown saved status bits remain unknown after return, so branches are pruned
only when their required flag is proven. Joins can broaden those masks or
retract stale vector targets. Absolute SP inference, modified return frames and
unmatched RTI roots remain unsupported. Hardware IRQ scheduling can change the
actual path; native source guards and the selected execution policy still apply.

## Derivation and consumer contract

Reports carry `software_interrupt` vector reads/target/resume, a three-byte
software frame kind, `interrupt_return_site` and `interrupt_return` provenance,
and entry/return summaries. The reader rederives the exact closure, permissions,
frames, joins and targets instead of trusting stored witnesses. Discovery-backed
[consumers](DISCOVERY_CONSUMERS.md) preserve that same closure through preparation,
builds and managed archives. Old readers reject the new policy. Numeric expanded
roots remain candidate declarations, not captures.

Generated C++ still performs real vector reads, stack traffic, flag restoration
and dynamic dispatch. Analysis never hardcodes a vector, saved flag or return
into the runtime. A changed live vector/status may reach a source identity
absent from the module: native-only mode refuses it; supported hybrid execution
may fall back to the interpreter.

## Authored qualification

The [reusable example](../examples/software-interrupts/README.md) derives 2,104
exact instruction identities across 3,889 calling/fact states from 257 seeds.
Under identical source permissions, the previous memory-flow policy derived
1,550 keys and stopped at 258 BRK-related frontiers; the new graph has none.
The nested main crosses ROM and proven WRAM vectors, stack aliases, nested
JSR/BRK frames, a handler MPR change and decimal arithmetic after return. It
retires 49 native instructions, zero interpreted and zero guard misses, with
literal CPU/full-WRAM/clocks and exact source/hits. A separate 256-status-byte
by four-SP matrix executes 1,024 preset windows: 15,360 instructions per native
or interpreter tier, covering every declared key. Changed-vector and changed-
status negatives retire 28 and 14 native instructions respectively, then each
refuse an omitted target with one guard miss and no refusal-time guest effects.

Fresh unmodified Geargrafx 1.8.4 checks the main plus all 1,024 matrix windows:
15,409 instruction points, every known incoming/outgoing scalar fact, tracked
WRAM byte and relative saved-stack bit, and all 1,025 original 8 KiB RAM
endpoints. Reference setup changes only disjoint bootstrap bytes; analyzed code
and permitted ROM data/vector bytes are identical. All 124,345 known incoming /
134,595 known outgoing
register/status component checks, 80 known WRAM byte checks and 182,616 relative
saved-stack bit checks agree; unknown scalar components remain unknown. No active
timer/hardware IRQ source participates. Two earlier reference setup attempts remain failed harness
attempts. This is bounded CPU/RAM evidence, not independent clocks, asynchronous
IRQ/device timing, hardware or retail compatibility proof.

Gear behavior was checked against its [1.8.4 CPU implementation](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/huc6280_opcodes_inline.h)
and the [pinned Mesen implementation](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceCpu.Instructions.cpp).
These are semantic references; no incompatible reference implementation is copied.
