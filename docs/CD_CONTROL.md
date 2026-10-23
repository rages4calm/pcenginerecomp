# Limited CD control and volatile BRAM

This is an instruction-level, idle CD control profile. Supplying `--bios`
enables it in the headless sandbox. Without firmware, the sandbox still
faults on these accesses. There is no CD command transport, audio, device
scheduler or persistent save implementation.

## Implemented contract

Hardware routing uses the physical bank after MPR translation. The control
registers below occupy bank `$FF`, offsets `$1800..$1BFF`. Addresses in another
logical page can therefore alias them through another MPR. These registers
are not mirrored every 16 bytes: `$1817` and `$1907` remain unsupported.

| Offset | Read | Write |
|---|---|---|
| `$1802` | IRQ-enable bits 0..6 and current ACK in bit 7 | Set enable bits and ACK; asserted reset keeps ACK clear |
| `$1803` | Lock BRAM; return active IRQ bits OR `$12` in this idle Geargrafx-compatible profile | Read-only; ignore the write without locking BRAM |
| `$1804` | Stored low nibble of reset register | Store low nibble; bit 1 asserts reset, clears ACK and active IRQ bits `$70` |
| `$1807` | Unsupported: CD subcode is not implemented | Bit 7 selects unlocked/locked BRAM access |

Other CD registers still fault. The separately enabled [VDC profile](VDC.md)
handles video ports; it does not add CD transport. No SCSI selection/data command, ADPCM,
audio sample, video or undefined register is accepted as a successful no-op.
The IRQ2 level is the intersection of active and enabled sources. Its
combinational state exists, but no asynchronous source or CPU IRQ delivery
is implemented. Reset and ACK are observable at instruction boundaries;
this does not model hardware signal phases.

The profile starts idle with BRAM unlocked, ACK/reset/IRQ fields zero and
unformatted, zero-filled **volatile** storage. Bank `$F7` has exactly 2 KiB
of writable BRAM at offsets `$0000..$07FF`. Locked reads and the remaining
6 KiB return `$FF`; locked/upper-hole writes are ignored. The hole does not
mirror the first 2 KiB. MPR aliases observe the same storage. Only changed
BRAM bytes advance its write generation; control writes and lock changes
do not count as RAM writes. No save files are opened, created or exported.

`Bus::read` can now produce device side effects. `peek` remains a pure source
inspection operation: it returns no value for I/O or BRAM, so source guards
cannot lock BRAM or dispatch stale BRAM code across a protection change.
CPU loads/stores/indexing/RMW all use the same bus path. A fault does not
retire the instruction; it is still a fatal, non-transactional exit.

Adding device state to `Bus` advances native-module ABI to **3**. Regenerate
older modules and rebuild all consumers. No serialized state format exists
to migrate. Future states must include control state and BRAM contents.

## Reference choices and limits

The register/profile behavior follows pinned Geargrafx 1.8.4 where explicitly
implemented. It is not a claim that all independently developed references
agree on undocumented hardware details:

- Mesen/Beetle treat `$1807` reads as CD subcode. Geargrafx instead reads back
  BRAM access state. This runtime leaves the read unsupported rather than
  inventing subcode or copying that readback.
- Geargrafx includes `$10` in `$1803` status and keeps its audio-channel bit
  stable without sample-latch writes; Mesen differs. Audio latch accesses
  are unsupported here, so the idle profile's extra status bits are explicit.
- Geargrafx clears active SCSI IRQ bits on reset; Mesen clears enable bits
  instead. The runtime follows Geargrafx's active-bit rule. Nonzero source
  combinations are local expected-value checks, not live IRQ-generation proof.
- Geargrafx/Mesen use bit 7 to lock or unlock on every `$1807` write; Beetle's
  pinned implementation only enables on a set bit. Hardware confirmation
  remains useful before calling these edge cases console conformance.

The public fixture is entirely authored RAM code. It checks 61,440 expected
native/interpreter load/store cases, all input bytes under four flag contexts,
the whole BRAM extent, MPR aliases, RMW read side effects, indexed hole
crossings, operand mutation, deadlines and explicit faults. The independent
MCP suite uses an authored 256 KiB bootstrap and blank 300-sector CUE/BIN,
then requires `is_cdrom_hardware_enabled=true`. This avoids comparing against
an emulator with CD hardware disabled. No retail BIOS/disc/save is needed.
See [REFERENCE.md](REFERENCE.md) for measured results and reproduction.

## Sources

- [Geargrafx CD registers](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/cdrom.cpp),
  [memory routing](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/memory_inline.h)
  and [SCSI reset](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/scsi_controller.cpp).
- [Mesen CD interface](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/CdRom/PceCdRom.cpp).
- [Beetle CD interface](https://github.com/libretro/beetle-pce-libretro/blob/b96c11e095b6a40a412d2da02766ae1c3f4fd539/mednafen/pce/pcecd.cpp).

These are research references, not linked or copied CPU/device implementations.
