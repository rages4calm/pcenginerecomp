# Measuring dispatch and module builds

Measure compilation and guest simulation separately. A shorter TCP replay can
reflect presentation pacing, startup, polling or different guest work; it does
not establish a faster native dispatcher. Correct guest results and independent
reference checks remain prerequisites for accepting an optimization.

## Authored dispatch workload

Configure with `PCE_BUILD_REFERENCE_PROBE=ON` and build
`pce-dispatch-benchmark`. The executable accepts one optional decimal iteration
count in `1..10000000` (default `100000`):

```text
build/pce-dispatch-benchmark.exe 100000
```

Use the executable name appropriate to the host. This authored workload uses
the capture reference plans, resetting CPU registers for each iteration and
executing the plan instruction followed by TMA through native dispatch. The
bus starts from each plan's authored RAM/ROM image and remains live across
iterations. An unsupported instruction, native miss or interpreted retirement
refuses the run.

Its output contains exactly `semantic` and `simulation_seconds`.
`semantic` records the workload name, plan and iteration counts, native and
interpreted retirements, master ticks, CPU cycles and an authored state/RAM
64-bit digest. That digest is a defined modulo-2^64 workload checksum, not a
cryptographic hash or a complete machine-state comparison. The measurement
script separately computes SHA-256 over canonical semantic JSON.

The probe's accumulated instrumented interval includes CPU setup, instruction
dispatch/execution, accounting and per-iteration checksum work. It excludes
process startup, per-plan image initialization, final RAM/generation checksum
work and JSON output. It is an authored CPU-dispatch microbenchmark, not a
retail game, device/rendering benchmark, hardware oracle or whole-program
performance result. A separate TCP replay verifies retained guest frames,
retirement totals, source identities and exposed CPU/device diagnostics.

## Reproducible receipt

`scripts/dispatch_benchmark.py` accepts `--spec`, a new `--out` path and optional
`--compare` successful baseline receipt. Paths in `inputs`, `implementation`
and `cwd` resolve relative to the specification file. Commands are nonempty
argv arrays, executed without a shell; shell operators and variable expansion
are not supported. Keep specifications, receipts and generated inputs private
under `.local/` when they contain local paths or derived code.

For a specification at `.local/performance/baseline.json`, this simulation-only
example runs an already built probe from the repository root. Replace the
checksum and compiler/host controls with the measured values before running:

```json
{
  "schema": 1,
  "workload": "authored-capture-dispatch-v1-100000",
  "cwd": "../..",
  "inputs": [
    {
      "path": "../../tests/generate_capture_reference_fixture.py",
      "sha256": "REPLACE_WITH_64_LOWERCASE_HEX_DIGITS"
    }
  ],
  "implementation": [
    {"path": "../../runtime/include/pce/runtime.hpp"},
    {"path": "../../runtime/src/runtime.cpp"},
    {"path": "../../pcerecomp/emitter.py"},
    {"path": "../../tests/dispatch_benchmark_probe.cpp"}
  ],
  "controls": {
    "compiler": "clang++",
    "compiler_version": "REPLACE_WITH_ACTUAL_VERSION",
    "flags": ["-O3", "-DNDEBUG"],
    "configuration": "Release",
    "architecture": "x86_64",
    "jobs": 2
  },
  "run": {
    "command": ["build/pce-dispatch-benchmark.exe", "100000"],
    "warmups": 1,
    "samples": 5
  },
  "timeout_seconds": 300
}
```

Include every immutable workload dependency in `inputs`: authored fixture
sources, generated plan/ROM/RAM data, workload configuration and the probe
source where applicable. Both compared specifications must use the same input
path labels and hashes. Record all changed compiler/runtime/generated source
and header files in `implementation`; they are fingerprinted for provenance
but may differ between baseline and candidate. Include the generated manifest
and all listed translation-unit/header identities in that provenance. The
example's short file lists illustrate the schema, not a complete provenance
inventory for every build.

```text
python scripts/dispatch_benchmark.py --spec .local/performance/baseline.json --out .local/performance/baseline-receipt.json
python scripts/dispatch_benchmark.py --spec .local/performance/candidate.json --out .local/performance/candidate-receipt.json --compare .local/performance/baseline-receipt.json
```

The script verifies pinned workload files before execution, then rechecks
inputs and implementation files afterward. It fingerprints the run executable
after any requested build and refuses a change during sampling. Each command
has a timeout of `1..3600` seconds and a 1 MiB output bound. Failed commands,
invalid/nonfinite timing, changed semantic results or changed pinned files
refuse the receipt. The output path must not already exist.

Run warmups are `0..10`; retained run samples are `1..50`. Defaults are one
warmup and five samples. Warmups are excluded from timings but must produce
the same complete semantic object as every measured sample. Receipts retain
all samples, median, minimum and maximum for instrumented simulation and
process wall time separately. Process wall time also includes startup, output
and the measurement wrapper's polling; report it under that name.

Comparison requires identical workload name, pinned input list, complete
controls object, recorded host fields, semantic object and semantic SHA-256.
No semantic fields are projected away. Controls are declared by the contributor,
not inferred from compiler invocations: verify the actual compiler version,
flags, target architecture, configuration, job count and commands. Additional
control fields such as `jobs` participate in exact comparison. The host record
contains system, release, machine and processor fields; it does not establish
identical load, frequency or thermal conditions. Keep those conditions stable
and describe exceptions. The reported ratio is baseline median divided by
candidate median; values greater than one mean a shorter candidate interval.

## Build measurements

An optional `build` object adds a separately timed command:

```json
{
  "command": ["cmake", "--build", "build", "--target", "pce-dispatch-benchmark", "--parallel", "2"],
  "scope": "total_build",
  "cache_state": "configured tree; all target objects removed; compiler cache disabled",
  "samples": 1
}
```

Add this object as `build` in the complete specification. Scope is either
`compile_only` or `total_build`; cache state is mandatory. The labels describe
your command's actual boundary: the script does not subtract linking,
configuration, generation or unrelated build work automatically. A target
build can include runtime compilation and linking. A module-object-only
command can measure compilation alone if its required generation/configuration
already exists and its exact inputs are recorded.

Build samples are `1..20`. Multiple samples require an explicit `prepare` argv
command before each timed build to establish the same cache state. Preparation
is outside the reported build interval. Use an owned preparation script with
fixed, verified scratch targets; avoid broad cleanup commands. Document whether
objects, generated sources, CMake state and compiler caches are warm or cold.
Use identical compiler, optimization/debug flags, architecture, job count,
target set and cache policy for both sides. Build comparison additionally
requires matching `scope` and `cache_state`. A one-sample build result remains
a single observation even though its summary includes a median.

Observed emission defaults to a 256-identity partition target, keeping
same-PC source variants together; the manifest reports any larger variant
group. `--partition-size` controls the target. `--single-unit` uses the current
exact-key dispatch and body sharing in one translation unit. It does not
restore the former linear variant chain. Compare those forms to isolate build
partitioning; a legacy-strategy comparison needs a separately pinned earlier
checkout and its generated source.

`pce_add_native_module` compiles each listed translation unit separately and
shares its object-library target across consumers of the same module/manifest
within one CMake configure tree. Headless and desktop links reuse those objects.
This is not a persistent cross-checkout compiler cache. All listed source and
header SHA-256 identities are verified; retain the whole generated artifact
set and manifest. See [CODE_CAPTURE.md](CODE_CAPTURE.md) and
[CONSUMER.md](CONSUMER.md) for contracts.

Report build timing, instrumented authored timing and retail TCP reproduction
as separate evidence scopes. Keep raw receipts and compare the guest workload
before describing any measured improvement.
