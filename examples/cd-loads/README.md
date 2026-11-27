# Authored offline CD load workflow

This example supplies explicit numeric CD load groups before running the
authored original-program CD READ loader from the live-overlay fixture. It
keeps two alternative sector loads at the same RAM address separate, declares
all 11 guarded instruction identities, and preserves genuine discovery history.

```sh
python examples/cd-loads/workflow.py create .local/cd-load-proof
python examples/cd-loads/workflow.py qualify .local/cd-load-proof --generator Ninja
```

Supply `--cmake-arg=-DCMAKE_CXX_COMPILER=PATH` and other supported build arguments
when selecting an explicit toolchain. Optional `--chdman PATH --libchdr PATH`
creates a real CD CHD from the same authored CUE/ISO and qualifies actual cooked
CHD reads, consumer preparation/build and native/reference guest loading. The
creator binary hash and exact command are retained. CUE checks always run.

Qualification uses SDL dummy/software/dummy audio, with no GPU or owner media.
The loader writes each whole 2048-byte sector into CD RAM through real guest
port instructions. Independent literal full WRAM/CD RAM expectations check its
results before executing each overlay. Authored paused data gates and a branch
selector are explicit test assistance; no CPU warp or fabricated live epoch is
used for offline admission. The real history supplies hit counts, while three
declared identities remain unexecuted until the second branch route.

The compiled ISO consumer runs both branches natively and through its
same-build interpreter reference. Complete paused CPU/device observations and
literal RAM match. Every declared identity must execute, with no unexpected
fallback. Fresh-process checkpoint forks compare the two policies. A changed
source-byte negative must fail its ordinary native guard. Separate CUE and
optional CHD consumers run the authored loader natively and in reference mode,
checking the same full RAM and paused state expectations. Reader, preparation,
compilation and execution evidence are reported separately.

Creation and qualification write new private directories and preserve failed
artifacts. `qualification.json` records actual native/interpreted work,
loader witnesses, original identities and the exact scope. Inputs are authored;
this is not retail-game, whole-routine or hardware-clock qualification.
