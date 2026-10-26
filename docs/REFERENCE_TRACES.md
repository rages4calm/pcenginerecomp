# Independent instruction-boundary traces

`pcerecomp.reference_trace` validates code-free CPU traces and reports the
first difference between independently produced runs. It complements native/
interpreter comparisons: those tiers share toolkit devices, while a separate
emulator can expose a shared device or scheduling defect.

```sh
python -m pcerecomp.reference_trace EXPECTED.jsonl ACTUAL.jsonl --out NEW_REPORT.json
python -m pcerecomp.reference_trace EXPECTED.jsonl ACTUAL.jsonl --profile architectural-elapsed-v1 --out NEW_REPORT.json
```

Exit 0 means equality under the named comparison profile, 1 means a valid
comparison found a difference, and 2 means invalid input or a file operation
failed. An output path must be new; an existing report is never overwritten.
Reports contain no input file paths. The Python APIs are `load_trace(path)`,
`parse_trace(bytes)` and `compare_traces(expected, actual, profile='exact')`.

## Wire format: pce-cpu-trace-1

A UTF-8 JSONL stream contains exactly these records, in order:

1. `header`: schema 1, format `pce-cpu-trace-1`, engine identity, fixture
   SHA256, case label, `clock: "master-ticks"`,
   `phase: "instruction-boundary"` and explicit unavailable fields.
2. `initial`: the actual state at the start of the measured window.
3. Zero or more `instruction` records: contiguous ordinal starting at 1,
   entry PC, complete entry MPRs and the actual post-instruction state.
4. `final`: actual executed count, `stop: "instruction-limit"` and
   `complete: true`. Missing, extra or truncated records are errors.

Engine identity contains `name`, 40-hex `revision`, 64-hex `source_sha256`
and `binary_sha256`. A fixture digest identifies the exact authored input.
Header identity is provenance metadata: validating its shape does not
authenticate an executable. A qualification runner must independently bind
the actual source, build, binary, input and raw output.

Every state contains `pc`, `a`, `x`, `y`, `sp`, `p`, all eight `mpr` bytes,
`mpr_latch`, `physical_pc`, `clock_divisor`, raw `ticks` and `wram_sha256`.
PC and physical PC describe the next instruction boundary; physical PC must
agree with that state's complete mapping. Each instruction's entry PC/MPRs
must equal the preceding state. Clocks must strictly increase at retirement.
WRAM digests cover the defined 8 KiB work RAM, observed without guest MMIO
reads. No opcode bytes, disassembly, image data or RAM dump is included.
The fixture hash identifies the input, not every dynamically rewritten code
overlay. Boundary PC/MPR fields alone cannot establish overlay source
identity. Use the separately guarded code-capture contract for byte-aware
native promotion; this trace schema does not replace it.

`unavailable_fields` is either `[]` or `["mpr_latch"]`. In the latter case
every state must contain `mpr_latch: null`. A producer must never fabricate a
latch value for an emulator that has no equivalent state. No other state
field can be omitted or declared unavailable in this schema.

The parser rejects duplicate/unknown keys, booleans masquerading as integers,
invalid ranges, malformed hashes, non-finite numbers, incorrect mappings,
broken entry chains and loss of closure. Limits are 100,000 total records
(at most 99,997 instructions), 16,384 bytes per line and 128 MiB per stream.
These are input protocol bounds; they do not limit a project's implementation
work or replace a qualification's explicit execution scope.

## Comparison profiles and honest differences

| Profile | State comparison | Clock comparison |
|---|---|---|
| `exact` | Every raw state field, including latch availability/value | Raw master ticks |
| `architectural-v1` | Excludes only `mpr_latch` | Raw master ticks |
| `architectural-elapsed-v1` | Excludes only `mpr_latch` | Ticks relative to each trace's recorded initial state |

Elapsed comparison preserves both raw clock origins and every instruction's
raw timestamp. It removes only the initial epoch offset; speed-transition
or later timing differences remain visible. No profile masks status bits,
MPRs, registers or memory hashes. There is no arbitrary ignore-field list.
Excluding the transfer latch does not establish TAM/TMA latch parity.

The report retains both engine identities, trace hashes, checked and
unchecked fields, the clock policy and initial origins. A difference includes
its ordinal, field and actual values; elapsed timing differences also include
both elapsed values. Ordinal 0 means initial state. The matched-instruction
count describes the prefix before the first difference, not all later state.
Fixture/case/clock/phase mismatches make the comparison incompatible.

Two engines can agree under a finite comparison and still share a defect.
Keep independently authored expectations, hardware documentation and other
references alongside these records. Never rewrite raw traces or broaden a
profile simply to remove a disagreement.

## Full-core reference boundary

The Beetle adapter uses the pinned original PCE core's built-in
`HuC6280::Run(true)` instruction-step path and original memory/device setup.
Libretro's ordinary `retro_run()` operates at frame granularity and is not
presented as an instruction debugger. Initialization/reset work and any guest
primer are separate from measured instruction retirement.
The default v1 adapter requires CPU I to be set at every stepped entry, including
primers and block continuations. It explicitly stops before an unmasked step:
the original API can return after IRQ entry without an opcode retirement.
The separate opt-in [IRQ-aware v2 observer](IRQ_TRACES.md) retains explicit
raw-call accounting and post-IRQ retirement groups. It does not silently enable
unmasked stepping in v1 or count IRQ entry as an instruction. Its finite
qualified domain and reference disagreements are documented separately.

The reference executable is built separately from user-supplied/pinned GPL
source. Its source is not vendored into the MIT runtime, and the reference
does not link the toolkit's emulated CPU or devices. Shared authored helpers
only encode traces and hash observations. Trace reads must not change CPU,
memory or clocks; independently checked raw RAM digests guard the hash helper.
See [REFERENCE.md](REFERENCE.md) and [STATUS.md](STATUS.md) for the actual
reference fixtures, source identities, disagreements and qualification scope.

The public adapters are optional developer tools; baseline builds/tests need
no emulator checkout, BIOS or retail image. Reproduce the authored suite with
new private outputs and the exact pinned reference sources:

```text
python scripts/speed_trace_reference.py --gear-source PINNED_GEAR --tool-source PINNED_TOOL --out .local/speed-reference --library LIBCHDR --library LZMA --library MINIZ --library ZSTD
python scripts/beetle_reference.py --beetle-source PINNED_BEETLE --rom .local/speed-reference/fixture/authored.pce --primer 20 --steps 161 --case software-primer-mixed-speed-masked-timer-v1 --compare .local/speed-reference/native-trace.jsonl --profile architectural-v1 --out .local/beetle-reference
```

Both scripts bind existing tools and actual source/build/output files. The
Beetle helper pins upstream commit
`b96c11e095b6a40a412d2da02766ae1c3f4fd539`; Gear uses
`1c62a549328241518101f5be5bf3e6840b96ea5d`. Current compiler/CMake/Ninja
executables can be selected with explicit flags. The native suite emits
direct code from the authored snapshot, not an interpreter bridge. The
Beetle reference keeps normal original CPU/device implementations in a
separate executable; optional CHD and physical-drive interfaces are disabled
for this HuCard-only fixture. No video, audio, CD or whole-library parity is
established by CPU trace equality.
