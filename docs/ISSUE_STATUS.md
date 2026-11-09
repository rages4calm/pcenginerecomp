# Repository issue status - 9 November 2026

This is a maintenance snapshot, not a console-compatibility score. Closed issues
retain their original acceptance scope. Historical verification is not relabelled
as a new emulator or hardware run.

| Issue | Status after this change | Evidence / remaining work |
|---|---|---|
| [#1 RMB/SMB](https://github.com/rages4calm/pcenginerecomp/issues/1) | Closed, implemented | Existing CPU bit-operation/native tests and [CPU contract](CPU_SEMANTICS.md) |
| [#2 push/pop/status](https://github.com/rages4calm/pcenginerecomp/issues/2) | Closed, implemented | Existing stack/status tests and [CPU contract](CPU_SEMANTICS.md) |
| [#3 synthetic disc gaps](https://github.com/rages4calm/pcenginerecomp/issues/3) | Closed, implemented | Six authored [media tests](../tests/test_media_gaps.py), independent three-track INDEX01/CHD coordinates, malformed/truncated metadata and bounded reads; [media contract](MEDIA.md#synthetic-chd-gap-and-decoder-bound-coverage) |
| [#4 reference bus-event tracing](https://github.com/rages4calm/pcenginerecomp/issues/4) | Implemented and independently qualified within the requested slice | [Software bus traces](BUS_TRACES.md): actual native/interpreter callbacks, strict chronological comparison, separately built original Gear/Beetle runs, source guards, both speeds and consumer TCP/checkpoint checks; broader MMIO/IRQ/hardware qualification remains on the roadmap |
| [#5 RetroRecomp import](https://github.com/rages4calm/pcenginerecomp/issues/5) | Closed, follow-up answered | Downstream reports broader HuCard/Linux comparisons and explains a Boxyboy backup-memory configuration difference. Reports retain their downstream scope; base HuCard defaults remain unchanged. |
| [#11 larger banked capture coverage](https://github.com/rages4calm/pcenginerecomp/issues/11) | Implementation and upstream checks completed; downstream route follow-up open | [Extended capture/history v2](EXTENDED_CAPTURE.md) preserves full identities, explicit legacy limits and complete provenance. Fresh authored/native and private SF2 checks are in [status](STATUS.md); original downstream play/long routes still require their own rerun. |

Earlier PRs [#6](https://github.com/rages4calm/pcenginerecomp/pull/6),
[#7](https://github.com/rages4calm/pcenginerecomp/pull/7),
[#9](https://github.com/rages4calm/pcenginerecomp/pull/9) and
[#10](https://github.com/rages4calm/pcenginerecomp/pull/10) are merged. Issue #11
introduced the new actionable request handled in this batch. Versioning remains
commit-pinned; no stable release-tag or cross-build checkpoint promise is introduced.

## Current software bus verification

Code `cf3d5dd28cab1447782a6a9b1a4c46db70d473b4` passes **1,849 Python tests without skips, 74 C++ suites and 12 fresh-process audio cases**.
All 705 frozen tracked inputs remain unchanged. Independent original-core
observations retain genuine timing/call differences. The canonical consumer's
bounded own-checkpoint test and the official authored project build/run API pass.
[Bus trace details](BUS_TRACES.md) retain producer versions and the exact scope.
No electrical bus, universal MMIO timing or campaign claim is introduced.

## Earlier media-fixture verification

At `b2bb60073010fbf36db6adb6f7c020e417625379`, a fresh SDL Release build and required
check pass **1,799 Python tests without skips, 73 C++ suites and 12 fresh-process
audio cases**. All 687 tracked inputs remain unchanged through verification.
The six new media cases, 25 frontend cases and ten subchannel-media cases also pass
as focused checks. The decoder boundary controls use an authored ctypes callback
and substitutes, not a real libchdr image decode. No new game or emulator run is
claimed. At that earlier media-only pin the bus document was a proposal; the current implementation and verification are above.

The Python media reader now rejects non-integer requests and decoder hunk indices
above the uint32 argument range before data access. Runtime/CPU/emitter semantics,
ABI 29 and existing consumer builds/checkpoints remain unchanged.
