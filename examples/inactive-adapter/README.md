# Inactive-adapter host benchmark

This Windows benchmark compares **the actual shared desktop host callbacks**,
using separately qualified baseline/candidate packages from the authored
[gameplay-adapter example](../title-adapter/README.md). It does not measure only
the core dispatcher. It never touches a retail game, firmware, owner save or
another project's running process, and it builds nothing automatically.

First qualify that example independently under each frozen SDK. Keep those SDKs,
packages and inputs in place. Then use a new output directory:

```sh
python examples/inactive-adapter/benchmark.py \
  --baseline-sdk BASELINE_SDK --baseline-qualification BASELINE_PROOF \
  --candidate-sdk CANDIDATE_SDK --candidate-qualification CANDIDATE_PROOF \
  --out .local/inactive-comparison \
  --ambient-note "Other concurrent machine activity was not controlled"
```

Each package is re-admitted by an isolated Python controller imported from its
**own frozen SDK**, before and after timing. No cross-package checkpoint is
loaded or rebound. Complete current producer/compiler/dependency audits are
rechecked. Cross-side admission compares machine/input/runtime policy, emitted
module and adapter identities, compiler/SDK/dependency hashes and effective
compile/link settings. Full source/asset inventories must differ only in the
intended host source; expected SDK/output-root relocation and its runtime-tree
digest are the only corresponding normalization. Shader assets are included.
The benchmark admits only the exact reviewed 170-byte original example program,
not arbitrary code that happens to use similar opcodes. It checks identical code/declarations,
disabled guest interrupts, fixed mapping and direct control-flow targets. Its
unreachable target lies outside that graph. It deliberately expects a paused
`instruction_limit` endpoint after a fixed retirement count; that is an explicit
benchmark criterion, **not** a successful `run_until` target/route probe.

Default modes are plain scalar, compiled-pristine scalar, compiled-pristine
span-eight and enhanced span-eight. Every cell uses a new owned host, runs an
untimed 250,000-instruction warmup, then measures exactly 6,000,000 further native
instructions. These values fit the original authored recipe's unchanged step and
tick allowances. Three ABBA groups per mode alternate baseline/candidate order;
all raw timings, polling counts and group ratios remain in the receipt. Each
logical ABBA cell sums three separate fresh-process segments. Segment order is
ABBA, ABBA, ABBA within each group, preserving temporal interleaving. The default
four-mode run therefore has 144 timed windows and 48 logical cells: 864 million
timed native instructions plus 36 million untimed warmup instructions.
Aggregated CPU/wall intervals are **not** one continuous execution interval and
do not include intervening startup, admission, inspection or teardown time.
Every raw interval and its endpoints remain available separately.

CPU deltas use [Windows GetProcessTimes](https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes):
kernel plus user time, summed across **all threads of the owned host process**,
in 100-nanosecond accounting units. These units do not guarantee timer resolution
at that scale. This is neither Python-controller CPU nor an isolated dispatch
clock. Wall intervals include TCP request/status work, polling and scheduling.
Startup, warmup, build/admission, full memory/image inspection and checkpoint
serialization are outside the measured interval. No WAV, source audit, code
capture or durable wire-journal flush runs inside it. Parsed endpoint/poll
observations are saved afterward; they are not a durable raw-wire journal.
The initial plumbing pilot produced about 0.4-second intervals with CPU values
on a 15.625-ms grid, too short/coarse for a micro-gain claim. The receipt records
the actual raw accounting grid and distributions; summing segments does not
create finer underlying CPU-clock resolution.

After timing, full RAM, guest RGB and complete HOST/adapter/CORE checkpoint
bodies must agree across all runs within each mode. **No guest counters, clocks,
audio or host fields are normalized.** Only the outer package identity header
differs. Actual native/interpreted totals and zero guard misses are checked.
Per-source timed execution counts are not captured; source identities come from
the admitted authored graph. Independent functional TCP/checkpoint qualification
remains separate from this throughput comparison.

Dummy SDL video/audio and software rendering keep the measurement off physical
devices. Run it separately from compiler/full-test loads. Other active projects,
CPU frequency changes, OS accounting granularity and background work can still
affect results. Preserve distributions and overlapping ranges; report an
inconclusive or undetectable effect when appropriate. These samples cannot prove
that an unrelated historical game slowdown had the same cause. Failed cells
remain failed, with owned hosts stopped; no automatic retry overwrites them.
