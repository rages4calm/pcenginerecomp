# Validated commands for caller-owned consumer sessions

`pcerecomp.project.prepare_launch` validates a built consumer and returns its
command and package bindings without starting the consumer or compiler. It gives
TCP drivers a supported alternative to reconstructing arguments and duplicating
private build-receipt checks. Normal `project.run` uses the same package admission.

```sh
python -m pcerecomp.project launch-plan .local/consumer/project.toml --build-dir .local/consumer-build --dev-port 0 --start-paused --reference-enabled
```

The result is a private JSON `pce-consumer-launch-plan` schema-1 object containing
`command`, the verified descriptor/SDK/input binding, build-receipt path/hash,
binary hash and output-file hashes. `executed` and `execution_evidence` are false.
There is no positive execution/qualification claim or implicit output file.
Commands and bindings can contain personal paths; keep saved plans private.

The Python API accepts the same typed development/capture/checkpoint/trace flags
as the immutable consumer command builder:

```python
from pathlib import Path
from pcerecomp.project import prepare_launch

plan = prepare_launch(
    Path(".local/consumer/project.toml"),
    Path(".local/consumer-build"),
    dev_port=0, start_paused=True, reference_enabled=True,
    code_capture=Path(".local/runs/new-capture.json"), capture_limit=65536,
    checkpoint_dir=Path(".local/checkpoints"),
)
argv = plan["command"]  # Pass directly to your owned process runner; never a shell.
```

Output parents and the checkpoint directory must already exist. Capture/trace
paths must be separate new destinations and are normalized before entering argv.
Planning does not reserve them; the host's exclusive creation remains authoritative.
Mutable BRAM/save sessions are deliberately owned by the separate `project.run`
save interface, not this immutable launch plan.

## Admission and lifetime

Admission verifies the source-pinned consumer, exact build binding, executable
content, complete adjacent output-file set and managed-generation state where
applicable. Build JSON rejects duplicates/nonfinite values and exact-type schema/
binding mismatches. Receipt bytes are revalidated while checking the package.
Planning derives the command, then re-admits the package and checks output
destinations before returning. Existing `run` also uses this stricter shared read.
Pause/write controls require actual booleans; a string such as `"off"` cannot
silently enable memory writes, and paused startup requires TCP.

These are content checks at admission, not a filesystem lock, signed producer
attestation or reusable launch lease. Prepare immediately before launch and keep
the selected package/media/source immutable for the session. A previously saved
plan must not replace current package validation. As with normal consumer builds,
the local builder/receipt and generated native source are trusted inputs.

The caller owns process creation, log streams, the TCP connection, input release,
termination on failure and waiting for actual process exit. Port zero is announced
as `PCE_DEV_PORT=N` on the owned host's stderr. Do not discover a port by attaching
to an unrelated owner process. An ACK to `quit` is not proof that files have closed.

For an exact same-build reference window, enable the capability in both launches
and select `DevClient.advance(..., reference=True)` before the reference host's
first dispatch. Start the native candidate fresh and do not select that reference
latch. Keep actual per-tier counters and capture producer metadata separate.
See [reference mode](REFERENCE_MODE.md), [TCP controls](DEV_SERVER.md) and
[checkpoint identity](DEVELOPER_CHECKPOINTS.md).

## Qualified scope

The authored native workflow obtains a plan, actually launches its argv and checks
the existing 200-native literal CPU endpoint. A separate private Bomberman consumer
uses the public planner for same-build cold reference/native and checkpoint-fork
sessions. Its finite first-stage results match full source keys/hits, stated paused
status fields, every WRAM byte and completed RGB; [status](STATUS.md) records exact
producer/counters and exclusions. Planning alone manufactures none of that work.
Runtime ABI 29, C++/CMake and checkpoint encoding are unchanged.

## Qualifying a new HuCard window

1. Capture a finite cold route from the exact board/header/encoding/region with
   no native module or with explicit interpreter-reference selection. Preserve
   the complete capture, media hashes, actual input/frame schedule and producer.
2. Use [preparation](PREPARE_PROJECT.md) with `module.kind = "capture"` or an
   original retained history, a HuCard-reset recipe and native-only runtime tier.
   Compile the candidate using the official [consumer builder](CONSUMER.md).
3. Derive fresh launch plans for that same built candidate's reference/native
   sessions. Replay the exact cold/input schedule. Never load an interpreter
   checkpoint from a different executable just because its ABI matches.
4. Compare actual source keys and per-key retirement totals using the existing
   [encoded relation](RAW_AUDIT_INTEGRATION.md), along with stated CPU/MPR/tick,
   memory and completed-frame expectations. Each memory inspection must retain
   its paused before/after replies. Declare all compared fields and exclusions.
5. Native-only success requires actual native work with no fallback or guard
   misses in the stated window. A finite positive window is not a complete game,
   independent emulator parity, multiplayer or hardware/audio qualification.

Large numbers of full MPR contexts can make stable layout produce many small
objects. For a cold candidate, balanced layout with an explicit partition size
can reduce translation-unit count; stable layout serves the supported managed
changed-unit workflow. Measure actual builds and preserve those tradeoffs rather
than assuming either layout is universally faster.
