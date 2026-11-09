# Repository issue status - 8 November 2026

This is a maintenance snapshot, not a console-compatibility score. Closed issues
retain their original acceptance scope. Historical verification is not relabelled
as a new emulator or hardware run.

| Issue | Status after this change | Evidence / remaining work |
|---|---|---|
| [#1 RMB/SMB](https://github.com/rages4calm/pcenginerecomp/issues/1) | Closed, implemented | Existing CPU bit-operation/native tests and [CPU contract](CPU_SEMANTICS.md) |
| [#2 push/pop/status](https://github.com/rages4calm/pcenginerecomp/issues/2) | Closed, implemented | Existing stack/status tests and [CPU contract](CPU_SEMANTICS.md) |
| [#3 synthetic disc gaps](https://github.com/rages4calm/pcenginerecomp/issues/3) | Completed in this change | Six new authored [media tests](../tests/test_media_gaps.py), independent three-track INDEX01/CHD coordinates, malformed/truncated metadata and bounded reads; [media contract](MEDIA.md#synthetic-chd-gap-and-decoder-bound-coverage) |
| [#4 reference bus-event tracing](https://github.com/rages4calm/pcenginerecomp/issues/4) | Open, partially implemented | Original Beetle adapter and CPU/vector/phase diagnostics exist; [bus-event draft](BUS_TRACE_PROPOSAL.md) defines the remaining implementation and qualification gates |
| [#5 RetroRecomp import](https://github.com/rages4calm/pcenginerecomp/issues/5) | Closed, downstream confirmed | Contributor reports an experimental HuCard integration; this is not an independent qualification of those games |

PRs [#6](https://github.com/rages4calm/pcenginerecomp/pull/6) and
[#7](https://github.com/rages4calm/pcenginerecomp/pull/7) are merged. No pending PR or
unanswered new contributor request was found during this audit. Versioning remains
commit-pinned; no stable release-tag or cross-build checkpoint promise is introduced.

## Current verification

At `b2bb60073010fbf36db6adb6f7c020e417625379`, a fresh SDL Release build and required
check pass **1,799 Python tests without skips, 73 C++ suites and 12 fresh-process
audio cases**. All 687 tracked inputs remain unchanged through verification.
The six new media cases, 25 frontend cases and ten subchannel-media cases also pass
as focused checks. The decoder boundary controls use an authored ctypes callback
and substitutes, not a real libchdr image decode. No new game or emulator run is
claimed. The bus-event document is a proposal, with no runtime hooks/API shipped.

The Python media reader now rejects non-integer requests and decoder hunk indices
above the uint32 argument range before data access. Runtime/CPU/emitter semantics,
ABI 29 and existing consumer builds/checkpoints remain unchanged.
