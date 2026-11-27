# Consumer gameplay adapters

Ports can add optional gameplay settings without forking either host or putting
game-specific addresses in the toolkit. An authored C++ adapter and a small
source-site manifest are prepared and built alongside the translated module.
The existing launcher can select initial settings through structured arguments;
no new launcher or live RPC is required.

Start with the [complete authored example](../examples/title-adapter/README.md).
It implements independent earned-EXP/gold multipliers and optional post-hit
protection, including a pristine comparison and checkpoint forks. Its addresses,
reward rules and frame durations describe an original test program, not Ys III
or any other retail game. Each port must verify its own earned-reward callers,
spending/refund behavior, overflow and level rules, damage sites and timers.

## Declare and build

Add this optional object to the consumer preparation recipe:

```json
{
  "title_adapter": {
    "source": "adapter.cpp",
    "manifest": "adapter.json",
    "headers": ["adapter_state.hpp"]
  }
}
```

Paths follow the normal recipe-relative input rules. Headers are explicit;
their paths must stay within the source directory. Preparation copies a closed,
hash-bound `title-adapter/` tree, rejects links and extra members, and generates
the binding from the exact manifest bytes. It does not blindly copy directories.

The manifest has format `pce-title-adapter-1`, schema 1, an identifier,
`state_bytes` (0..4096), up to 32 integer settings and 1..256 events. A setting
declares `name`, `min`, `max` and `default` within signed 64-bit bounds. An event
declares `name`, logical `pc`, all eight `mpr` bytes, `selector` and `data`:
lowercase hex for exactly one legal instruction. See the example's
[fixture generator](../examples/title-adapter/fixture.py) for a complete manifest.

Managed adapter builds require the audited Windows LLVM-MinGW package-cache or
recoverable producer. The source, headers, manifest, generated binding and actual
compiler dependencies enter the build contract. Ordinary managed receipts are
refused for this extension. Direct CMake consumers can use `TITLE_ADAPTER` and
`TITLE_MANIFEST` in `pce_add_consumer`; caller-owned builds do not acquire audited
producer status merely by using these options.

## Select settings

Use the supported launch-plan API, with the same frozen SDK that built the port:

```python
plan = project.prepare_launch(
    descriptor, build_dir,
    title_mode="enhanced",
    title_settings={"exp": 2, "gold": 8, "protection": 1},
    title_audit=new_private_audit_path,
)
```

Setting names belong to the port, not the toolkit. Omitted values receive their
declared defaults. Unknown, duplicate, incorrectly typed or out-of-range values
are rejected. The CLI offers `launch-plan --title-mode enhanced` with repeated
`--title-setting name=value`; the host receives a canonical sorted setting string.
Settings are initial-only in v1. Existing launcher Choice controls can build
these arguments. `pristine` is the default: declared defaults only and no
callback execution. An enhanced 1x/off combination remains explicitly enhanced
and must be separately checked against pristine behavior.

## Callback and state contract

Implement `pce::consumer::title_adapter_after(TitleAdapterContext&)`. An event
matches the source recorded **before execution**: logical PC, complete mapping,
selector, physical fetch addresses and exact live instruction bytes. A matching
instruction invokes the callback once after successful retirement, device
synchronization and any interrupt entry. The post-register view may therefore
already show an interrupt handler. Zero-retirement attempts and exceptional
dispatch paths do not invoke it. Scalar and native-span dispatch share this rule.

The context exposes source/pre/post views, guest clocks, guest video frame,
settings and a scratch state span. Expected-value edits can change A/X/Y/P or
volatile RAM. The transaction checks every edit before committing; a callback
exception, conflicting alias or wrong expected value leaves its patches and
adapter state unapplied. The original instruction has already retired, so a
failed callback stops execution rather than rolling back that instruction.

PC, MPRs, stack pointer, guest clocks, retirement counters and device registers
are not mutation APIs. RAM edits cannot target ROM, BRAM, MMIO or declared hook
source bytes. Keep all persistent adapter data in the declared state span; use
guest time for gameplay rules. The adapter is trusted C++ code, **not a sandbox**:
mutable globals, external side effects and nondeterministic host-time decisions
are outside this supported checkpoint contract.

## Checkpoints, evidence and limits

Enhanced checkpoint files use an explicit schema-2 HOST extension containing the
adapter binding and opaque engine/consumer state, followed by the unchanged
canonical CORE. Mode, settings and source/build identity must match. Restoration
validates the whole envelope and counters before committing live state. Enhanced
native/repeat/reference comparisons retain adapter state; only the ordinary four
execution-tier counters may differ between native and reference runs.

Pristine checkpoint files retain the original schema-1 layout. Ordinary ports
without adapters retain their prior launch and checkpoint behavior. Enhanced
diagnostics are labeled in status/final reports and an optional bounded audit
file; that audit option requires enhanced mode. Adapter work never increments
guest instruction counts. On restore the
audit records its imported checkpoint origin separately from new callbacks.

Enhanced execution cannot produce original-program code captures, bus traces or
disc-origin discovery in v1. Keep discovery pristine and qualify enhancements
separately. Existing isolated, explicit BRAM export remains host policy; adapters
have no direct BRAM/file-save API. Cross-package continuation of adapter-bearing
packages and the CORE-only rewind helper are not supported in v1. The legacy
`project.run` qualification wrapper also refuses adapter options; use supported
prepare/build/launch planning and the example's explicit qualification workflow.
