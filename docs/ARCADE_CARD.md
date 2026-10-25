# Arcade Card Duo expansion

The optional Arcade Card Duo profile adds **2 MiB of expansion RAM** to an
explicit Super System Card machine. It models the console's memory expansion
interface; it is separate from arcade-machine emulation. No title detection,
firmware service, host persistence or automatic attachment is supplied.

```sh
build/pce-headless --system-card-reset super system-card.pce 1000000 30000000 hybrid --arcade-card duo
```

Both hosts accept the same option. Omit it for the original hardware profile.
`duo` is the only accepted value; standard System Card, HuCard and snapshot
recipes reject attachment. Arcade Card Pro and SuperGrafx are separate
hardware profiles and remain unsupported.

Consumer schema 1 adds one optional boot field:

```toml
[boot]
mode = "system-card-reset"
profile = "super"
arcade_card = "duo"
```

Normal BIOS/module/tool/input pins and execution limits remain required.
Startup metadata adds `arcade_card: "duo"` only when enabled. Paused TCP status
and final JSON then add the live ports, shifter, access counters and RAM size.
Diagnostics do not read data ports or advance guest time. Disabled recipes
retain their previous metadata shape and behavior.

## Data ports and mapped windows

There are four independent ports, each with a 24-bit base, 16-bit offset,
16-bit increment and seven-bit control. All ports access the same expansion
RAM. Effective RAM addresses wrap modulo 2 MiB; base updates wrap at 24 bits
and offset updates at 16 bits.

Physical banks `$40..$43` are **side-effecting I/O windows** for ports 0..3.
Every offset in a bank accesses that port's data byte, then applies its
configured increment. Incrementing the CPU address does not itself select
another expansion-RAM byte. Hardware registers `$FF:1A00..1A3F` provide the
same four ports; `$1A40..$1A7F` mirrors those registers.

| Port register | Read/write contract |
|---|---|
| 0, 1 | Data at the previous effective address; increment afterward |
| 2, 3, 4 | Base address, low byte first |
| 5, 6 | Offset, low byte first; optionally trigger base addition |
| 7, 8 | Increment, low byte first |
| 9 | Control bits 0..6; bit 7 discarded |
| A | Read zero; optional explicit offset-add trigger on write |
| B..F | Read `$FF`, ignore writes |

Control bit 0 enables auto-increment; bit 1 includes the offset in the
effective address. These are independent: **control 3** enables a sequential
offset-based stream, while control 1 advances an offset that does not yet
contribute to the data address. Bit 4 increments the base instead of the
offset. Bit 3 unconditionally subtracts `$10000` from the offset; it does not
sign-extend based on offset bit 15. Bit 2 is retained but otherwise unused.

Bits 5..6 choose when to add the adjusted offset to the base: 0 never,
1 on offset-low writes, 2 on offset-high writes, 3 on register-A writes.
The updated offset value participates in the triggering addition. Writing
control does not itself add the offset.

## Shifter, identification and reserved addresses

`$1AE0..$1AE3` read/write a little-endian 32-bit register. Writing `$1AE4`
retains the low nibble and shifts: 0 leaves the register unchanged, 1..7
shift left, 8..15 shift right by `16 - nibble`, filling with zeros. `$1AE5`
uses the same distances and directions for rotation. Each amount reads back
independently.

Identification reads are `$1AFC=00`, `$1AFD=00`, `$1AFE=10`, `$1AFF=51`.
The global registers do not have a second 16-byte mirror: `$1AF0..$1AF5`
read `$FF`. Other holes in the enabled `$1A00..$1BFF` decode read `$FF` and
ignore writes. With the expansion disabled, the original CD register policy
is retained. No address beyond this decode is silently added.

## Execution, inspection and state compatibility

Native instructions in ordinary ROM/RAM use the ports through the shared
bus, including LDA/STA, read-modify-write and block transfers. Source guards
must not treat the four windows as stable RAM: pure source peeks return
unreadable, and native execution misses before touching the port.

The interpreter reads live opcode/operand bytes through the bus. Executing
from a port can therefore advance it on each fetch. Such instructions remain
unreadable to the source observer; its capture records explicit loss rather
than inventing a stationary native identity. An operand crossing into a port
window follows the same distinction.

The normal debugger RAM read/CAS APIs reject these I/O windows. `Bus::load`
also rejects any intersecting range before writing ordinary memory or changing
generations. Expansion RAM is reached through its device API or real guest
operations, not a fictional flat physical RAM alias. Guest-clock ordering
uses the existing instruction-level bus profile; exact electrical access
phases and contention are not qualified.

Attachment is setup-only: an unpowered Super System Card bus and initial
device clocks are required. RAM defaults to zero, with an explicit fill byte
available to low-level callers. No warm reset or save-state format is added.
Future states must preserve all expansion RAM, four port states, shifter and
amounts. Host handles are not part of that state.

**ABI 20** introduced the expansion owner; current runtime **ABI 21** adds
the stopped timer phase. Re-emit retained ABI-12 through ABI-20 observations without changing their original labels, then
rebuild modules and runtime together. See [consumer upgrades](CONSUMER.md)
and [independent reference scope](REFERENCE.md).
