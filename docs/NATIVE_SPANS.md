# Optional native instruction spans

Observed-code modules can opt into a second generated entry point that retires
several instructions before returning to the outer module dispatcher. The
existing `generated_step` entry and the default host path remain single-step.
This is an additive ABI25 capability: no `Cpu`/`Bus` layout or state format
changes, and legacy modules do not need to define a new symbol.

```sh
python -m pcerecomp emit-capture capture.json --out new-module --partition-layout stable --native-span
```

The emitted manifest includes `native_span = {schema: 1, protocol:
"per_instruction_v1"}`. Only the stable full-MPR/256-byte logical-PC layout is
supported initially. CMake validates the capability and propagates
`PCE_NATIVE_SPAN=1` through the module target to its consumer. Consumers using
`pce_add_consumer` get this automatically; copying object files without the
target's usage requirements does not select the capability.

Select the host profile explicitly with `--native-span 1..256`, or consumer
schema-1 `[runtime] native_span = 16`. Values above one require an opted-in
module. On a supporting module, an explicit limit of one uses the same span
interface as larger limits, providing a controlled batching reference.
Omission uses the legacy single-step path, even when the module supports spans.
The legacy path remains the default. Rebuild against the pinned toolkit source;
an ABI number alone does not identify the added header/helper capability.

## Every instruction remains a boundary

Each local part retains exact logical PC, all eight MPRs and fetched-byte
guards. It executes direct translated operations and the ordinary
`Bus::begin_instruction`/`retire` or `retire_speed` calls for every instruction.
Device clocks and sampled IRQ delivery are not deferred to the end of a span.
Writes to upcoming code, TAM mappings, branches, interrupts and returns are
checked again before the next operation. Leaving a part's mapping or PC range
redispatches without inventing a source guard miss. A genuine missing identity
counts one miss and uses the declared interpreter/fault policy.

`pce/native_span.hpp` provides explicit `NativeSpan`, `SpanHooks` and
`dispatch_span` APIs. The caller supplies the generated function pointer;
there are no ambient globals or thread-local execution modes. The before/after
hooks surround each attempted instruction, including a zero-retirement budget
or source refusal. A miss followed by interpretation shares one pending
boundary. Exceptions close it once and preserve the original exception.
Hooks can operate host controls and inspect/update allowed state, but advancing
CPU ticks, cycles or retirement counters from an observer is refused.

Both hosts preserve their per-instruction input scheduling, paused TCP/frame
boundaries, code-capture before/after pairs and presentation. Count limits are
retirements, not span calls. Tick deadlines retain the existing started-block
completion rule; a transfer is not suspended mid-instruction. Capture records
each actually retired identity individually. Capturing a span as one opcode
or skipping callbacks to obtain a benchmark result is not this protocol.

## Accounting and performance

Only an explicit host flag adds final `native_dispatch` JSON. It records the
protocol, supported capability, selected limit, batch/generated-entry counts,
native/interpreted completions, actual local continuations and maximum completed
batch. TCP status schema remains unchanged. Consumer execution receipts validate
the selected limit, module capability and accounting against actual CPU counters.
These host counters can differ across execution profiles; guest state, source
identity/hits and device/audio results still need their declared equality gates.

Fewer generated-entry calls do not establish faster execution. Boundary checks,
callbacks, duplicated optional code and host work can offset dispatch savings.
The optional authored benchmark compares the same binary's legacy and span
paths with fixed work, independent endpoint literals and alternating runs.
Finite original-Gear and retail evidence is recorded in [STATUS.md](STATUS.md).
Do not compare only against span limit one and call that a speedup over the
default path. No new general hardware or campaign coverage follows from batching.

Opted-in source contains separate direct-operation bodies for single-step and
span entries. `translated_body_count` retains its single-step meaning;
`native_span_translated_body_count` counts the additional span-path bodies.
Neither count is retired work. Cold compilation and package size can increase
even when the span entry is not selected at run time.
