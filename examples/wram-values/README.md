# Writable data → banked native code and indirect calls

This original 32 KiB fixture needs no game or firmware. It follows explicitly
permitted ROM data through WRAM, T-mode arithmetic and bank changes, then uses
RAM pointers for a safe store inside a call and a later indirect JMP. Generated
operations keep their actual CPU/bus reads, writes, flags and source guards.

Run from the repository root with a **new** destination:

```powershell
python examples/wram-values/workflow.py create .local/wram-example
python examples/wram-values/workflow.py prepare .local/wram-example
python examples/wram-values/workflow.py qualify .local/wram-example
```

`qualify` accepts `--generator` and repeatable `--cmake-arg`. It builds the
official pinned consumer, then links a probe against that exact runtime archive.
Windows probes use verified packaged DLLs with only Windows directories on PATH.
Creation, preparation, compilation and execution have separate receipts. The
workflow binds original inputs, helper sources, SDK, derivation closure, generated
probe expectations and captures; changed inputs refuse qualification.

The main route retires **45 native / zero interpreted / zero guard misses**,
173 cycles / 2,076 master ticks. Separate **354 reset/preset cases** cover 208
memory RMW/bit changes, 40 T-mode logic/binary/decimal operations, 72 BIT/TST
tests and all 34 scalar memory load/store addressing forms. Each tier retires
3,716 matrix instructions. Every one of the 3,761 declared source identities
executes across these distinct windows; they are not one continuous guest run.

Literal CPU/flags/MPR/clocks, every WRAM byte, exact encoded source keys/hits and
native/interpreted counts are checked. Two explicit host RAM mutations confirm
live behavior: a changed pointer reaches an omitted target after 38 native
instructions; a changed T-mode destination drives a different bank after 25.
Both refuse with zero interpreted / one guard and no guest effects at refusal.
These are authored negative fixtures, not retail progress or game patches.

Only 13 canonical WRAM bytes are permitted to analysis. Initial memory remains
unknown until the guest writes it. Uncertain writes lose facts. The stack page,
devices, general block-copy values, unknown-index RAM tables and RAM code fetches
are outside this policy. See [the static discovery contract](../../docs/STATIC_DISCOVERY.md).
This example alone supplies internal native/reference evidence; it does not
establish independent emulator, interrupt, device, retail or hardware parity.
