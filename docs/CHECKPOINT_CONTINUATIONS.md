# Additive native-module checkpoint continuation

This opt-in developer workflow continues an unchanged machine checkpoint after
adding guarded native identities to its module. It is separate from ordinary
[exact-build restore](DEVELOPER_CHECKPOINTS.md); default restore still rejects
different packages. It does not define portable saves, CPU/device migrations,
arbitrary native-code replacement or remote producer authentication.

Admission and launch preparation use one scoped verified-input epoch per
operation. Repeated project checks reuse parsed graphs while rechecking raw
content, closed membership and SDK identity; compiler, dependency, package,
checkpoint, journal and permit checks still run. This is not a persistent cache
or an exemption for historical SDKs. See [performance](PERFORMANCE.md).
Packages containing a [gameplay adapter](TITLE_ADAPTERS.md) are refused by v1,
including a compiled adapter selected in pristine mode.

## First adoption

Both packages must use **the identical current SDK revision, path and source**, identical machine,
input, media/provider and reference-capability recipes, and the audited Windows
LLVM-MinGW/Ninja build producer. Keep its compiler/SDK/dependency trees and build
metadata available at the same hashed paths. V1 deliberately rejects even different
Git revisions with identical source bytes; it does not infer a compatibility
contract from doc-only changes. Build through the verified package-cache producer on a
compiled cache miss, or the recoverable build producer. An ordinary build
receipt or cache hit without actual dependency evidence is refused.

**Known recovery-reader restriction ([#60](https://github.com/rages4calm/pcenginerecomp/issues/60)):**
the current continuation reader rejects the genuine recoverable producer's
sealed wrapper at the wrong nesting level. Recoverable compilation itself and
ordinary exact-build checkpoints are separate capabilities; do not start a
recoverable rebuild expecting additive continuation to admit it yet. The
audited compiled-cache-MISS path remains the qualified continuation producer.
Preserve failed receipts and never flatten or edit a recovery contract to force
admission. A tested reader fix and compatibility/baseline requirement are pending.

A fresh recoverable package can instead create a new cold baseline and use
ordinary exact-build save/restore checkpoints from that same package. The normal
`project.prepare_launch(checkpoint_dir=..., checkpoint_load=...)` path does not
invoke the additive audit. An authored fresh recovery build on the leadout-fix
SDK verifies that path with independent native/reference restores and exact PCM
suffixes. This requires new producer-owned checkpoints; it does not admit an
older package's state or guarantee another title's cold route.

A dedicated detached SDK checkout keeps later toolkit updates from changing a
consumer's existing lineage. From a source checkout, for example:

```sh
git worktree add --detach .local/port-sdk TOOLKIT_COMMIT
```

Point both consumer recipes at that directory and keep its revision and files
unchanged. Git-free exported source kits carry their original verified SDK pin
instead. Neither arrangement bypasses the compiler, dependency or input checks.
Run admission and launch helpers from that pinned SDK too: for example, change
into `.local/port-sdk` before invoking `python -m pcerecomp.project`, using paths
to the consumers from that location. Embedded controllers must select the same
SDK on their Python import path. Pointing descriptors at a frozen SDK does not
make a command imported from a newer toolkit checkout use that implementation.

Older SDK checkpoints remain with their original packages. Adopt this SDK by
performing one new cold qualification and creating a checkpoint under its
audited baseline. Subsequent supported native-only extensions can use that
checkpoint without replaying its imported prefix. This deliberately does not
reinterpret historical ABI29 states as automatically compatible.

## Admit the extension

Keep the source checkpoint unchanged in its existing private directory. Supply
both original verified consumers, their retained build directories, and each
module's exact original declarations/history/profile/capture input:

```sh
python -m pcerecomp.project checkpoint-continuation admit \
  --source-descriptor OLD/project.toml --source-build OLD_BUILD \
  --source-observations OLD_DECLARATIONS_OR_OBSERVATIONS \
  --destination-descriptor NEW/project.toml --destination-build NEW_BUILD \
  --destination-observations NEW_DECLARATIONS_OR_OBSERVATIONS \
  --checkpoint-dir PRIVATE_CHECKPOINTS --checkpoint-name frontier.pcec \
  --reference-enabled --out NEW_PRIVATE_ADMISSION_DIRECTORY
```

Use `--reference-enabled` only if the source checkpoint was created under that
capability. It remains exact on both sides. Admission never clears interpreter,
guard, block-transfer or other imported counters.

Admission verifies each original graph, all PC/MPR/physical/source-byte keys,
strict additive membership, unchanged emission/exclusion/guard policies and
exact current-SDK generated artifacts through deterministic re-emission. It
rechecks compiler trees, effective flags, CMake/Ninja configuration and actual
compiled dependencies. Identical ABI numbers or a catalogue subset alone do
not satisfy these gates.

Two owned, dummy-display, zero-retirement processes then check the source's
ordinary restore and the destination's independently computed exact host
identity. They exit without guest advancement. Inputs are re-admitted before
publishing `receipt.json` and the small `permit.pcecp`. The permit binds the
receipt, original checkpoint digest and source/destination host identities.
Retain the entire admission directory with the original proof. Probe wire files
retain the exact request/reply bytes before parsing; their hashes appear in the
receipt. Failed probes retain a failed admission receipt without a permit.

## Prepare a destination launch

```sh
python -m pcerecomp.project launch-plan NEW/project.toml \
  --build-dir NEW_BUILD --checkpoint-continuation ADMISSION/receipt.json \
  --code-capture NEW_PRIVATE_SUFFIX.jsonl --capture-profile extended \
  --capture-limit 262144
```

The returned plan is always paused and contains the startup-only permit and
its exact digest. The launcher rechecks the package, original checkpoint,
producer closure and permit before returning it. The caller owns process
lifetime and TCP qualification. The equivalent Python entry point is
`pcerecomp.checkpoint_continuation.prepare_continuation_launch(receipt_path)`;
`project.prepare_launch(..., checkpoint_continuation=receipt_path)` also checks
that the caller selected the same destination consumer.

Code capture is an optional output-only diagnostic. Both Python launch helpers
accept `code_capture`, `capture_limit` and `capture_profile`, and the standalone
`checkpoint-continuation launch-plan` command accepts their corresponding flags.
They use ordinary launch output validation: choose a new file in an existing
private directory; an existing file is refused, and capture limits require a
capture path. Capture preserves the receipt's reference capability, dispatch
span, checkpoint identity and original imported capture origin. The caller may
then select a reference window over TCP and retain its fresh source counts.
Capture does not itself qualify the suffix. Memory writes, disc-origin tracking,
bus tracing and caller overrides of the checkpoint/reference recipe remain
unsupported by the v1 continuation launch API.

The raw host requires `--checkpoint-load`, `--checkpoint-continuation` and
`--checkpoint-continuation-sha` together at paused startup. It checks the permit
against its own exact destination identity, then validates the untouched source
checkpoint using the named source identity. The expected file digest is checked
against the **same bounded bytes** that the decoder consumes. Existing complete
machine/media/provider/host validation runs before the nonthrowing guest commit.
There is no TCP command that permits a mismatched ordinary restore.

Raw host callers own their reviewed admission capability, just as they own
`--checkpoint-context`. SHA256 binds integrity; it is not a signature proving
authorship against an attacker controlling the local filesystem or launcher.
Use the supported admission/launch APIs for the verification gates above.

## Evidence and limits

The imported checkpoint, machine clocks, device state, pending PCM, host input
and WAV cursors and every lifetime counter remain exact. Fresh presentation and
audio handles use ordinary checkpoint restoration semantics. Source WAV history
is an imported marker; the destination WAV is a newly recorded suffix.

A checkpoint may precede the first completed video frame. Desktop restoration
waits for a genuine frame before presenting it; it does not fabricate an image
or advance the guest to fill one. Guest and presented screenshots correctly
refuse capture until a completed frame exists.

Status/final reports add `checkpoint.continuation` with receipt and permit
digests and both host identities. Existing `checkpoint.origin` and `window`
keep imported and newly retired work separate. New destination checkpoints use
the destination's normal exact identity. Retain the admission receipt alongside
captures whose origin points to the older package's unchanged checkpoint.

An admission receipt authorizes this narrow import; `qualified` and
`execution_evidence` remain false. Qualify a fresh destination native suffix,
an independent repeat, and a same-package interpreter-reference suffix. Compare
complete machine/host state, full RAM, guest RGB, digital PCM and exact inputs,
accounting explicitly for execution-tier counters. A meaningful paced desktop
audio case remains a separate host qualification.

Changes to engine, lowering, compiler, device or input/media policy require a
new baseline. Extensions cannot remove old identities or change source bytes
for an existing identity. Additional source-byte variants are distinct guarded
keys. Offline CD-load declarations and genuine observation history remain
separate evidence classes. This workflow reduces replay cost; it does not
establish whole-program discovery, original hardware equivalence or campaign
completion.

## Measured scope

The authored example reports package compilation, admission and total workflow
time separately. Each launch re-audits the original compiler/dependency trees
and generated sources; this can be substantial even for a small guest program.
V1 intentionally retains those checks. It makes no universal speedup claim and
does not cache verification epochs across launches. Compare measured admission
and suffix cost with the actual avoided prefix replay for the consumer.
