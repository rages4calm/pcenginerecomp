# Managed changed-module rebuilds

`python -m pcerecomp.incremental` provides an opt-in, private workspace for
rebuilding [stable observed-code modules](STABLE_EMISSION.md). Unlike the
[exact package cache](BUILD_CACHE.md), it can retain unaffected compiled objects
when observations change. The existing new-directory consumer build remains
available. This producer currently supports Windows x64 LLVM-MinGW and Ninja,
with the same explicit toolchain/SDK and effective-graph audits as the package
cache. It does not install or download dependencies.

Emit a candidate into a new directory and pin it in a normal schema-1 consumer
descriptor. Then create a separate workspace:

```sh
python -m pcerecomp emit-capture observed-code.json --out module-first --partition-layout stable
python -m pcerecomp.incremental create project-first.toml --workspace .local/development --toolchain-root /absolute/llvm-mingw --cmake-arg=-DCMAKE_CXX_COMPILER=/absolute/llvm-mingw/bin/clang++.exe --cmake-arg=-DCMAKE_MAKE_PROGRAM=/absolute/llvm-mingw/bin/ninja.exe
```

Select the declared bundle's `bin` on the calling process's PATH. For SDL add
`--desktop`, `--dependency-root /absolute/sdl-sdk` and
`--cmake-arg=-DSDL3_DIR=/absolute/sdl-sdk/lib/cmake/SDL3`. Dependencies and
toolchain files are content-bound, not discovered through an SDK PATH workaround.
Opaque CMake toolchain files and ambient compiler/search flags are refused.

After a new capture, emit another stable module into another new directory and
update its hashes/paths in a candidate descriptor. Only that descriptor's module
may change:

```sh
python -m pcerecomp emit-capture observed-next.json --out module-next --partition-layout stable
python -m pcerecomp.incremental update project-next.toml --workspace .local/development
python -m pcerecomp.project run .local/development/project.toml --build-dir .local/development/output --receipt .local/development-run.json
```

The producer copies checked artifacts into `workspace/module`, writes its own
normalized `workspace/project.toml`, and builds in `workspace/output`. It never
rewrites the caller's descriptor, emitted directory or qualified package. Keep
execution receipts, TCP outputs, saves and captures outside the workspace.
The original source revision/ABI, full module pins and runtime recipe still
apply. Historical capture labels are not changed by choosing stable layout.

Candidates may also declare the optional
[`module.observation_profile` binding](OBSERVATION_PROFILES.md#bind-the-profile-to-a-consumer-build).
The producer verifies the exact raw profile and its metadata against the
manifest before altering the workspace. It copies the file to
`workspace/module/observation-profile.json`, normalizes the owned descriptor,
and archives exact profile bytes in each generation. Profiles remain private
code-bearing data. Unchanged bytes keep their modification time. A changed
profile is a mutable module input in the cache contract; it does not authorize
an additional compiler include root. The caller's original file remains intact.
Missing, altered or linked candidate profiles and filename collisions refuse;
live profile or active-generation archived-profile tampering blocks reuse/run.
Admission does not recursively re-audit every older history generation. Adding this
optional binding changes checkpoint context and requires new checkpoints.
Once a workspace binds a profile, an update cannot drop the binding; use a
new workspace for an explicitly unbound workflow. Adding a binding to an
unbound workspace is allowed and still requires new checkpoints.

## What permits reuse

Before an update, the producer verifies the complete retained build directory
and managed module by content and exact modification times. This includes
objects, libraries, executable/DLLs, CMake graph, Ninja logs and dependency
records. It also checks the managed descriptor and current immutable generation
identity. External changes, missing/new files, backdated objects and an
incomplete generation are refused before reuse.

Compiler/runtime/toolkit bytes and revision, complete declared toolchain/SDK
trees, build options, input files, runtime profiles and limits must remain the
same. Change these by creating a new workspace. Updates may add, change or
remove module observations. The producer preserves identical artifact bytes
and timestamps; changed artifacts receive a timestamp strictly newer than
every retained build output. Clock regression/resolution that prevents this
stops explicitly. Removed sources are only previously verified, owned flat
module artifacts; no directory tree is recursively removed.

Every generation actually reconfigures CMake, audits its File API/Ninja graph,
and invokes compilation/linking as needed. Compiler-header dependencies and
external input identities are checked again after the build. CMake/Ninja decide
which dependencies rebuild; a source-body change, declaration change, or newly
introduced bucket can require different work. Removed objects may remain in
the private build tree, but are no longer linked if absent from the new graph.

`output/build-receipt.json` binds the current verified descriptor/package and
contains `incremental` metadata: generation, changed/unchanged/removed artifacts,
actual retained/rebuilt/added object timestamp inventories, audit and elapsed
time. These inventories describe this build, not runtime performance. The
producer never treats a build as execution qualification.

## Ownership, history and failures

An exclusive producer lock prevents two compliant writers from using one
workspace. Generation metadata, descriptor/manifest snapshots and build receipts
are retained create-new in `history/NNNNNN`. The live descriptor and binaries
are development output; old receipts are historical records, not runnable copies
of old packages. Preserve any qualified release separately before development.

An in-progress marker is written before changing managed inputs. A failed or
interrupted generation leaves it in place. Further updates and the official
consumer runner refuse that workspace; create a new one. There is no automatic
rollback, cleanup, repair or claim of whole-filesystem power-loss durability.
An abandoned lock is also left for explicit review rather than broken by age.
Directly launching a binary bypasses the official receipt/marker checks.

The audit assumes trusted toolkit/CMake/compiler code and cooperating writers;
it is not a sandbox for hostile build scripts or concurrent external file
replacement. The first producer is same-workspace, not a relocatable object
cache or a runtime-loaded native-module system. Stable layout can produce more
small units than balanced layout, increasing a cold build's work. Use actual
build receipts to assess the tradeoff.

The authored native integration test deliberately leaves one `INX` identity
untranslated. Its actual 200-instruction run retires 101 native and 99 interpreted
instructions; a complete capture supplies the missing identity. The update
then retires 200 native instructions with zero fallback, with independently
expected X=106, PC=$4100 and 1,800 master ticks. Only the affected range's object
rebuilds; the other 26 retain their exact bytes and timestamps. A separate clean
build matches the full guest result and capture. Further test generations
change only capture/manifest provenance, then repeat the exact descriptor;
neither recompiles objects or changes the executable. Changed runtime inputs
and an in-progress marker are explicitly refused. These finite authored checks
do not establish a general build-speed ratio or binary reproducibility across
different output paths/link times.
