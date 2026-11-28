# Resident sources and proven RTS transfers

This authored example boots original fixture firmware, copies a shared resident
routine with TII, and loads two alternative CD sectors through guest CD READ.
The sector changes MPR3 and calls the resident routine. That routine consumes
and restores its actual caller word, pushes a second known word, transfers with
RTS, then returns from the target to the original caller.

```sh
python examples/resident-far-calls/workflow.py create .local/resident-example
python examples/resident-far-calls/workflow.py qualify .local/resident-example --generator Ninja
```

Pass explicit compiler, Ninja and SDL locations with repeated `--cmake-arg=...`
when needed. The controller selects SDL dummy video/audio and software rendering;
it does not open a visible window or test the physical GPU.

Qualification captures authentic paused RAM after the real CD loads. It selects
resident bytes from the first snapshot, composes them with each disjoint CD load
group, and requires exactly the same candidate identities as whole-snapshot
analysis. The reconstructed-return edges must be present. Both source types are
prepared and compiled with genuine observed firmware history. Each runs two
branch choices through native and same-build interpreter execution, comparing
literal full WRAM/CD RAM, final CPU and complete paused status projections.
Independent fresh processes also check own-build checkpoint suffixes.

The original firmware/disc/recipe, SDK and example sources are bound before use.
Branch choice and release gates use disclosed checked paused writes. This is an
authored internal proof of the supported source/stack flow, not retail-game,
arbitrary-thunk, hardware or cross-build checkpoint qualification.
See [the source and safety contracts](../../docs/RESIDENT_FAR_CALLS.md).
