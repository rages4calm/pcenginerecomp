# Offline checkpoint BRAM diagnostic

This authored example exercises a supported read-only export of the 2 KiB CD
backup-memory region from an exact, source-bound developer checkpoint. It uses
no game, firmware, disc, installed save or external owner input.

The guest first unlocks BRAM through CD port `$1807`, reads its complete initial
contents into RAM, writes an independently specified eight-page pattern, and
locks BRAM again by reading `$1803`. Every instruction has a native declaration.
The export runs only after the TCP host has quit. Its typed checkpoint admission
does not execute guest instructions or change the original checkpoint.

The workflow builds two fresh consumers. The first starts with an authored blank
BRAM asset and produces native, repeat and interpreter-reference checkpoints.
It compares the complete HOST/CORE payload, allowing only the four execution-tier
counters for reference. It also restores its own exact checkpoint without new
retirements. The second consumer takes the diagnostic bytes as a new immutable
BRAM asset, cold starts with its own identity, and verifies all 2,048 initial
bytes through genuine guest reads before running the same native/reference
comparison. No earlier checkpoint is rebound to that consumer.

From a frozen, committed SDK with the supported LLVM-MinGW producer:

```powershell
python examples/checkpoint-bram/workflow.py --out .local/checkpoint-bram/proof01 --toolchain-root PATH_TO_TOOLCHAIN
```

The default is headless. Optional `--desktop`, repeated `--dependency-root` and
`--cmake-arg` arguments support an explicitly bound SDL SDK; SDL video and audio
drivers remain dummy in this workflow. Each output root must be new. Receipts,
launch plans, TCP journals, checkpoints and diagnostic bytes stay under that
private root. Preserve failed receipts when retrying in a different directory.

Negative probes retain the ordinary reference/checkpoint `--bram-out` exclusions
and TCP BRAM-read refusal, and reject wrong hashes, malformed checkpoints,
changed source bytes and existing output directories. This is developer
diagnostic evidence. The bytes are not automatically a valid or authentic game
SAVE, a portable player save, or a retail/hardware compatibility result.
