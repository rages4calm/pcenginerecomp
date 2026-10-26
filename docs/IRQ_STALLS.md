# IRQ delivery during queued VRAM stalls

The dynamic-stall suite extends the separate [device IRQ suite](IRQ_DEVICES.md).
It uses authored firmware and authored MODE1 CUE/BIN media. Guest instructions
configure mapping, stack, CPU masks, VCE clocks, VDC registers and a complete
10-byte CD directory CDB. The observers do not inject a pending interrupt, DMA
countdown, raster phase, queue entry or response deadline.

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

Relevant pinned original source: [CPU clocking and IRQ sampling](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_inline.h),
[queued VDC accesses](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270_inline.h),
[hardware clock order](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/geargrafx_core_inline.h)
and [CD response scheduling](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/scsi_controller.cpp).
