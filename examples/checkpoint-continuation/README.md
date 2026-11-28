# Reproduce an additive native extension

The authored program loops through two counters, reaches a late instruction and
writes a marker. The source module declares every instruction except that late
entry. The destination adds exactly that guarded identity. Declarations contain
no execution hits. No ROM, firmware, debugger edits or GPU are used.

On Windows with the supported LLVM-MinGW/Ninja bundle:

```powershell
python examples/checkpoint-continuation/workflow.py --toolchain-root PATH_TO_BUNDLE --out .local/continuation-example
```

The default uses two compiled-cache-MISS producers. Select the actual recoverable
producer for either package without changing or flattening its sealed receipt:

```powershell
python examples/checkpoint-continuation/workflow.py --toolchain-root PATH_TO_BUNDLE --source-producer recovery --destination-producer recovery --out .local/continuation-recovery
python examples/checkpoint-continuation/workflow.py --toolchain-root PATH_TO_BUNDLE --destination-producer recovery --out .local/continuation-cache-recovery
```

Each invocation needs a new output directory and compiles both packages afresh.
The report records the producer choices and original receipt digests, and checks
that SDK, workflow and producer receipts stay unchanged through qualification.
Recovery selection tests completed recoverable builds; it does not deliberately
interrupt a compiler or migrate checkpoints from an older SDK.

The new output directory contains two audited compiled packages, an unchanged
source checkpoint, the reviewed admission and fresh source/native/repeat/
reference suffixes. Native repeats must match complete checkpoint bytes. All
four suffixes compare complete encoded HOST/CORE, full RAM, guest RGB, digital
PCM and per-identity retirements. Only four execution-tier counters and the
source package's one expected guard miss are projected.

The original prefix remains imported work. This is a bounded authored example,
not retail compatibility or whole-game coverage. The initial proof used a
25,579-native/zero-interpreter prefix and 12-frame suffixes: the source retired
329,342 native plus one interpreter instruction, while each destination native
suffix retired 329,343 native with zero fallback. Pending 39 PCM frames and the
759-frame source WAV cursor survived import. The reference suffix retired the
same 329,343 operations through the interpreter.

See [supported continuation contracts](../../docs/CHECKPOINT_CONTINUATIONS.md).
