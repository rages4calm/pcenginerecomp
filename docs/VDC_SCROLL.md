# Live VDC scroll latches

ABI **25** adds the guest timing history needed for late BXR/BYR writes. The
history belongs to the emulated device even with framebuffer production off.
It is not a host presentation enhancement. Earlier CR/MWR latch edges remain
unchanged; this fixes separate, previously missing scroll-write behavior.

The normal Y and X latches occur 36 and 34 dots before display start. A write
can update a latch during the strict early half of its dot: after rounding the
recorded latch clock down to a dot boundary, the write must be strictly after
that boundary and strictly before `boundary + ceil(divider / 2)`. Divisor4
therefore admits one master tick; divisor3 also admits one; divisor2 admits
none. This is the pinned reference model, not an electrical hardware verdict.

BXR writes in that window update the current X latch. BYR writes in their
window perform the normal Y-counter reload immediately. A separate BYR rule
can refresh just the current line's offset: a low-byte write within four dots
of the Y latch, followed by a high-byte write within six dots of that low
write, while still in HSW and without an earlier pre-latch BXR write. The
offset becomes BYR on raster line zero or BYR+1 otherwise. The existing
counter is retained until the later normal reload. Low-byte timing, latch
timestamps and BXR inhibition reset at each physical line boundary.

## Authored verification

`pce-vdc-scroll-tests` uses **19 original guest programs** through native code,
the interpreter, and native code with framebuffer production disabled. Real
slow-CPU TIA instructions initialize all BAT/pattern data, and real guest
stores establish geometry. Integer padding then places ST0/ST1/ST2 effects
at declared master clocks on steady active physical line64. Two contrasting
tiles and alternating pixel rows give independent rendered-index literals.
No host writes set pending state, a raster phase or a scroll latch.

For divisor4 and HSR `$0202`, the X latch occurs at local clock56. Guest writes
at54,57 and60 must produce new/new/old X respectively in the current line.
For HSR `$0302`, the Y latch is at80; writes at78,81 and84 test its
before/window/after behavior. Paired BYR cases check valid and exact-boundary
gaps, expired gaps/low writes, high-only writes, BXR inhibition, the HSW gate,
and reachable divisor3/divisor2 controls. A successful pair changes the line
offset from47 to4 while retaining counter47; an immediate reload changes
both to4. The first sixteen actual background indices are checked.

Ordinary CPU clocks here lie on a three-master-tick lattice. Divisor3's
single-tick immediate window is not reached by this matrix; its normal/pair
behavior is checked. The suite does not claim fractional guest phases.
The known CSH prefix timing difference remains explicit: independent padding
in the two authored prefixes reaches the same declared effects without
rewriting captured clocks. It does not assert identical prefix opcodes/steps.

The optional `scripts/vdc_scroll_reference.py` executes those programs against
a separately compiled original Geargrafx core pinned to
`1c62a549328241518101f5be5bf3e6840b96ea5d`. Its adapter observes original latch
fields and line indices read-only and checks real original register-write
callbacks. Source references are [register writes and line history](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270.cpp)
and [latch-window predicates](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270_inline.h).
Original GPL implementation bodies are not copied into the MIT runtime.

Actual source captures retain logical PC, all eight MPRs, physical fetched
bytes and per-tier hits. Authored translation inputs are not called captured
execution. Independent CPU/mapping/full WRAM, scroll and pixel literals are
separate from native/interpreter equality. Current proof results and source
pins are in [status](STATUS.md).

The final original-Gear/native/interpreter run passes all 19 cases, executing
1,935 native instructions with zero fallback and 1,935 separate interpreted
instructions. All 153 compiled identities are actually observed, including
304 block transfers per tier. Six real pre-fix counterexamples retain their
original failed outcomes. All 19 positive datasets requalify; 11 corrupted
copies are rejected with 514 bound files unchanged. The corrected observer's
source pin is separate from the unchanged runtime/compiler pin; no failed raw
JSON was repaired. Original continuation calls remain distinct from completed
opcodes.

The scope excludes arbitrary geometry/latch races, whole-frame equality,
independent physical hardware, warm reset and campaign parity. Future states
must retain the added per-line timestamps and BXR/BYR history, as well as the
existing Y counter, pending reload, increment and live offset. No save-state
format is introduced; BRAM-only saves retain their separate contract.
