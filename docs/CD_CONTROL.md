# CD TOC/data handshake and volatile BRAM

The baseline has two explicit profiles: idle CD control/BRAM through
`Bus::enable_cd_control()`, and a clocked command handshake through
`Bus::enable_cd_transport()`. Supplying `--bios` or `--toc` enables the latter
in the headless sandbox. Without either profile, CD accesses still fault.
The transport implements selection, command reception, TEST UNIT READY,
directory/TOC responses, DATA IN acknowledgement, status and message completion.
The TOC descriptor supplies metadata only; there is no sector, sense, subcode
or audio backend and no claim of a mounted disc or complete System Card boot.

## Implemented contract

Hardware routing uses the physical bank after MPR translation. The control
registers below occupy bank `$FF`, offsets `$1800..$1BFF`. Addresses in another
logical page can therefore alias them through another MPR. These registers
are not mirrored every 16 bytes: `$1817` and `$1907` remain unsupported.

| Offset | Read | Write |
|---|---|---|
| `$1800` | SCSI BSY/REQ/MSG/CD/IO in bits 7..3; transport profile only | Begin selection; value is ignored; transport profile only |
| `$1801` | Drive byte in DATA IN/STATUS/MESSAGE IN, host latch otherwise; transport profile only | Set host data latch; does not itself acknowledge a byte; transport profile only |
| `$1802` | IRQ-enable bits 0..6 and current ACK in bit 7 | Set enable bits and ACK; asserted reset keeps ACK clear |
| `$1803` | Lock BRAM; return active IRQ bits OR `$12` in this idle Geargrafx-compatible profile | Read-only; ignore the write without locking BRAM |
| `$1804` | Stored low nibble of reset register | Store low nibble; bit 1 asserts reset, clears ACK and active IRQ bits `$70` |
| `$1807` | Unsupported: CD subcode is not implemented | Bit 7 selects unlocked/locked BRAM access |
| `$1808` | Sample the data byte; DATA IN with REQ/IO and CD clear asserts ACK, which releases after 21 master ticks | Unsupported: ADPCM is not implemented |

Other CD registers still fault. The separately enabled [VDC profile](VDC.md)
handles video ports. No unsupported command, ADPCM, audio sample or undefined
register is accepted as a successful no-op.
The IRQ2 level is the intersection of active and enabled sources. Its
transport source `$20` follows a requested STATUS/MESSAGE byte; `$40` follows
a requested DATA IN byte. ACK clears REQ and its source. CPU interrupt delivery
remains unsupported: an eligible unmasked IRQ2 stops explicitly before another
instruction. Device changes are observed at instruction boundaries, with the
same access-phase approximation as video timing; this does not establish
cycle-exact CPU bus phases.

## Clocked transport

The host latch and drive data byte are separate. Writing `$1801` does not
advance the command or overwrite the drive's status byte. The host sets ACK
through `$1802` bit 7 only after observing REQ. A requested command byte is
captured once when REQ and ACK are both high, and REQ falls. Repeated high ACK
writes cannot capture extra bytes. Dropping ACK allows the next command-byte
request or dispatch of a complete command. Reads of `$1801` never acknowledge
it automatically. `$1808` samples the same byte and additionally acknowledges
a requested DATA IN byte. Its auto-ACK release schedules the next byte like a
manual ACK falling edge. Outside DATA IN it samples without acknowledging;
write-side ADPCM semantics remain unsupported.

Six-byte **TEST UNIT READY (`$00`)** produces GOOD status (`$00`) followed by
COMMAND COMPLETE message (`$00`). Ten-byte **GET DIRECTORY INFO (`$DE`)**
returns metadata through the bounded DATA IN path described below.
Unsupported commands stop explicitly when dispatched; the captured command
remains useful diagnostic state. In particular, REQUEST SENSE (`$03`), READ
(`$08`), CDDA controls and subcode requests are not successful stubs.
GOOD here means the configured control transaction completed; no medium was
read or validated.

| Transition | Geargrafx-reference delay in master ticks |
|---|---:|
| Selection write → COMMAND with REQ | 75,000 |
| Intermediate command byte ACK falls → next REQ | 3,000 |
| Complete TEST UNIT READY ACK falls → GOOD status with REQ | 450,000 |
| Complete supported directory command ACK falls → DATA IN with first REQ | 9,000 |
| DATA IN byte ACK falls → next response byte REQ | 900 |
| `$1808` auto-ACK assertion → ACK release | 21 |
| Last DATA IN byte ACK falls → GOOD status with REQ | 3,000 |
| Status byte ACK falls → MESSAGE IN with REQ | 1,500 |
| Message byte ACK falls → BUS FREE | 1,500 |

The command remains in COMMAND with REQ clear during its completion delay.
STATUS and MESSAGE IN drop REQ while ACK is asserted, clearing the transport
IRQ source. The delayed phase transitions then request the next byte. A held
ACK is observable at a delayed REQ edge and consumes that request once.
Reset bit 1 cancels pending transitions, clears transport latches/command
state and ACK, returns the bus to idle, and clears active IRQ bits `$70`;
the IRQ-enable mask and attached TOC metadata are preserved. Releasing reset
does not resurrect a partial command, response or auto-ACK timer.

Selection during DATA IN follows Geargrafx's separate abort profile: eight
GOOD status bytes are exposed and COMMAND is scheduled after 900,000 ticks.
Status/message ACKs can replace that pending transition as in the reference.
The local tests cover both consuming this response and leaving it pending;
the live suite checks settled abort sequences.

These are a deterministic **reference-emulator timing profile**, not measured
drive timing. The pinned Mesen source calls its delays approximations and
deliberately shortens TEST UNIT READY. It corroborates the initial selection,
byte and completion delays after conversion from CPU ticks, but changes
STATUS/MESSAGE phases immediately. The runtime follows Geargrafx's delayed
phase profile. Live checks compare settled transactions; they do not qualify
the exact instant of a CPU register access or physical drive accuracy.

## Directory response and metadata boundary

The command's byte 1 selects one of three implemented modes. Every response
has four bytes in the selected Geargrafx/Mesen profile:

| Mode | Response |
|---|---|
| `$00` | `$01`, last track number in BCD, `$00`, `$00` |
| `$01` | Absolute leadout minute/second/frame in BCD, `$00` |
| `$02` | Requested track's absolute INDEX 01 minute/second/frame in BCD, type `$00` audio or `$04` data |

Mode `$02` reads the track selector from command byte 2. Track zero aliases
track 1. BCD track numbers above the last track and the explicit `$AA` leadout
sentinel return the absolute leadout position with type `$00`. Other malformed
BCD selectors and unsupported modes fault explicitly with attached metadata.
Without a TOC, the command returns CHECK CONDITION (`$02`) through the
Geargrafx status/message path; it does not invent tracks. This reference path
also presents `$02` as its message byte. REQUEST SENSE remains unsupported.

`CdControl::set_toc()` validates 1..99 consecutive tracks, strictly increasing
nonnegative INDEX 01 LBAs before leadout, and type values 0/4. Leadout is bounded
to 449,849 so adding the 150-frame lead-in fits absolute BCD `99:59:74`.
Attachment requires an idle enabled transport; reset preserves the metadata.
The runtime converts disc LBAs to absolute MSF only when constructing replies.

The frontend exports a descriptor without decompression or sector extraction:

```sh
python -m pcerecomp toc "/path/to/disc.chd" --out .local/title/disc.toc
build/pce-headless .local/title/boot.bin 0x100000 0x4000 255,248,128,129,130,131,132,0 100000 2000000 hybrid --bios .local/firmware/syscard3-usa.pce --toc .local/title/disc.toc
```

Use `.exe` on Windows. The exporter also accepts a single-track cooked
2048-byte-sector ISO. CHD metadata supports AUDIO, MODE1 and MODE1_RAW;
unsupported formats/types fault. Stored and virtual pregaps affect disc time
according to the metadata; four-frame CHD storage padding does not. Inter-track
postgaps move following INDEX 01 positions. The chosen Geargrafx CHD profile
reports leadout at the end of the final track's program frames, excluding a
trailing POSTGAP. This last rule is explicit reference compatibility, without
console qualification. No implicit 150-frame correction changes exported LBAs.

The canonical ASCII format is bounded to 8 KiB:

```text
PCE_TOC 1
image_sha256 <64 lowercase hex digits>
leadout_lba <decimal disc LBA>
track <consecutive number> <decimal INDEX 01 LBA> <0 or 4>
```

Each track has one line. The parser rejects bad versions/fields, trailing
tokens, invalid characters/numbers/hashes, ordering violations and excessive
tracks. The exporter hashes the source image and refuses an output alias of
that source. **Headless trusts the descriptor's hash as provenance; it does
not reopen or authenticate the original disc.** `--toc` alone enables transport
and volatile BRAM, without firmware or video timing; it supplies no readable
sector backend. Both optional argument orders with `--bios` are supported.

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

The current native-module ABI is **7**, including TOC/response/auto-ACK state.
Regenerate older modules and rebuild all consumers. No serialized state
format exists to migrate. Future states must include both data latches, phase,
ACK, command and response bytes/positions, pending event and auto-ACK deadlines,
attached TOC identity/geometry, IRQ state and BRAM contents.

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
  instead. The runtime follows Geargrafx's active-bit rule. The retained idle
  suite did not generate live IRQ sources; transport checks have separate scope.
- Geargrafx/Mesen use bit 7 to lock or unlock on every `$1807` write; Beetle's
  pinned implementation only enables on a set bit. Hardware confirmation
  remains useful before calling these edge cases console conformance.
- Geargrafx accepts unsupported commands with GOOD status and implements
  REQUEST SENSE as delayed GOOD without returning sense data. Mesen also lacks
  that command. The runtime refuses unsupported commands rather than presenting
  those reference shortcuts as implemented drive services.
- Geargrafx/Mesen send four bytes for each supported directory mode. Beetle
  sends two, three and four respectively, and its source notes that physical
  response lengths were not confirmed. It also treats unknown modes as mode
  zero; this runtime refuses them. The four-byte profile is reference evidence,
  not a hardware-conformance claim. The `$AA` leadout sentinel agrees with
  Beetle and Geargrafx's above-last-track result.
- On the observed DATA IN selection-abort transition, Geargrafx retains the
  old DATA IRQ `$40` while adding STATUS IRQ `$20`, producing active `$60`
  until ACK clears REQ and both sources. The runtime preserves this reference
  behavior. Ordinary requested data/status bytes expose `$40`/`$20` respectively.
  Mesen's intermediate phase-clear IRQ update appears to differ in source;
  it was not run live. This edge is emulator compatibility, without hardware
  confirmation.

The public fixture is entirely authored RAM code. It checks 61,440 expected
native/interpreter load/store cases, all input bytes under four flag contexts,
the whole BRAM extent, MPR aliases, RMW read side effects, indexed hole
crossings, operand mutation, deadlines and explicit faults. The independent
MCP suite uses an authored 256 KiB bootstrap and blank 300-sector CUE/BIN,
then requires `is_cdrom_hardware_enabled=true`. This avoids comparing against
an emulator with CD hardware disabled. No retail BIOS/disc/save is needed.
See [REFERENCE.md](REFERENCE.md) for measured results and reproduction.

The transport suite passes 8,369 groups, including 4,096 independently expected
latch/control groups and 4,096 TSB/TRB control groups, plus directed edge/refusal checks. Byte
groups cover all 256 latch/control values, four status contexts, two speeds
and both execution tiers. Literal 75,000/3,000/450,000/1,500-tick edges,
held ACK, repeated selection within COMMAND, reset cancellation, IRQ2 refusal, operand mutation and
deadlines are local expectations. They are distinct from settled emulator
observations and do not qualify a media backend.

The TOC extension adds 418 independent groups for literal response/BCD,
DATA IN, auto-ACK, reset/abort and refusal in the same synthetic test binary. Frontend
geometry tests and headless parser-boundary tests separately cover descriptor
construction, source protection and untrusted metadata. See REFERENCE.md for
the independent mixed-track sequence scope. One pending-response/auto-ACK
reset plan remains unqualified after reproducible crashes of the isolated
Geargrafx reference process; local reset expectations are separate evidence.

## Sources

- [Geargrafx CD registers](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/cdrom.cpp),
  [memory routing](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/memory_inline.h)
  and [SCSI phases/commands](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/scsi_controller.cpp),
  [signals](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/scsi_controller.h)
  and [clock/IRQ helpers](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/scsi_controller_inline.h).
- [Mesen CD interface](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/CdRom/PceCdRom.cpp).
- [Mesen SCSI implementation](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/CdRom/PceScsiBus.cpp):
  latch separation, handshake and deliberately approximate timing.
- [Beetle CD interface](https://github.com/libretro/beetle-pce-libretro/blob/b96c11e095b6a40a412d2da02766ae1c3f4fd539/mednafen/pce/pcecd.cpp).
- [Geargrafx CHD geometry](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/cdrom_chd_image.cpp)
  and [TOC getters](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/cdrom_media_inline.h):
  INDEX 01, pregaps/postgaps and absolute leadout conversion.
- [Beetle directory commands](https://github.com/libretro/beetle-pce-libretro/blob/b96c11e095b6a40a412d2da02766ae1c3f4fd539/mednafen/cdrom/scsicd-pce-commands.inc):
  response-length differences and the `$AA` leadout selector.

These are research references, not linked or copied CPU/device implementations.
