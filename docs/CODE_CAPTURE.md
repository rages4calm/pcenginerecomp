# Retired-code capture and native emission

The optional host observer collects exact identities of instructions that
actually retire. It supplies an offline compiler input for overlays, MPR
changes and self-modifying code without guessing a global control-flow graph.
It is available in both headless and desktop hosts and does not change runtime
ABI 12. This is an execution profile, not a save state or complete program.

**Captures contain game or firmware instruction bytes. Keep them and generated
modules private.** Store local experiments in ignored scratch. Do not publish
retail captures, generated source or title-specific debug addresses as fixtures.

## Capture a bounded run

Add these options to the existing host command:

```text
--code-capture .local/capture/run.json --capture-limit 65536
```

The output parent directory must already exist. The filename must be new;
exclusive creation refuses existing files, symlinks and hard links. The host
also refuses an alias with another input or capture output. There is no implicit
output location or overwrite option. The normal tick, instruction and optional
wall-clock limits still apply. `--capture-limit` requires `--code-capture`,
accepts 1 through 65,536 identities, and defaults to 16,384.

With capture absent, the host does not inspect instruction source for this
feature, allocate its identity tables, write a capture or add diagnostic fields.
The opt-in path increases host work and retained private data; include it in
batch storage and wall-time accounting.

Before dispatch, the observer reads only the instruction's exact decoded length
through side-effect-free RAM/ROM peeks. Each byte maps independently, including
MPR page boundaries and logical `$FFFF` wrap. No neighboring bytes, CPU semantic
registers, broad RAM, BRAM or MMIO contents are captured. After dispatch it
accounts for a native or interpreted retirement; budgets, unsupported exits,
guard misses and faults before retirement do not become observations. An
instruction that retires before a later interrupt-service fault is counted.

The file is finalized after the execution loop, including an ordinary requested
TCP quit or a caught guest bus fault. An interrupted process, host setup failure
or failed output write may leave an empty or partial file. Such a file is not a
valid capture and must not be used as qualification evidence.

## Schema 1

The top-level fields are:

| Field | Meaning |
|---|---|
| `schema`, `runtime_abi` | Exactly 1 and 12 |
| `capacity` | Maximum unique identities retained |
| `retired_instructions` | All observed native plus interpreted retirements |
| `dropped_instructions` | Retirement occurrences for new identities when full |
| `unreadable_instructions` | Retirements whose complete bytes could not be safely peeked |
| `complete` | True exactly when both preceding loss counters are zero |
| `observations` | Deterministically ordered unique instruction identities |

Each observation contains `pc` (16-bit logical address), `mpr` (all eight
mapping bytes), `physical` (21-bit address for each fetched byte), `data` (exact
instruction bytes), `native_hits` and `interpreted_hits`. The full MPR mapping
and logical PC plus bytes identify a record; physical addresses are explicitly
recorded and checked against that mapping. Repeated byte variants at one PC,
multiple MPR contexts and overlapping retired interpretations remain separate.
No snapshot generation or complete memory image is implied.

Hit counts are nonnegative 64-bit integers with a nonzero sum per identity.
All retained hits plus both loss counters must equal `retired_instructions`.
After capacity is reached, already-retained identities continue accumulating
hits. Dropped occurrences do not report the number of distinct missing sites.
`complete` describes loss within this observed run only: it says nothing about
unvisited code, alternate inputs or campaign coverage.

## Emit a private native module

```text
python -m pcerecomp emit-capture .local/capture/run.json --out .local/native/run
```

The output directory must be new. The command reads at most 64 MiB, rejects
unknown or duplicate JSON fields, booleans used as integers, malformed lengths,
incorrect physical mappings, duplicate identities and inconsistent counters.
The existing ISA decoder derives operation metadata and branch targets rather
than trusting capture-supplied mnemonic or target labels.

Emission produces `module.cpp` and `module.json`. Every supported observation
has direct translated C++ operations, with no per-opcode interpreter call.
Dispatch first checks the instruction deadline, then selects an exact packed
full-MPR context and logical-PC case. Exact source-byte guards choose among
variants before any guest mutation. A stale mapping, changed bytes, unobserved
PC or unsupported opcode returns a native miss. The host's configured dispatcher
then interprets or explicitly stops; it does not invent a replacement operation.

The manifest retains schema 1 / ABI 12 / `native_instructions_emitted` and adds
the capture SHA-256, context count, retained hit totals and loss metadata.
`execution_evidence` remains false: emitting source proves neither successful
compilation nor executed native coverage. Report executed native/interpreted
counts from a separately bounded replay, compare semantic diagnostics and guest
images, and retain an independent reference scope where available.

A capture made under a game-specific patch includes those patched source
identities. Do not promote temporary cheat code into a distributed module.
Consumers must select appropriate source identities and document any removed
observations. Guarding a patched identity prevents an accidental match to the
original bytes; it does not make that patch an appropriate production input.
