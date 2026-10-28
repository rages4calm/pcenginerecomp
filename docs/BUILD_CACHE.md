# Verified consumer package reuse

The opt-in consumer build cache stores an exact compiled executable and its
adjacent runtime DLLs. Every request verifies the consumer descriptor and
freshly configures CMake. An exact hit then restores the checked package and
skips consumer compilation and linking. CMake compiler-discovery probes may
still run. Normal uncached builds retain their existing behavior.

This first producer supports **Windows x64, LLVM-MinGW and Ninja**, with an
explicit complete toolchain bundle and, for desktop builds, an explicit SDL3
SDK. Other compilers and platforms can build normally; they do not silently
fall back to an unverified cache producer.

## Use

Create a private cache directory before invoking the build. Supply absolute
toolchain/compiler/Ninja paths and choose a new build directory each time:

```sh
python -m pcerecomp.project build your-project.toml --build-dir .local/build-cold --generator Ninja --cache-root .local/package-cache --cache-toolchain-root /absolute/llvm-mingw --cmake-arg=-DCMAKE_CXX_COMPILER=/absolute/llvm-mingw/bin/clang++.exe --cmake-arg=-DCMAKE_MAKE_PROGRAM=/absolute/llvm-mingw/bin/ninja.exe
```

Select that bundle's `bin` directory on the calling process's `PATH` so the
selected `cmake` also comes from the declared bundle. A second request with
the same compiled inputs and another new build directory can reuse the entry.
For desktop builds add `--desktop`,
`--cmake-arg=-DSDL3_DIR=/absolute/sdl-sdk/lib/cmake/SDL3` and
`--cache-dependency-root /absolute/sdl-sdk`. Repeat the dependency-root option
for additional complete SDK trees. These commands never download dependencies.

## Identity and receipts

The key includes compiler/runtime source identity and ABI, generated module
identities, complete content and directory inventories of the module,
toolchain, runtime/CMake and declared SDK trees, compiler/options/target,
host and controlled environment policy. Modification times are not content
identity. Fresh configuration adds the actual CMake File API model and
normalized Ninja build graph, including flags, definitions, compiled sources,
include/link inputs and configuration inputs. The selected SDL runtime source
is checked as well. Different build-directory paths are normalized; input
paths remain part of the identity.

The producer stores the full audited input contract in the build receipt and
binds its complete canonical UTF-8 encoding with SHA-256 plus byte length in
the package manifest's compact `contract`. Receipt `cache.key_contract` records
that envelope; `cache.input_contract` retains every original field. The full
contract has a 64 MiB bound. This supports larger partitioned source graphs
without increasing the generic cache's 256 KiB contract or 1 MiB manifest
limits. No source, header, option or dependency field is excluded from the
digest. The changed producer representation gives old entries a safe miss;
it does not relabel existing cache manifests or retained receipts.

The producer audits the known toolkit/SDL build graph and refuses unsupported
generated compile inputs, undeclared external dependencies and opaque
toolchain files. Cold builds additionally check actual Ninja compiler-header
dependencies before publication. It rejects ambient compiler flags/search
paths, runs children with a controlled Windows/toolchain environment and
rechecks input identities before writing a success receipt. This is a trusted
declared-input build profile, not a sandbox for arbitrary or hostile CMake,
compiler plugins or custom build scripts.

`build-receipt.json` always binds the current descriptor and current assets.
Its `cache` record includes the key, hit/miss, producer, input contract,
manifest identity, audit and elapsed time. Cold receipts record configure and
build commands; warm receipts record the actual configure command. Neither
receipt claims execution. Runtime media and runtime limits remain fresh
receipt bindings rather than compiled-package key inputs.

CMake can generate a different graph for a different output location even
when source bytes match. Windows object-path shortening and the ordering of
generated prerequisite lists can change the exact key. Such differences
produce a safe miss; they are not normalized away or treated as a hit. Use a
consistent output layout when evaluating reuse, and inspect the actual key
and receipt before claiming compilation was skipped.

Only bounded flat binary packages are accepted. Media, saves, translated
source, captures, and execution receipts are refused. A per-key process lock,
immutable manifests, staged create-new publication/restoration, file hashes
and link checks protect against concurrent writers and partial/corrupt entries.
Corruption or an interrupted entry stops explicitly; it is not silently
repaired. Atomic publication does not certify power-loss durability of an
entire filesystem.

## Boundaries

One frozen Windows x64 qualification rebuilt a 43,574-site observed-code
consumer in **154.17 seconds** on a cold miss and restored the byte-identical
package after fresh configuration in **15.25 seconds** on a warm hit. These
include input hashing/auditing and ran alongside other checks; they are one
paired observation, not a general compiler-speed benchmark. A separate wholly
authored program executes 200 native instructions from both packages, with
queued VRAM work and matching results. Retail TCP execution is reported
separately in [STATUS.md](STATUS.md).

This cache reuses the **same package**. A changed module, toolkit, SDK, compiler
or effective configuration produces a different key. It does not reuse
individual changed translation units, load native modules at runtime, compile
guest code during play, or improve native coverage. Existing partitioned
module builds remain useful when code changes. Cross-platform producers,
relocatable cache entries, cache eviction and broader toolchain support remain
roadmap work. Keep caches private: binary packages may contain translated
game logic even though the cache refuses raw media and source files.
