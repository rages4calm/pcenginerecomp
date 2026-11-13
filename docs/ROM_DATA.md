# Source-qualified ROM data discovery

Opt-in immutable data-load analysis lets static discovery follow bank selectors
and indices loaded from authorized ROM. It derives candidates; it does not turn
static predictions into observed execution or replace runtime memory reads.

```sh
python -m pcerecomp discover-roots seeds.json --image card.pce --rom-range 0:20 --rom-data-range 256:6 --out new-data-graph
```

This short example authorizes only those decoded-ROM offsets. Supply the actual
code/data ranges for your image, or use the complete
[authored native workflow](../examples/rom-data/README.md) without a game or BIOS.
Python callers use `discover_roots(..., rom_data_ranges=[(offset, length), ...])`.
The repeated CLI option is `--rom-data-range OFFSET:LENGTH`. It accepts 1..256
typed, nonempty, image-bounded ranges; malformed integers, booleans, fractional
values and empty sets refuse. Omitting it preserves old policy/artifact bytes.

## Reads and permissions

All 16 non-immediate LDA/LDX/LDY addressing forms can acquire register facts:

| Register | Forms |
| --- | --- |
| A | direct page, direct page X, absolute, absolute X/Y, indexed indirect, indirect indexed, direct-page indirect |
| X | direct page, direct page Y, absolute, absolute Y |
| Y | direct page, direct page X, absolute, absolute X |

Immediate loads keep their existing facts without a new data-read witness.
Each actual static read must independently resolve to driven immutable HuCard
ROM under the exact image/header/encoding/board selector and all eight MPRs.
RAM, I/O, undriven sources and the Populous writable aperture remain unknown.
Code ranges do not grant data permissions. Data ranges grant neither instruction
admission nor jump-vector permissions. Indirect loads need data permission for
both pointer bytes and the terminal value; a permitted terminal alone is insufficient.

Direct-page indexing wraps at eight bits in logical $2000..$20FF, including the
high byte of a pointer at $20FF. Absolute/indirect endpoint addition wraps at
16 bits. Every byte uses its own current mapping, including page/bank boundaries.
Unknown indices or denied reads leave the loaded register unknown while unrelated
flow continues. A later TAM requiring unknown A still stops explicitly.

Known facts can feed existing TAM, index/vector and bounded synchronous-call
analysis. Incoming facts join conservatively; conflicting predecessors retract
stale facts/descendants. This is not general ALU evaluation, writable memory
simulation, interrupt recovery or RAM/CD overlay source discovery.

## Graph contract

The new policy is `bounded-source-qualified-rom-data-v1`. Its options retain
`rom_data_ranges` and may compose `rom_vector_ranges`, `call_depth_limit` and
`rom_table_limit` under their existing restrictions. A single data policy avoids
inventing a policy string for every combination. Older readers reject it.

Each eligible node records `rom_data_load` with register, mode and ordered reads.
Each read retains its role (`pointer-low`, `pointer-high`, `value`), logical
address, physical address, decoded-ROM offset and byte value. A resolved record
adds `status: resolved` and its value. An unknown record retains `reason`, `detail`
and any successfully read pointer prefix. Summary counts separate
`resolved_rom_data_loads` and `unknown_rom_data_loads`. These count retained
analysis nodes, not guest retirements. A failed fact lookup is separate from
the control-flow frontier in `unresolved`.

The exact three-file closure remains `seed-roots.json`, `roots.json` and
`discovery.json`. Admission independently rederives every read, mapping, fact,
edge and count from the original seeds and bound image. Rehashing edited metadata
does not authenticate a graph. Copying and
[discovery-backed preparation](DISCOVERY_CONSUMERS.md) retain that closure.
Declarations have no fabricated hit counts or execution evidence.

Generated operations still load actual live memory. Changing a ROM-data copy
can change a register or bank at runtime; normal full-context/source guards
refuse uncompiled routes. No predicted value or jump target is baked into code.
Runtime C++/emitter, ABI 29 and checkpoint encoding are unchanged. New source,
package or build identities still require fresh exact-build checkpoints.

## Verification

Frozen `22b5a7fbf8fd93f47035bf7a38e8c694bca04955` passes **2,175 Python tests
without skips, 74 C++ suites and 12 fresh-process audio cases**. All 771 tracked
inputs stay unchanged through the required checker. SDK SHA256
`ffd0708d2fa92dea363aae3e3528dc2f6a73fb8736593467f3567eacc0ed52bf`
covers 95 source files. Later publication edits are Markdown only.

Fourteen data-analysis tests cover addressing/wrap, independent pointer
permissions, mappings/selectors, RAM-source refusal,
unknown indices, conservative joins, calls/vectors/tables, strict options,
tampered witnesses and exact copying/preparation. Five workflow tests include
actual native compilation/execution. Twelve legacy default/vector/call/table
graphs remain byte-identical to committed `b3ce5e9b`; its reader rejects the
new data policy. Eight additional authored static checks cover all four
header/encoding combinations and separate Populous RAM/undriven/WRAM/I-O source
refusals; these are derivation checks, not executed emulator comparisons.

The authored main route expands four candidates to 17. With 64 additional
explicit seeds, the combined graph expands 260 to 273 candidates with 70 resolved
loads. The cold route executes 17 native/zero interpreted/zero guards. Separate
native/reference main probes execute 17 each; separate 64-case load matrices
execute 256 each and cover all 16 forms with four directed byte values. All
273 source identities are exercised across these distinct windows, not one
continuous run. Literal CPU/flags/MPR/clock/full-8192-byte-WRAM and exact encoded
key/hit expectations pass. The main route costs 87 cycles/1044 master ticks.

A changed private data value produces the changed native result without fallback.
Changed bank/source copies refuse after four/ten native instructions respectively,
each with zero interpreted and one guard miss, no added guest work/clocks or
memory effects at refusal. Original files stay unchanged. The probe links the
official builder's exact runtime archive; Windows packaged DLLs are checked and
it runs without SDK PATH entries.

Fresh Geargrafx 1.8.4 independently matches CPU/flags/PC/MPRs and all WRAM bytes
for the authored main route and 64 load cases. Reference-only setup/presets are
separate. This is not external clock/bus/device/audio/video or hardware parity.

A fresh shared-layout Rondo consumer separately repeats cold TCP boot/file
creation/introduction: **404,669,933 native/zero interpreted/zero guards**,
25,621 exact source keys/hits and 17 full-state/WRAM/CD-RAM/completed-RGB samples
match the same-build interpreter and original expectations. Fresh native-owned
checkpoint forks agree on 59,672 new instructions/753 keys; the imported
379,716,149-native prefix remains separate. Post-close raw journals, full memory
bytes and independent PNG CRC/pixel decoding pass, with no RAM-write requests.
This is a regression of the existing captured route, not retail ROM-data-policy
qualification, playable action, whole-game or independent retail/audio evidence.
Host audio is off; old captures retain their original producers. Ys III stays parked.
