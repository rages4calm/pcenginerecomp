# Typed checkpoint inspection and comparison

This authored workflow compares guest state through the supported offline
inspection API. It does not parse checkpoint offsets or rewrite saved state.
It uses no game, firmware, disc, installed save or external owner input.

Two audited consumers run the same authored program: an original package and
a package with a consumer-owned gameplay adapter. The original, compiled
pristine and enhanced settings each receive their own genuine native, repeat,
interpreter-reference and exact-checkpoint-restored TCP runs. Guest RAM values
have independent toy-game expectations; completed nonzero RGB and pending PCM
are retained in the checkpoint.

Each source executable validates its own checkpoint and emits typed CPU/MPR,
HOST and complete CORE fingerprints without running or restoring the guest.
The comparison API re-inspects both source files before comparing them. Exact
native/reference comparison must report a difference; the explicit
`tier-counters` policy may ignore exactly four named execution-tier counters.
HOST, clocks, guards, IRQs, devices, memory, picture, sound and adapter state
remain strict. Original counter values remain in the reports. Repeated and
exact-restored checkpoints must match exactly.

```powershell
python examples/checkpoint-inspection/workflow.py --out .local/inspection/proof01 --toolchain-root PATH_TO_TOOLCHAIN
```

Run from a frozen committed SDK. Add explicit `--dependency-root` and
`--cmake-arg` options for the supplied SDL SDK, or `--headless` to omit the
desktop host. Desktop testing uses dummy video/audio and software rendering,
never the owner's monitor or physical audio device. Each output root is new.

Negative tests reject changed hashes, source graphs, modes/settings, different
source recipes and a self-consistent forged projected fingerprint. A direct
offline call with invalid SDL drivers must still succeed with zero guest work
and no device/server startup. Genuine source checkpoints and closed inspections
remain unchanged. Failed/refused artifacts and deliberately forged authored
negative inputs remain labelled under the private proof root.

An equal comparison establishes bounded state agreement under its named policy.
It does not authorize checkpoint migration, establish hardware accuracy, qualify
a native whole game, validate a player SAVE or permit cross-build loading.
