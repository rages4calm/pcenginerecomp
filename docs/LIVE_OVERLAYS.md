# Live RAM and CD overlay candidates

This interface captures reported RAM bytes from an already paused TCP consumer,
derives bounded instruction candidates and composes several RAM epochs into one
guarded native module. It complements [recorded histories](OBSERVATION_HISTORY.md)
and [explicit source sets](SOURCE_SETS.md); snapshots do not manufacture retired
instructions, capture hits or checkpoint origins. Runtime ABI **29** is unchanged.

## Workflow

Start your verified consumer with the [TCP development server](DEV_SERVER.md)
paused. Use the port announced by that owned process. The descriptor, build
receipt and executable must still match the local package. Destinations below
must be new; the example physical range is one standard CD-RAM bank.

```sh
python -m pcerecomp capture-overlay consumer/project.toml --build-dir consumer-build --port 12345 --ram-range 0x100000:8192 --journal .local/epoch-wire.jsonl --out .local/epoch
python -m pcerecomp discover-overlay .local/epoch --code-range 0x100000:8192 --entry 0x4000 --out .local/candidates
python -m pcerecomp compose-overlays .local/candidates --out .local/overlay-library
python -m pcerecomp verify-overlays .local/overlay-library
python -m pcerecomp emit-overlays .local/overlay-library --partition-layout shared --partition-size 1024 --out .local/overlay-module
```

Choose ranges and entry PCs from your project's source knowledge. The logical
entry must map entirely into captured allowed code RAM using the snapshot's
MPRs. Omit `--entry` to use the paused PC. Repeat `--ram-range`, `--code-range`
or `--entry` as needed; ranges must be sorted and disjoint. Repeat the capture
and discovery at another paused epoch, then pass both candidate directories to
`compose-overlays`. Capture does not pause, advance, resume or write the guest.

For a complete consumer, use [prepare-project](PREPARE_PROJECT.md) with the
original explicit boot/media recipe and:

```toml
[module]
kind = "overlay"
path = "overlays/library.json"
partition_layout = "shared"
partition_size = 1024
# Optional genuine history, independently admitted:
# history_path = "observed/history.json"
```

Preparation copies the complete library graph into `declarations/`, emits
translated operations, and pins every member in the descriptor. Boot mode,
profile, initial payload mapping where applicable, and all guest asset hashes
must match the snapshots' machine contract. Rebuilding with a new native module
does not require pretending the old snapshot came from that new binary. Each
epoch retains its actual caller-bound SDK/package provenance.

Use the [authored CD workflow](../examples/live-overlays/README.md) for a runnable
example without proprietary inputs. `emit-overlays --history` adds genuine
observed code through the existing union, with observed and declared accounting
kept separate. The [native catalogue](NATIVE_GAPS.md) uses format
`pce-native-catalog-4` and selection contract `declared-overlay-abi29-v1` for
these inputs. Formats 1–3 and existing declaration contracts remain supported.

## Source and integrity contract

`pce-paused-ram-snapshot-1` contains original before/after status responses,
two original memory responses per range and exact binary RAM bytes. Typed full
statuses must agree except for transport IDs; the complete response sequence
must have contiguous IDs. CPU-reported
fetch addresses must match PC/MPR, and captured fetch bytes must agree with RAM.
Every artifact has an exact size/hash binding. Extra files, links, changed
readbacks, gaps and inconsistent bindings refuse admission.

`pce-live-overlay-discovery-1` contains the options, source locations, states,
edges, overlaps and explicit unresolved frontiers. Every reader rederives the
graph from the bound snapshot. Updating hashes alone does not authenticate
invented analysis. `pce-overlay-library-1` retains each closed epoch and dedupes
only identical complete PC/MPR/physical/source-byte keys. Different code at the
same address remains distinct. All memberships and producer bindings survive
preparation, catalogue reconstruction and managed generation archives.

The first profile supports canonical base WRAM, standard CD RAM, and Super
System Card RAM in the matching machine profile. Fetches through base-WRAM
aliases retain their exact physical identity while bytes are resolved against
canonical WRAM. Unknown/Arcade/Populous RAM is not guessed. Capture bounds are
32 spans, 64 KiB each, at most 270,336 bytes. Libraries admit at most 32 epochs
and 64 MiB of complete bound graph data. Limit failures never silently discard
epochs or identities.

## Conservative analysis and remaining gaps

Direct branches explore both sides. Proven register facts can cross TAM mapping
changes. Discovery stops at indirect jumps, dynamic returns, BRK/RTI boundaries,
unknown mapping values and unsupported instructions. Calls may admit the direct
callee; they do not invent a return continuation. Device writes, unknown pointer
writes, block transfers and possible code writes produce explicit frontiers
after the real writing instruction. Stack writes and T-mode direct-page writes
are included in that protection. State/context limits report unresolved work.

These are **candidates**, not a guarantee of routine closure or future RAM
contents. Asynchronous interrupts, loader/sector attribution, broader indirect
flow and automatic interprocedural recovery remain separate work. A paused
snapshot is not a checkpoint. Libraries cannot establish cross-build checkpoint
compatibility; changed provenance changes the consumer checkpoint context.

The local package binding and repeated TCP responses do not cryptographically
authenticate a remote process or prove how bytes reached RAM. Operate an owned
loopback consumer and retain its original launch/process receipts and raw
journal. Native source/MPR guards still validate actual instruction fetches at
execution. A changed or unknown identity refuses in native mode; normal hybrid
fallback remains explicitly counted.

## Verification scope

The authored firmware issues actual CD READ commands and loads two original
sectors into the same CD-RAM address. Snapshots precede executing either loaded
sector in discovery. Three branch keys absent from that original route are
derived without invented hits. Two real native routes execute all **11 declared
keys**, with zero interpreted work. Literal full WRAM/CD RAM and final CPU,
same-build reference parity, own-checkpoint forks and a changed-code guard
negative pass. Paused data gates/branch controls are disclosed assistance.

Unmodified Geargrafx at the reviewed upstream fix loads the same authored CD
sectors. All **26 CPU/MPR/source-byte points** across four RAM execution windows,
all 11 identities and full WRAM/CD-RAM endpoints pass. Initial RAM and isolated
CPU register presets are explicit; this is not independent device clocks or
hardware proof. Two managed native builds reuse all **35 objects** after epoch
reordering and reject all **21** individual archive-artifact tampers before
preparation/compilation. Thirty-six existing pure/mixed source emission cases
remain byte-identical to the prior loader/emitter.

A fresh Rondo reference route captures two live RAM epochs (26 and 106 keys;
106 unique candidates). The combined native module and genuine history pass
404,669,933 native instructions with zero interpreted work/guards, 25,621 exact
retired identities and 17 paired CPU/full-WRAM/CD-RAM/RGB samples. Of the 106
declared candidates, 93 execute and 13 remain explicitly unexercised. Same-build
checkpoint forks add 59,672 new native steps / 753 keys, separately from imported
counts. This qualifies boot/file/introduction, not action gameplay or a whole
retail title. Ys III remains parked.

The required frozen-source check passes **2,401 Python tests without skips,
74 C++ suites and 12 fresh-process audio cases**. All 846 tracked candidate inputs
remain byte-identical through the seal. Later publication edits are Markdown
only; the 104-file SDK source fingerprint is unchanged.
