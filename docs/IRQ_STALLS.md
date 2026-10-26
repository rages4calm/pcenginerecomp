# IRQ delivery during queued VRAM stalls

The dynamic-stall suite extends the separate [device IRQ suite](IRQ_DEVICES.md).
It uses authored firmware and authored MODE1 CUE/BIN media. Guest instructions
configure mapping, stack, CPU masks, VCE clocks, VDC registers and a complete
10-byte CD directory CDB. The observers do not inject a pending interrupt, DMA
countdown, raster phase, queue entry or response deadline.

## Frozen results

Implementation `06d97f42c78f55a752187a063aaf7f6161f051ea` has canonical source
SHA-256 `4ad299601b2c91ec3fe791daab2bb1effe5f45583119c2f102917acfca1f1587`
over 69 files, ABI 24. The existing CPU/device runtime passed; no production
semantic change or ABI migration was justified.

All 78 cases pass their independent expectations in native code, a separate
interpreter run and original Gear. Each engine has 3,744 measured retirements.
The toolkit executes 19,227 native instructions with zero fallback, plus
19,227 separate interpreted instructions, including 1,548 block transfers per
tier. All 635 compiled translated identities are actually observed with exact
per-key counts; 312 native source/deadline guards remain pure.

The check retains 39-column device observations and 37-field raw original
kernels. An independently computed 18-field blank-slot kernel additionally
qualifies queue, buffer, raster and CD state at every measured boundary.
Hardware callback exits and actual subsequent CPU samples remain distinct.

There are 52 elapsed retirement matches and 26 precisely predicted timing
differences. Their first differences are all retirement clocks: Gear is
three ticks later in 14 cases, six ticks earlier in 11, and six ticks later
in one. Registers, mappings, WRAM and IRQ metadata agree throughout the
measured suffixes; each complete engine timeline is checked separately.
The raw fast-primer origin differs by 18 ticks and is retained explicitly.

The independent audit requalifies all raw cases, 452,556 literal checks and
11,500,470 journal expectations. It verifies 130 original Git blobs, unchanged
compile copies, 40 objects and all bound outputs. Fresh SDL-enabled
`scripts/check.py` passes 892 Python tests without skips and 49 C++ suites;
the stall C++ selftest has 77,610 checks. CTest metadata contains 50 entries,
including Python; a second CTest execution is not implied.
All 78 positive cases also requalify in the mutation run: 81 independently
corrupted copies are rejected, with original inputs rehashed unchanged.

## Verification contract

The authored matrix has 78 cases across both CPU speeds and VCE divisors
4, 3 and 2. A genuine
long VRAM DMA blocks a MARR prefetch; a mapped CPU port access then waits for
the pending access. Cases cover read-low, read-high, write, read-modify-write,
CPU interrupt masks, the I flag, individual and competing device sources,
stack wrap and remapped interrupt vectors. Separate command cases exercise
the first CD DATA IN request and a subsequent response byte. The 72
subsequent-byte cases use 256-word DMA; six first-request cases use 2,048
words. These lengths leave both requested source assertions inside the wait,
including the fastest video clock at low CPU speed.

Each engine has independent integer timing expectations from the complete
authored primer. Expected values are not obtained from a captured entry
phase or from agreement between the native emitter and the interpreter.
The evidence includes complete CPU state, elapsed clocks, all eight MPRs,
the transfer latch, full WRAM and little-endian VRAM hashes, device literals,
interrupt return addresses and full fetched-source hit counts.
The RMW target is specifically the low data port (`INC $0002`); this does
not qualify a high-port RMW that queues another prefetch between accesses.

The original Gear observer records every hardware-clock callback. An inline
three-tick callback is a dynamic wait only when the original CPU's extra
master-cycle counter increases by three. A fixed memory wait at fast CPU
speed also lasts three ticks. The checker must distinguish them.

Gear calls its hardware clock before updating its internal clocked counter
and sampling interrupts. A source asserted at callback exit has therefore
not yet been sampled by the CPU. The next inline callback's pending value,
or the actual value at instruction return, supplies that witness. Wrapper
drain clocks do not perform that CPU resampling. Only primer block transfers
may compact their per-span device kernels; measured accesses retain them.

## Reference limits

The original core runs separately under its own license with Standard CD
hardware and zero expanded Card RAM. Its CPU, IRQ, VDC, CD and SCSI events
remain original callbacks. No reference implementation bodies are copied
into the toolkit runtime.

The engines have distinct clock origins and device scheduling. In particular,
Gear can process an ACK transition on a later hardware slice. A subsequent
900-tick response countdown can consequently assert 903 ticks after a guest
write when that transition is processed in a three-tick slice. This must be
modeled explicitly rather than erased by shifting observed timestamps.

These are finite authored tests and emulator-source comparisons. They do not
certify electrical bus phases, hardware parity, all display configurations,
all device combinations or a complete retail game.

## Running the suite

The normal authored tests run through CMake and `python scripts/check.py`.
They require no retail media or external emulator. The original-core proof
additionally needs the pinned Gear checkout above, an existing C++20 compiler,
CMake, Ninja and explicit compatible Gear dependency libraries. Run
`python scripts/irq_stall_reference.py --help` for the required paths. Choose a
new directory under `.local/`; the runner refuses an existing proof directory.
It builds the reference separately and binds source, tool, library, object,
fixture and raw-output hashes. Its generated firmware and disc are authored
fixtures. No user BIOS or game is needed for this suite.

Relevant pinned original source: [CPU clocking and IRQ sampling](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_inline.h),
[queued VDC accesses](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270_inline.h),
[hardware clock order](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/geargrafx_core_inline.h)
and [CD response scheduling](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/scsi_controller.cpp).
