# Device interrupt priority and acknowledgement

The authored device suite exercises the existing aggregate interrupt profile
through actual guest instructions and independently compiled original Gear.
It adds reusable verification and call journals; it does not introduce a new
CPU policy or runtime ABI. ABI remains **24**. See [STATUS.md](STATUS.md) for
the frozen execution identities and final results.

## Priority and the two kinds of mask

The CPU request register uses these bits:

| Bit | Source | Vector | Acknowledgement |
|---|---|---|---|
| `$04` | Timer | `$FFFA` | Write CPU `$1403` |
| `$02` | VDC IRQ1 | `$FFF8` | Read VDC status |
| `$01` | CD IRQ2 | `$FFF6` | Service or mask its source device |

CPU `$1402` contains **disable** bits. CD `$1802` instead contains CD source
**enable** bits and ACK. Changing one mask does not change the other or erase
an active device source. Reading CPU requests does not acknowledge them.

The selected profile samples requests, the CPU mask and I before executing an
instruction, and can replace that sample at modeled hardware wait points.
At delivery, it chooses timer, then IRQ1, then IRQ2. The sampled timer must
still be pending; acknowledging it can therefore expose a lower sampled
source. IRQ entry itself does not acknowledge any source. Held lines can
reenter after RTI and the documented entry-I delay.

This describes the implemented Gear aggregate profile. It does not establish
electrical IRQ sampling on physical hardware or resolve every difference
from other emulators. [CPU_SEMANTICS.md](CPU_SEMANTICS.md) retains those limits.

## A cleared line can retain a sampled interrupt

In the default queued VDC profile, a mapped status read clocks one fixed CPU
wait **before** observing and clearing status/IRQ1. The CPU can retain the
sample taken during that wait and deliver IRQ1 at the instruction boundary,
even though the live line is now clear. A status INC has a subsequent mapped
write and wait, which can replace the sample and cancel delivery.

The explicit legacy `immediate` profile reads/clears before its fixed wait.
Its later sample can cancel IRQ1 on the same read. That difference is tested
as a declared comparison against original Gear; it is not projected away or
reported as equality. The default profile is unchanged.

CD `$1803` reports active sources and locks BRAM; reading it does not
acknowledge IRQ2. An ordinary data read also leaves REQ asserted. A real ACK
handshake clears the requested source, while disabling its CD enable bit
only lowers the CPU line and retains the active source. Reset has its own
source-clearing behavior. None of these CD writes injects a new CPU sample,
so an already sampled IRQ2 can still be delivered.

Original Gear applies ACK to the SCSI bus immediately and processes the
resulting REQ/source change when its hardware clock runs. The toolkit's port
handler processes the handshake synchronously. The finite suite checks the
declared completed-instruction CPU/device outcomes and retains original
callback times. This is not an assertion of identical internal CD bus phases.

## Authored firmware and media

All 44 configurations use authored 256 KiB firmware and a tiny authored
MODE1 CUE/BIN image. Public load/reset APIs select Standard CD hardware in
both implementations; no expanded Card RAM is used. Guest code establishes
MPRs, clears work RAM, sets registers/stack, issues the complete ten-byte
`$DE` command, triggers one real VRAM DMA, starts the timer and waits for its
request before disabling its clock without acknowledging it.

No host register, IRQ line, RAM or device phase seeds establish the compared
state. Deterministic public reset options remain declared test configuration,
not reconstructed electrical power-on state. Original Gear's in-memory
BRAM reset defaults are not a claim of BRAM-byte equality, and the adapter
does not call its disk save/load APIs. All media stays private/generated.

The matrix includes all eight CPU masks at both fixed CPU speeds, genuine
handler order and source acknowledgements, queued/immediate status reads,
read-modify-write resampling, CD ACK/disable/reset/non-acknowledging reads,
timer-acknowledgement fallback, retained lines, STATUS versus DATA IN CD
sources, stack wrapping and mapped interrupt vectors. There are 48 measured
retirements per configuration, including handler work and a bounded terminal
branch loop. Primers and block-transfer payloads are counted separately.

Independent literals retain full CPU/mapping/clock/WRAM states, actual IRQ
counts/vectors/return PCs and 39 named CPU/device columns. Every native and
interpreter capture must match independent logical-PC/full-MPR/physical-byte
identities and per-key hits. Native guards are checked while real devices
are pending; a guard must not mutate CPU, clocks, memory or device state.
The emission source plan is authored static metadata, not an execution
capture or a claim that every compiled identity executed.

## Original call and clock journals

The original observer keeps CPU/IRQ, VDC, CD and SCSI callbacks enabled.
It records full entry/post-call states and device rows, original call count,
returned ticks, internally clocked ticks observed before wrapper draining,
dynamic waits and every actual hardware-clock callback span. Audio buffers
are drained at guest-driven boundaries without adding clocks.

One group is one guest opcode. Original Gear block transfers return for
start, each byte and closing; these calls do not become extra retirements.
The qualifier checks their authored stable-ROM operands, exact call count
and aggregate duration. Measured calls must each contain one original opcode.

The checker binds the actual fetched bytes, mapped source and register
observations; verifies callback ordering, exact fixed-wait/drain partitions,
IRQ vector/return-PC/mask/time and required CD access/ACK-clear callbacks;
and requires genuine DMA and complete-command/source witnesses in the primer.
Other raw device callbacks remain retained observations. A well-formed
journal alone does not authenticate an executable: source, tool, media,
fixture, binary and raw-output bindings are separately checked.

Reproduce with an existing compiler, pinned original source, dependency
libraries and a new private directory:

```text
python scripts/irq_device_reference.py --gear-source PINNED_GEAR --tool-source PINNED_TOOL --out .local/irq-device-reference --library LIBCHDR --library LZMA --library MINIZ --library ZSTD
```

The runtime/CPU operations are not copied from Gear. Its original sources
compile into a separate reference executable; that GPL executable is not
linked into the toolkit runtime. The baseline C++ and Python tests require
only authored fixtures and do not require this external checkout.

## Remaining scope

These vectors use DMA-completion IRQ1 and SCSI DATA IN/STATUS IRQ2. They do
not qualify every raster/sprite IRQ, ADPCM half/end source, overlapping CD
source latch combination, interrupted transfer or physical penultimate-cycle
sample. These device literals deliberately assert zero dynamic waits. The
separate [78-case stall suite](IRQ_STALLS.md) adds DMA IRQ1 and CD IRQ2 inside
actual queued VRAM waits with independent timing and original clock kernels.
Full original
Beetle CD execution is not added here. A finite Ys III TCP regression checks
the shared runtime separately and is not new library or campaign coverage.

Primary references are pinned original Gear
[CPU delivery](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_inline.h),
[mapped I/O](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/memory_inline.h),
[VDC](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270.cpp),
and [SCSI clock/IRQ handling](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/scsi_controller_inline.h).
