# Disc origins through authored CD loads

This example reuses the original firmware and sector generator from
[live overlays](../live-overlays/README.md). The guest sends READ commands,
loads sector 1 and then sector 2 into the same 2,048 RAM bytes, and waits at
explicit data gates before executing each overlay.

Run the check with an existing headless toolkit build and a new output path.

```sh
python examples/disc-origins/workflow.py --runner build/pce-headless --out .local/disc-origin-proof
```

On Windows use `build/pce-headless.exe`. The example uses the interpreter
reference policy and a dummy display. It records the exact executable, source
and fixture hashes, process output, original TCP journals and checkpoints.
The untracked discovery session also retains an original retired-code capture.
Supply a generated executable that covers that route and add `--native` to
require native retirement with zero interpreted instructions throughout the
same protocol. The two builds each use their own exact-build checkpoints.

The tracked and untracked routes must agree on CPU, full work RAM, full CD RAM,
frames and clocks. Every loaded byte must report its literal disc position.
The second load must replace the first origin even for equal bytes. A paused
write of the same byte must invalidate its origin. After restoring the
first-load checkpoint, preexisting RAM starts with unknown origins in the
new observer epoch. The following real sector read learns sector-two origins.
The restored continuation must produce the same final checkpoint bytes as
the untracked route.

Origin reports are diagnostic evidence of transfers observed in their current
host epoch. Loaded source still needs the toolkit's full mapping and byte guards
before native dispatch. The fixture's data-gate edits are developer assistance
and are retained in the wire journals.
