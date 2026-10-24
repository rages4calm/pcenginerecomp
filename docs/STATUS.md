# Current status — 23 October 2026

## Verified baseline

This is an executable compiler/runtime foundation with continuous software
video, an optional desktop window and locally demonstrated first-mine combat,
level progression and volatile guest SAVE/LOAD. Separate, explicitly assisted
tests reach the Pendant, Storehouse Key and first-storehouse-boss encounter,
with observed damage to the enemy bar. The complete final route reproduces
across headless and SDL hosts within the documented comparison scope.
**No complete game port is certified.**
The public source needs no retail input to build or test. SDL is optional.

## BIN/CUE media and pinned consumers

The new shared media implementation is
[`95fe3e07e63b0869de8c9d7b70681b5c557abf01`](https://github.com/rages4calm/pcenginerecomp/commit/95fe3e07e63b0869de8c9d7b70681b5c557abf01),
canonical source digest
`60c37d9fb5b1a1318cd2509c7ac1cc45c03a9939116d04e836aa67e0e03c4ffb`
over **57 files**. Runtime ABI **17** and consumer/capture schema **1** remain
unchanged: this adds host media readers and input bindings, without changing
CPU/Bus layout or translated instruction semantics. Consumer packages still
need fresh source pins, builds and execution receipts.

The bounded read-only BIN/CUE subset supports single/multiple binary files,
cooked/raw MODE1, AUDIO, stored and virtual pregaps, and little-endian signed
audio samples. Complete-image identity covers exact CUE bytes and every
referenced binary. Python inspect, TOC export and bounded IPL discovery use
the same layout contract. Consumers bind all components, preserve the declared
CUE root through permitted links, and reject changed inputs. CLI outputs
cannot replace the CUE, a referenced file or an existing hardlink alias.
Unsupported formats/layouts stop explicitly; see [MEDIA.md](MEDIA.md).

The fresh SDL/reference build passes **35 suites / 420 Python tests, zero
skips**. The CUE provider adds **13,059 authored expectations**; 32 additional
finite vectors check parser acceptance consistency across C++ and Python.
The separately compiled unchanged Geargrafx 1.8.4 media reader matches six
authored images: **114 observations / 59,392 data bytes / 28,224 signed audio
samples**. All six compound identities match independent record encoding.

A separate actual translated-MMIO probe executes seven READ streams per tier,
14 sectors per tier: **114,877 native / zero interpreted instructions**, and
the same count in the interpreter-only runs. Payloads, ACKs, status/message,
zero guard misses and zero read errors agree. Gear independently checks the
media geometry/bytes; this command-stream check is toolkit functional evidence,
not external whole-guest bus timing.

Two fresh official authored CUE consumer verify/build/run sequences, headless
and SDL, each execute **600,000 native / zero interpreted instructions**.
Separate native-only TCP runs each advance **26 frames / 803,697 native
instructions**, with zero fallback/guard misses, one READ and all 2,048 guest
RAM bytes matching independently authored data. Normal input/release,
captures and natural TCP quit pass; memory editing remains disabled and its
counters stay zero. Four interpreter-host runs separately cover cooked/raw
sectors in both hosts. Every authored input remains unchanged. PCM is off in
these short data-path proofs; their captures add no audio-output claim.

The separate Ys III project also freshly rebuilds the same qualified native
module against this toolkit source and passes a **5,526-frame CHD reset
prefix** through ordinary TCP controls. All **20 checkpoints and two guest
images** match its retained ABI-17 reference, including CPU/MPR/source/device
state and digital PCM. Actual work is **152,630,394 native / zero interpreted
instructions**, 177 sectors read and 4,073,415 stereo PCM frames, including
3,307,345 nonzero mixed frames, with zero RAM edits or runtime audio discard
and natural TCP quit 0. The bounded
10-second WAV prefix is boot-silent and byte-identical; later cumulative PCM
is nonzero. The fresh official SDL package retains the same 258 generated
artifacts and verifies its packaged SDL outside the SDK PATH. The explicit
`gear-good` profile is still used twice. This is a compatibility regression,
separate from that project's ongoing town-coverage work; it adds no campaign
milestone and does not replace its previously qualified launcher selection.

Existing CHD/ISO input identities and semantics remain unchanged. The earlier
native System Card and assisted gameplay sections below retain their original
source pins and execution scope. The new media reader does not implement the
unknown `$FF` CD command, add persistence, or certify a complete game.

## Native reset promotion and ABI-17 integration

The shared toolkit now checks native reset execution independently and provides
a reusable actual-capture-to-native consumer example. Production implementation
[`bb3b695b782352bdfacd8db877f2a843bd1242f1`](https://github.com/rages4calm/pcenginerecomp/commit/bb3b695b782352bdfacd8db877f2a843bd1242f1)
has canonical source digest
`5d3551481d1245d8cec9011d0f390ad0b464720c2d1f37a0fce601d0888e7a0d`
over 54 files. ABI **17** and both schema-1 formats remain unchanged.
The only canonical source change from the original reset batch is consumer
receipt validation in `project.py`; all runtime and emitter bytes are identical.
The authored helper and native reference adapter are finalized in
[`24244348370187c343c4ae223c7282a08252106e`](https://github.com/rages4calm/pcenginerecomp/commit/24244348370187c343c4ae223c7282a08252106e),
with that same canonical source digest. Native modules and input pins still
require fresh generation/build/run qualification for the selected consumer.

The fresh SDL/reference build passes **34 suites / 386 Python tests with zero
skips**. Reset receipts verify the initial typed metadata against the selected
hardware, pinned BIOS vector, deterministic policy and BRAM source. Fresh
captures must have the current ABI, requested capacity and consistent native /
interpreted retirement counts. Explicit loss remains visible and unclassified;
older offline capture inputs retain their original ABI labels.

The actual authored training run records 16 identities across five complete
MPR contexts, including ROM fetches in banks `$00`, `$20` and `$40`. Four fresh
official Standard/Super × headless/SDL-desktop verify/build/run sequences each
retire **200 native / zero interpreted instructions**, with matching guest
CPU/device state and actual native captures. Each separate paused TCP test
executes **79,448 native / zero interpreted instructions** over two frames,
verifies mirrored reads and the authored RAM result, and quits cleanly with
zero RAM edits. Each changed-CSH negative stops at a native guard miss after
six retired instructions, before the changed instruction executes. PCM is
explicitly off for these short CPU/mapping proofs; they add no audio claim.

The unchanged external Geargrafx oracle repeats all **38 original cases /
29,824 observations**, plus **12 separately authored mirror-fetch cases / 120
observations**. Actual captured source identities are emitted, compiled and
executed: **303 identities / 20 MPR contexts, 1,320 native / zero interpreted
instructions**. Native/interpreted raw records match exactly. Original Gear
comparisons retain the known **36 CSH differences of 18 master ticks**; the
additional mirror-case clocks agree. Separate guard tests check 200 refusals
with 100 intentional authored source mutations explicitly recorded/restored.
These are finite authored proofs, distinct from native retail qualification.

The Ys III consumer's separate ABI-17 reset recipe now executes the actual
**14,680-frame** firmware-to-town-opening route with **432,875,213 native /
zero interpreted instructions**, **41,179 native / zero interpreted block
transfers**, and zero guard misses. Its fresh official package uses the actual
capture union: **52,556 eligible identities / 79 MPR contexts**, including
7,674 newly observed identities. The original six-byte source exclusion remains
in force. The raw reset capture retains 36,145 identities, all 432,875,213
retirements and zero dropped/unreadable instructions; source ABI labels remain
unchanged. Emitted source is compiled as 257 translation units plus its header.

The native run follows the same normal controls as the interpreted baseline:
reset → System Card menu → Run → disc introduction → Beginning → blank-BRAM
Proceed → town opening. All ten guest images, guest CPU/MPR/source/device/CD
state and digital PCM/bounded WAV agree within the stated comparison scope.
Both full runs retain 105 states and 115 actions, natural TCP quit 0, unchanged
protected input assertions and **zero RAM edits**. This is a new native boot
proof, not a new campaign milestone or complete port certification.

The same regenerated module also passes the retained **95,686-frame /
68-checkpoint** IPL-start gameplay regression on ABI 17: **2,980,431,691 native /
981 interpreted instructions** and 470,652 native block transfers. Guest state
and the retained filtered 48 kHz PCM comparison agree within that route's
existing scope. It keeps the original 709 assisted transactions / 723 edited
bytes, with no new assists, and quits naturally with exit 0. This separate
assisted regression does not change the zero-RAM-edit reset proof above.

The only old-reference input-status projection is the explicitly witnessed
same-tick release observation at frame 11,660. The old status still held I;
the new host had applied release. All other guest fields remain strict, and the
actual next two-frame advance confirms release with an exact guest-state match.
The original failed attempt and both raw observations remain preserved. There
is no broad removal of button fields. See [input acknowledgement semantics](DEV_SERVER.md).

A separate first-600-frame native menu run records **17,483,734 native / zero
interpreted instructions**: 17,483,730 BIOS-range hits and four RAM hits. Its
frame-120 and frame-600 guest images match the retained toolkit images exactly,
tying this bounded native menu result to the earlier explicit Gear viewport
comparison. Full Gear/tool images still differ by the documented black-border
crop; this is not a new whole-retail CPU/timing comparison.

Guest audio remains on: 10,821,162 stereo frames, PCM hash
`16077886581937742416`, zero runtime discard and the same bounded 441,000-frame
WAV prefix. The run reads 516 sectors without read errors and still requires
the explicit `gear-good` response profile twice. This does not implement `$FF`,
add listening/hardware parity or introduce persistent host saves.

See [the capture example](../examples/reset-consumer/README.md#capture-mappings-that-a-fixed-cfg-cannot-discover),
[reset contract](SYSTEM_CARD_BOOT.md) and [reference limits](REFERENCE.md).

## System Card reset boot - ABI 17

This section preserves the original reset batch's execution and reference
scope. Later native integration is recorded above.

The toolkit now has an explicit Standard/Super System Card reset-vector
startup path in both hosts and the consumer interface. It maps the selected
ROM/RAM hardware, initializes the named deterministic reference state, then
executes the actual supplied firmware. No extracted IPL, game entry address,
firmware patch or invented BIOS service is used. Existing snapshot/IPL recipes
remain available. BRAM is blank/unformatted or an explicit read-only seed;
there is no automatic formatting, owner-save discovery or persistence.

The immutable implementation is
[`df110529bd79cded48d9607653c8b6218bce4b3b`](https://github.com/rages4calm/pcenginerecomp/commit/df110529bd79cded48d9607653c8b6218bce4b3b),
source digest `c3dd7c6de6bba4abdb92eb3f90c1c5dbecf387790a15db654b597eda0225f1d7`
over 54 canonical files. Runtime ABI is **17**; consumer and capture schemas
remain 1. Retained ABI-12/13/14/15/16 captures can be re-emitted and rebuilt
without relabeling their original observations.

That fresh SDL/reference build passes **34 suites / 360 Python tests without
skips**. The new reset fixture checks **6,105,054 authored expectations**;
22 actual host tests cover headless/desktop reset, mapping, preserved inputs,
invalid grammar, captures and paused-before-first-instruction TCP control.

Independent unchanged Geargrafx 1.8.4 execution passes **38 authored cases /
29,824 observations**, including complete 109-field initial device snapshots,
CPU traces, explicit seeds/vectors/regions, memory mirrors, expansion RAM,
absent memory, source peeks and identification pins. Selected architectural
state agrees. The **36 CSH transitions retain the established 18-master-tick
clock difference**; raw clocks and the disclosed transition adjustment are
recorded, rather than claiming unconditional cycle parity.

Separate real clean USA firmware/actual-disc execution reaches the System
Card menu through 600 frames in Gear and this runtime. All **60,672 overlapping
pixels** match at both frame 120 and 600. Full frames remain unequal because
the toolkit uses active-VDC rows and Gear's selected fixed VCE viewport keeps
three additional black rows. No raster timing or image bytes are altered to
force agreement.

Standard headless and Super SDL desktop authored official consumer
verify/build/run sequences each retire **200 native / zero interpreted
instructions**, with literal CPU/clock results and actual three-identity
captures. This proves native reset-entry integration without any retail data;
it does not turn an interpreter-only retail boot into native execution.

A separate BIOS-backed TCP run starts at reset and completes **14,680 frames**:
System Card menu → Run → disc-loaded introduction → Beginning → unformatted
BRAM warning → Proceed → opening story and town opening. It retires **432,875,213
interpreted / zero native instructions**, reads 516 sectors with zero read
errors, and ends by clean TCP quit. Normal controller input is scripted; there
are **zero RAM edits**, no preloaded IPL and no owner save. This qualifies
firmware/disc startup and the observed opening, not a new campaign milestone
or fully native retail port.

Audio stays enabled throughout: **10,821,162 stereo frames** synthesized with
nonzero PSG, ADPCM and CDDA contributions, zero runtime discard, and a bounded
10-second WAV. The WAV alone covers only its recorded prefix; cumulative
diagnostics cover later synthesis. This headless check is not new listening,
device-playback or independent retail mixed-audio parity evidence.

The run still needs the explicit `gear-good` policy when leaving the
introduction, used twice. A separate strict prefix reaches the same first
`$FF` and stops explicitly with one attempt, zero accepted responses and
natural process exit 3. Reset-vector startup does not implement that command.
Earlier private controller-harness failures are preserved separately; the
completed route and strict prefix use the corrected helper and clean exits.

At that stage, the Ys III consumer's independent coverage work stayed on its
qualified ABI-16 pin while reset startup was tested separately. Earlier ABI-16
and older sections below retain their historical qualification scope.
See [the startup contract and limits](SYSTEM_CARD_BOOT.md),
[consumer migration](CONSUMER.md#upgrade-a-consumer-to-abi-17), and
[authored example](../examples/reset-consumer/README.md).

## Base compatibility - ABI 16

The retained ABI-16 shared runtime adds normal PC Engine F8-FB work-RAM aliases,
direct native/interpreted BRK, and device-clock VDC sprite collision/overflow
events. There are 234 supported opcode encodings; 22 reserved slots still
trap explicitly. Runtime ABI is **16**, with unchanged schema-1 consumer and
capture formats. Re-emit retained ABI-12/13/14/15 captures and rebuild modules
with the runtime. No new capture or native gain is implied by an ABI upgrade.

The immutable implementation is
[`3bd06b5055c92e9f368aab7023098ff8aa796854`](https://github.com/rages4calm/pcenginerecomp/commit/3bd06b5055c92e9f368aab7023098ff8aa796854),
canonical source digest
`720e3c1e980e3ad9d03b28cb4b31db696fe3bb27e687c0cf19bc3d0f3f1c9440`
over 54 source files. A fresh build from that exact checkout passes the checks
below. An earlier working-tree CRLF header epoch is preserved separately;
canonical public LF bytes were rebuilt and checked without changing semantics.

The fresh SDL/reference-probe build passes **33 suites and all 328 Python
tests without skips**. New authored expectations include **426,004 WRAM
checks, 2,374,129 BRK checks and 211 sprite checks**. Actual TCP checks cover
alias reads and atomic compare/write behavior; authored unknown-CD traffic
tests strict fault and explicit reference-response modes with retained source
context. Existing audio, rendering, device, compiler and packaging suites pass.

Three fresh authored official consumer verify/build/run sequences each retire
**200 native / zero interpreted instructions**. The BRK fixture captures
its actual two-byte encoding, then capture-to-native regeneration and another
fresh official run reproduce the capture and final diagnostics exactly.
Authored ABI-12/13/14/15 format fixtures re-emit successfully for ABI 16;
they are format checks, not executions by those historical runtimes.

Separately compiled unchanged Geargrafx 1.8.4 matches **81 sprite cases /
125,922 checkpoints** in each toolkit video-on/off mode, plus **3,040 BRK
cases / 5,280 checkpoints** in each execution tier. The external memory check
passes 131,072 WRAM alias readbacks and four actual instruction-fetch aliases.
These are finite authored device/CPU proofs, not retail/hardware conformance.
Earlier external-wrapper startup failures and obsolete-fixture failures are
preserved separately; no runtime correction was needed for those harness errors.

Unknown CD commands still fault by default; REQUEST SENSE remains unsupported.
New bounded `cd_unknown` diagnostics retain opcode attempts and last-unknown
CDB/origin without replacing it with later known commands. The origin is
the last latch-write PC/MPR/fetch supplying the initial CDB byte before ACK,
not an ACK-time retirement trace. Physical
VRAM contention, undriven rendering-bus reads, authentic reset, HuCard mappers,
SuperGrafx/Arcade Card and persistent host saves remain separate gaps.
See [the compatibility contract](COMPATIBILITY.md),
[reference scope](REFERENCE.md#base-compatibility-references---abi-16), and
[consumer upgrade procedure](CONSUMER.md#upgrade-a-consumer-to-abi-16).

## ABI-16 consumer integration

The separate Ys III consumer re-emits its original ABI-13 observations for
the exact ABI-16 implementation above. All **208 translation units and one
header** retain their translated operations, source guards and exclusions,
with only ABI assertions changed. The capture still contains **44,879 eligible
identities across 57 MPR contexts**; no new observation or native gain is
claimed.

Fresh official desktop builds complete the same assisted **94,800-frame
route** with legacy filtered 48 kHz, default Gear filtered 48 kHz, and audio
off. All **39 images/checkpoint states and three endpoints** preserve the
retained guest/source/IRQ/generation fields. Each run retires **2,953,438,406
native / 981 interpreted instructions**, including **466,118 native / zero
interpreted block transfers** and 981 guard misses. The 709 inherited RAM
compare-and-swap transactions submit 49,303 bytes and change 723 bytes; there
are no new assists or campaign milestones. Original media, captures and old
qualified receipts remain unchanged and private.

Fresh legacy and Gear headless runs match their corresponding desktop routes,
including all new `cd_unknown` diagnostics, PCM and bounded WAV bytes.
The headless run's explicit Gear flag
and the desktop's omitted/default flag both select the same three-key audio
profile. Legacy and Gear PCM hashes remain `13785118638779356764` and
`1852331864136332503`, respectively; the audio-off route produces no PCM/WAV.
The first 30-second WAV alone cannot qualify the full audio stream; checkpoint
and cumulative hashes retain that separate scope.

The new diagnostics identify all **53 reference-profile responses as opcode
`$FF`**, rather than assuming they are REQUEST SENSE. A separate strict-policy
probe stops at the first `$FF` with one attempt, zero accepted responses and
the explicit unsupported-command fault. It qualifies fault diagnostics, not
a successful route or normal process shutdown. The assisted route still
requires `gear-good`; no unknown CD operation is implemented by this result.

A separate official `project run` smoke passes **60 frames / 2,014,178 native /
zero interpreted instructions**. Full routes use the separately bounded
1,800-second TCP supervisor, not the official command's 600-second bound.
The paced packaged SDL check loads its adjacent runtime from an empty working
directory with sanitized PATH, exercises input/capture/pause/resume, accepts
and drains **773,361 output frames**, and ends with zero runtime discard and
an empty device queue. Pause-flush device drops are recorded separately;
this is device acceptance, not listening or analog-audio parity.

The fresh consumer-embedded runtime passes **33 suites / 328 Python tests
without skips**. The consumer's own final suite passes **324 tests without
skips**, including strict ABI-16 capture and additive diagnostic validation.
These runs qualify the reusable consumer interface and the retained route;
they add no independent retail-game oracle, full-campaign, authentic-reset or
hardware-conformance claim. Earlier ABI-15 evidence below remains historical.

## ABI-15 consumer integration

The reusable consumer contract is exercised against the same qualified
ABI-15 implementation described below. A fresh authored example passes official
prepare, verify, build and run: **200 native / zero interpreted instructions**,
expected CPU state, and an actual four-identity / 200-retirement capture.
Authored ABI-12/13/14 format fixtures re-emit successfully for ABI 15;
these fixtures do not claim execution by older runtimes. All 57 focused
capture/project tests pass.

The Ys III consumer's retained ABI-13 observation union re-emits **44,879
eligible identities / 57 complete MPR contexts**. All **208 translation units
and one header** preserve their translated operations and guards after
normalizing only ABI assertions. The existing source exclusion and its
981 interpreted retirements remain intact. This is an ABI migration, with
no additional native gain or new campaign coverage.

Fresh official headless and desktop builds execute the same assisted
**94,800-frame route**, including its retained combat, Game Over and Continue
section. Both audio timings match all **39 image/checkpoint states and three
endpoints** across hosts. Native work remains **2,953,438,406 native + 981
interpreted**, with **466,118 native / zero interpreted block transfers**.
The audio-off desktop replay also completes the same route. No new assistance
is introduced: 709 compare-and-swap transactions submit 49,303 bytes and change
723 bytes. Original media and captures remain private and unchanged; prior
qualified source epochs are preserved in exact private archives.

| Audio mode | Result |
|---|---|
| Explicit legacy, filtered 48 kHz | All checkpoint/final PCM and bounded WAV bytes match the retained ABI-13 consumer and fresh ABI-15 headless reference; cumulative PCM hash `13785118638779356764` |
| Default Gear, filtered 48 kHz | Desktop PCM/WAV matches the fresh headless reference; cumulative PCM hash `1852331864136332503` |
| Both enabled modes | 76,060,360 output frames / 69,880,456 source frames, peak 13,355 and zero runtime discard |

Gear source counts match `floor(ticks*44100/21477273)` and filtered output
counts match `floor(source_frames*160/147)` at all 39 checkpoints and three
endpoints. The first 30-second WAV remains byte-identical across timings;
whole-stream/checkpoint hashes provide the later audio evidence.

A separate official consumer `project run` TCP smoke passes **60 frames /
2,014,178 native / zero interpreted instructions**. The full routes use a
separate 1,800-second consumer supervisor with official verify/build bindings,
not the command's 600-second limit. A paced packaged Gear/48 kHz check passes
adjacent-SDL loading from an empty working directory with sanitized PATH,
TCP input/captures, pause freeze and resumed advancement. It produces 773,361
output frames with zero runtime discard. Device acceptance is separate from
listening or hardware accuracy.

The fresh embedded shared-runtime check passes **30 suites / 316 Python tests
without skips**. Consumer migration checks pass **283 tests without skips**.
Independent root evidence review rehashes 655 actual artifacts and passes
27,328 checks. These are runtime/consumer regression results; retained finite
Geargrafx source oracles keep their original scope. No independent retail
mixed-audio oracle, complete-game port or hardware certification is added.
See [the migration procedure](CONSUMER.md#upgrade-a-consumer-to-abi-15).

## CDDA sample-latch ports

The guest now reads signed post-fader CDDA samples through `$1805/$1806`,
independently of PCM output, filtering, output rate and legacy presentation
sample timing. Accepted `$1805` writes are at least 700 master ticks apart,
alternate right first and retain one coherent 16-bit sample. Reads do not
advance or toggle it; `$1806` writes are ignored. `$1803` reports the selected
side and relocks BRAM. See [the exact contract](CD_AUDIO.md#guest-sample-latch).

The implementation is frozen at
[`e0f67bf64fe670723acd4443b0da76f3bfe8276f`](https://github.com/rages4calm/pcenginerecomp/commit/e0f67bf64fe670723acd4443b0da76f3bfe8276f),
source digest `38573f59cd17b1b9c640337ac6c1d9db80b3dc926d42312f8cedfd28d7959dd7`
over 53 canonical files. Runtime **ABI 15** owns the guest CDDA cursor, phase,
raw/post-fader holds and latch state. Descriptor schema remains **1**.
ABI-12/13/14 captures remain accepted; re-emit and rebuild modules and runtime
when upgrading. There is no snapshot compatibility contract.

The SDL/native-module configuration passes **30 suites and 316 Python tests
without skips**. New authored checks cover **3,047 latch/source expectations**
and **48 native/interpreter latch instruction sequences**, including signed
loads and flags, both CPU speeds and MPR aliases. The full SCSI, CDDA, DSP,
timing, video, compiler and host suites pass. A clean immutable public-source
build without SDL or a generated game module passes **28 suites**, discovering
the same 316 Python tests with eight intentional desktop-only skips.
A maximum-timestamp regression
found during this batch is fixed: an exhausted CD source timeline has no
future representable deadline, while actual command/output scheduling overflow
still faults explicitly.

A separately compiled unchanged Geargrafx 1.8.4 core passes nine authored
cases / **367 distinct reference checkpoints**, each compared with toolkit PCM
on and off. The real master scheduler advances source and fader clocks using
an authored CUE/BIN. The disclosed private-clock member-pointer bridge changes
no reference source or sample state. The final oracle and its exact executed
probe/source bindings are preserved separately from earlier development runs.
This qualifies the selected reference profile; CPU bus phases, variable seek
distance, retail mixed-audio parity and hardware output remain unqualified.
Full reset is covered by authored runtime checks; the reference cases start
fresh cores rather than resetting a previously nonzero latch in place.

## Ys III latch regression through TCP

Two fresh ABI-15 headless TCP executions finish the original assisted
**93,735-frame route**. Legacy raw 44.1 kHz and Gear filtered 48 kHz each
match their preceding ABI-14 execution exactly: all **25 complete guest image
hashes, 25 checkpoint states, three final states, every guest/native/device
field, every PCM field and the bounded WAV bytes**. Final execution remains
2,920,491,782 native / 981 interpreted retirements, 981 guard misses and
460,685 native / zero interpreted block transfers. The original 44,832
identities / 57 MPR mappings were re-emitted for ABI 15; all 208 generated
files retain the translated operations and guards, changing only ABI assertions.

The original 709 compare-and-swap transactions submit 49,303 bytes and change
723 bytes. No new assists or campaign progression are added. This route
regresses existing behavior; the authored CPU and independent Gear tests
supply the new latch-port coverage. No retail latch usage, independent retail
mixed-PCM parity, packaged device playback, listening or hardware qualification
is claimed. Both owned headless children exit normally; all seven protected
inputs and the original capture remain unchanged.

These direct runs use a disclosed private frozen snapshot of the consumer's
helpers, adapted for ABI 15. A new preflight initially omitted the existing
route-directory capture fallback and stopped before launching a game. The
exact old helper, failed preflight logs and harness are preserved; a separate
amendment records the corrected path resolution. Original captures are present
and match their previous receipt hashes. Actual successful supervisors and
qualifications are retained independently. At this latch-port milestone,
the consumer's separate native-coverage work remained on its published
capture-only ABI-13 pin; the ABI-15 adoption is qualified separately above.

## Retained ABI-14 audio timing and source accuracy

Default source timing now uses **ceiling-rational sample edges**, beginning at
master tick 488 rather than 487, and holds each PSG channel's stereo DAC output
between positive PSG clocks. Timed DDA/gain/control writes no longer become
audible before the next PSG clock; waveform-memory writes and DDA-falling
transitions retain their immediate update rules. Explicit
`--audio-timing legacy` preserves the preceding floor-edge/analytical PCM path.
Raw/filtered selection and 44.1/48 kHz output remain independent of timing.

The implementation is frozen at
[`8b620e0e2f07f12997637645fb938f231a31c097`](https://github.com/rages4calm/pcenginerecomp/commit/8b620e0e2f07f12997637645fb938f231a31c097),
source digest `00b49884c490729b33c05b01dc315811629ebb77cef686ff45ae747dd70976ef`
over 53 canonical files. Runtime **ABI 14** adds per-channel held DAC state;
descriptor schema remains **1**. ABI-12/13 captures can be re-emitted, with
modules and runtime rebuilt together. Old compiled modules are incompatible.

The expanded SDL/native-module build passes **29 suites and all 308 Python
tests without skips**. Authored timing checks pass 29,418 expectations;
776 PSG checks include held writes, and 16,748 CDDA cursor checks run under
both timing profiles. Existing DSP, mixer, decoder and host suites pass.
A clean immutable public-source build without SDL or a generated game module
passes **27 suites**, discovering the same 308 Python tests with eight
intentional desktop-only skips.

The separately compiled unchanged Geargrafx clock-driven oracle passes
**102 authored cases / 1,551 checkpoints / 75,137 stereo frames**, measured
after integer one-third mixer headroom. It uses actual source clocks, timed
register writes and real ADPCM decoding from authored RAM at all 16 rates;
decoder state is compared separately. It injects no predictor/filter state.
Ordinary callback partitions agree; three overdue-rate cases explicitly use
single-master-tick Gear callbacks and retain its coarse-callback disagreement.
Fader master time, delayed bus slots/DMA, CDDA, pre-mix source S16 equality,
retail mixed-audio parity, listening and hardware remain outside that oracle.

The additive capture-window ancestor
[`c5aa9a26125edabdbe98a68bf716bff6eacd310e`](https://github.com/rages4calm/pcenginerecomp/commit/c5aa9a26125edabdbe98a68bf716bff6eacd310e)
retains ABI 13 for consumers qualifying native coverage separately. Its clean
no-module build passes 26 suites / 294 Python tests with eight desktop-only
skips; all 11 focused capture tests run without skips. The current ABI-16
toolkit includes the same `--code-capture-start-frame` feature. Capture starts
after a completed-frame threshold at a safe instruction boundary; its report
separates preceding retirements from the capture window. It does not restore
or certify game bytes. See [CODE_CAPTURE.md](CODE_CAPTURE.md).

## Ys III timing regression through TCP

Two fresh ABI-14 **headless** TCP executions finish the same assisted
**93,735-frame route**. Both match all 25 complete guest image hashes, all
25 checkpoint states, three final statuses and every original guest/device
diagnostic. Execution remains **2,920,491,782 native / 981 interpreted
retirements**, 981 guard misses, and **460,685 native / zero interpreted
block transfers**. The original module's 44,832 identities / 57 mappings were
re-emitted for ABI 14; its 208 generated files differ only in ABI assertions,
with translated operations, guards, capture and exclusions unchanged.

| Timing/output | Actual result |
|---|---|
| Legacy raw 44.1 kHz | All 13 PCM fields and bounded WAV match the retained raw baseline exactly: 69,095,406 frames, hash 7,177,686,580,420,813,080, peak 13,000 and zero discard |
| Gear filtered 48 kHz | 75,205,884 output frames; hash **12,432,665,724,897,062,919**, 71,837,759 nonzero frames, peak 13,355 and zero discard |
| Gear raw-source projection | 69,095,406 source frames; hash **16,552,896,032,681,844,245**, 65,958,169 nonzero frames, peak 13,000; nonzero PSG 27,644,754 / ADPCM 4,030,676 / CDDA 49,762,727 |

At all checkpoint/final statuses, gear source counts equal
`floor(guest_ticks*44100/21477273)` and 48 kHz output counts equal
`floor(source_frames*160/147)`. Final guest time is 33,650,360,835 ticks.
The bounded 30-second filtered WAV still has 1,440,000 frames and SHA256
`daac69ca4a6707ac94fe4fc5f6006c362a3918835ef52b909e6183c7e8d7770d`;
its retained opening does not expose the later full-stream timing changes.
Whole-stream hashes/activity counters provide the additional regression data.

The original 709 compare-and-swap RAM transactions submit 49,303 bytes and
change 723 bytes. No new assists or campaign progression are added. A private
wrapper initially confused submitted and changed bytes in its last assertion;
both actual supervisors had already passed and exited normally. A separate
read-only closeout independently rechecks the retained executions, journal,
full comparisons and provenance. Original failure receipts remain unchanged;
no game replay or raw output is rewritten to close that harness error.

These are direct supervised headless runs using a disclosed private snapshot
of the consumer's helpers, adapted for ABI 14 and explicit timing validation.
They do not claim official consumer `project run`, new packaged/device
playback, independent Gear retail mixed PCM or listening/analog qualification.
All seven protected inputs and the original capture remain unchanged; both
owned headless children exit cleanly. The consumer's separate native-coverage
work can use the published ABI-13 capture-only ancestor without adopting the
timing migration.

## Retained ABI-13 audio filtering and resampling

At this retained pin, the default was **raw 44.1 kHz stereo**, preserving the
preceding samples, diagnostics and guest timeline. `--audio-profile filtered` added PSG DC
blocking and ADPCM DC/low-pass filtering with gain smoothing. Filtered
output supports 44.1 kHz passthrough or `--audio-rate 48000` using an authored,
fixed-memory **64-tap, 160-phase Q30 FIR**. Consumer schema **1** optionally
selected the same profile/rate. That correction retained **ABI 13**, allowing
the then-existing 208-file module to be reused after a runtime rebuild. The
ABI-15 sample-latch upgrade required module regeneration; current ABI 16
also requires regenerated modules.

The implementation is frozen at
[`72bd5a2d4616d50d8b19f0d78c5af6ddfbd1c777`](https://github.com/rages4calm/pcenginerecomp/commit/72bd5a2d4616d50d8b19f0d78c5af6ddfbd1c777),
with 53 canonical source files and source digest
`0bfa0312dfaa28e4ae0371007385086c885d8fd6f4e5a231870f4d61b557aef3`.

The filtered profile retains unclipped PSG half-sample precision and ADPCM
history while decoder values are held or stopped; ADPCM reset clears its
filter history and restores initial gain. Guest clocks,
source observations and the raw reference path remain separate from these
presentation histories. At 48 kHz the output count is exactly
`floor(source_frames*160/147)`, with **31 source frames** of causal FIR delay,
zero initial history and no synthesized tail. PCM drains and presentation
pauses do not reset the DSP. Filtered diagnostics explicitly distinguish raw
44.1 kHz observations from processed output frames/hash/WAV.

| Evidence | Result | Limit |
|---|---|---|
| Expanded-module SDL build | **28 suites / all 291 Python tests pass**, without skips; 478,512 authored DSP checks, 20,852 mixer expectations and 159 SDL dummy-device checks | Windows x64; component/host tests, separate from retail-route and physical-device evidence |
| Clean frozen public-source default build | **26 suites pass; 291 Python tests discovered with eight intentional desktop-only skips** | Windows x64, no generated game module or desktop host; distinct from the expanded SDL configuration |
| Separately compiled unmodified Geargrafx 1.8.4 PSG filters | **3,266 authored cases / 59,505 stereo frames match exactly**; actual one-frame and 509-frame reference drains agree | Positive source-clock observations and synthetic unclipped half-sample sums; no hardware, final-mix or resampler parity |
| Separately compiled unmodified Geargrafx ADPCM filters | **17 held-input cases / 34,112 stereo frames match exactly**, including reset, decay and fader targets zero/one | Per-sample reference drain only; fixture-controlled held predictor/fader inputs, without ADPCM decoder/clock integration or continuous fader-timeline qualification |
| Authored FIR response | All 160 phases, DC–18 kHz in 50 Hz increments: maximum magnitude error **0.00166081 dB**; worst phase at source Nyquist **−72.2656 dB**. Streamed 20.5/21.5/22 kHz tones produce 23.6/22.6/22.1 kHz images **−81.35/−77.62/−78.17 dB** relative to input | Analytic/authored coefficient and actual rational-stream tests, without Geargrafx/SDL device-conversion or analog measurements |
| Independent filter-reference review | **480 checks pass**, rehashing **244 actual artifacts** with no pending evidence; source/compiler/probe/plan/output bindings and the claimed comparisons are independently checked | Audits the recorded external execution; not another emulator, a new retail run or physical audio measurement |

The filter oracle binds 130 external source/header files, four libraries,
compiler options, probes, plans and raw output hashes, and rejects unpinned
compilation inputs. Seven authored adapter tests exercise its preservation
and failure checks. The original GPL implementation remains an external
reference; the runtime contains independently authored equations and FIR
coefficients. See [AUDIO_OUTPUT.md](AUDIO_OUTPUT.md) for exact equations,
controls, diagnostics, reference commands and source provenance.

Filtering the existing 44.1 kHz observations cannot reconstruct transitions
already lost at that stage or remove aliases already folded into them.
Geargrafx source-filter agreement does not qualify its final unity-gain mix,
host resampling, the console's analog circuit or complete retail sound.
The earlier raw-source and consumer results below retain their original scope.

## Retained ABI-13 packaged Ys III consumer qualification

The [Ys III consumer revision 6f0f9bf](https://github.com/rages4calm/ys3recomp/commit/6f0f9bf645495c2510ae128fb525fe078979a00f) rebuilds against
the frozen filtering/resampling pin above. Fresh headless reference
runs and packaged desktop TCP replays each complete the same **93,735-frame
route**, once with raw 44.1 kHz and once with filtered 48 kHz output. All
**25 complete guest image hashes, 25 checkpoint states and three final TCP
statuses** preserve the original guest fields. Final CPU/device/source state
and execution counts remain exact: **2,920,491,782 native / 981 interpreted
retirements**, 981 guard misses, **460,685 native / zero interpreted block
transfers**. Both hosts exit normally under each profile.

| Complete-route audio | Result | Scope |
|---|---|---|
| Raw 44.1 kHz reference and desktop | All 13 existing PCM fields and bounded 30-second WAV remain identical to the retained raw baseline: **69,095,406 frames**, PCM hash **7,177,686,580,420,813,080**, peak 13,000, 65,958,163 nonzero mixed frames and zero runtime discard | Raw default and diagnostics remain unchanged; unthrottled device output is intentionally muted |
| Filtered 48 kHz reference and desktop | **75,205,884 output frames**, exactly `floor(69095406*160/147)`; PCM hash **8,515,195,911,678,413,936**, peak 13,355, 71,837,781 nonzero mixed frames and zero runtime discard; processed PCM/WAV match across hosts | 31-source-frame FIR latency, no tail flush; internal cross-host reproducibility, not Geargrafx retail mixed-output or hardware parity |
| Unchanged raw source domain | 69,095,406 source frames; raw hash 7,177,686,580,420,813,080, peak 13,000, 65,958,163 nonzero mixed frames; nonzero PSG **27,644,755**, ADPCM **4,030,681**, CDDA **49,762,727** | Source counters/observations retain the 44.1 kHz domain, separately from processed output |

The filtered 30-second WAV contains **1,440,000 stereo frames / 5,760,044 bytes**,
SHA256 `daac69ca4a6707ac94fe4fc5f6006c362a3918835ef52b909e6183c7e8d7770d`.
This is the same assisted IPL-entry/`gear-good`/volatile-BRAM route, including
the original **709 RAM transactions / 723 changed bytes**. There are no extra
assists or new campaign progression. The seven protected inputs and original
code capture remain unchanged. This demonstrates presentation isolation and
repeatability, without independent retail mixed-audio, analog or listening
qualification.

The frozen consumer DSP qualification passes strict comparisons against the
old raw baseline and the new raw/processed headless references, including all
25 checkpoint states and three final statuses. Raw source fields and original
guest diagnostics remain exact while declared processed-output fields use
their separate profile-specific expectations.

The final independent batch audit passes **1,997 checks** and rehashes
**1,065 actual artifacts**, including every frozen consumer evidence binding,
with no failures or pending evidence. It checks the recorded Geargrafx filter
comparisons, authored FIR tests, builds/packages and internal retail replay
results within their separate scopes. This audit does not add independent
retail mixed-audio, decoder-clock, physical-device or listening qualification.

Two separate paced packaged executions select filtered 44.1 and 48 kHz output.
Both start in an empty
isolated working directory with no SDK or packaged `bin` directories on the
child `PATH`; actual same-process module inspection before and after execution
confirms the adjacent SDL DLL path/hash against the executable/build receipt.
Official descriptor verification and builds remain distinct from these direct
TCP-supervised executions; they are not official `project run` receipts.

Both runs generate **710,526 raw source frames** with raw PCM hash
**9,100,448,555,341,449,602**, peak 10,366, 524,060 nonzero raw mixed frames
and zero runtime queue discard. This paced opening contains CDDA energy but no
nonzero PSG/ADPCM source frames, so these checks qualify output conversion,
packaging and pacing rather than active source-filter quality.

| Paced output | Result | Host queue accounting |
|---|---|---|
| Filtered 44.1 kHz | 710,526 output/WAV frames; PCM hash 9,100,448,555,341,449,602 and peak 10,366 | 2,393 explicit pause-flush drops; peak pending 1,364 frames; final queue zero |
| Filtered 48 kHz | **773,361 output/WAV frames**, exactly `floor(710526*160/147)`; PCM hash 17,430,929,810,710,949,061 and peak 10,434 | 2,782 explicit pause-flush drops; peak pending 1,675 frames; final queue zero |

The queried SDL devices report the selected 44.1/48 kHz rates respectively,
stereo and numeric format 33056 (F32). Device acceptance/drain and queried
format do not qualify listening, analog levels or device-sample/WAV parity.
Both tests retain timestamped snapshots at least 0.15 seconds apart proving
paused guest clocks, source/processed counters and hashes remain unchanged;
resume, input press/release, guest/presentation captures and clean quit pass.
There are no RAM edits, and both owned children stop. All **190 consumer
tests** pass, including 15 new DSP qualification cases.

A fresh authored embedded SDL build uses an empty game module and completes
119 build steps. Its unchanged normal `scripts/check.py` runs **28 upstream
suites and all 291 Python tests with zero skips**, including the original
packaging test's nested SDK discovery. No test adapter or `PCE_TEST` override
is used. This qualifies the shared nested CMake-cache discovery correction;
it uses no retail execution, owner installation or saves. The consumer's 190
tests also pass in that configuration. The earlier raw-route results below
retain their original scope.

## Retained audio accuracy — digital reference

The PSG digital reference now uses a complete 32-sample waveform mean for
ordinary effective periods **1–5**, with per-channel nearest rounding and
ties away from zero before channel summation and half-scale truncation.
Period zero still means 4,096 PSG clocks. Periods 6 and above, DDA, noise,
configured LFO source/destination channels and trigger-held channel 1 retain
their separate sample rules. Waveform writes immediately affect the mean;
oscillator phase, guest clocks and register state remain unchanged.
No state field, runtime ABI **13** or consumer schema **1** changed.

The implementation is qualified at revision
`df7e16d465b1618e936d2750bdbe3259b56996a9`, source digest
`f2615f6278c030542fdef56e1709e6891f6e349662b2869a3a11f606a0431caf`.
That expanded-module SDL build passes **27 suites and all 273 Python tests**;
focused authored checks include **732 PSG** and **20,828 mixer** expectations.
A clean public-source default build passes **25 suites**, with seven
desktop-only skips among the same 273 discovered Python tests.

| Evidence | Result | Limit |
|---|---|---|
| Separately compiled Geargrafx 1.8.4 PSG source | 3,262 authored cases / 49,258 raw stereo pairs match, including six waveform indices and two noise seeds per observation, fractional means, side gains, both DAC profiles, DDA, noise and LFO | Pinned external source; positive oscillator-clock boundaries, raw half-gain digital profile before filters, resampling or source mixing; no zero-clock cached-DAC, CPU bus-phase, game or hardware parity |
| Unmodified Geargrafx 1.8.4 ADPCM binary | 18 authored cases / 108 main checkpoints across all 16 rates; predictor/index, nibble/address/length, IRQ flags and running phase match; stop/restart/reset adds five continuous probe checkpoints from one initial state; 131 raw serialized states checked overall | Pinned Windows v44 save-state layout, uniquely identified authored 64 KiB RAM and cross-checked public fields; no filtered/scaled emulator output or analog DAC parity |
| Finite ADPCM end | Decoder/end state agrees; reference stopped-phase residue 186,918 and runtime residue 55,846 are independently derived from the same vector | Their difference is two master ticks: Gear retains its whole six-tick CPU callback remainder; runtime stops at the exact integer tick. Stopped phases are explicitly not claimed identical |
| Independent evidence review | Reproduces both oracle comparisons and verifies bound source, binary, input and output identities | Source/state evidence only; not a second emulator or independent retail-route comparison |
| Fresh corrected-profile Ys III headless TCP replay | All 93,735 frames, 25 complete guest image hashes, 25 checkpoint states and every original final guest diagnostic match; 2,920,491,782 native / 981 interpreted retirements, 981 guard misses and all 460,685 block transfers native remain exact | Same assisted route, 709 original RAM transactions / 723 changed bytes, explicit `gear-good` profile, IPL entry and volatile BRAM; no extra assistance, campaign progress or independent retail-route comparison |
| Corrected-profile full-route digital output | All source counters and output remain unchanged: 69,095,406 frames; nonzero PSG 27,644,755, ADPCM 4,030,681, CDDA 49,762,727, mixed 65,958,163; peak 13,000, PCM hash 7,177,686,580,420,813,080, zero runtime discard; bounded 30-second WAV remains byte-identical | The authored ultrasonic cases exercise the correction. This route supplies regression evidence and demonstrates no retail PCM change or audible improvement |

The old PSG implementation fails the new unchanged oracle plan; the corrected
implementation passes. ADPCM runtime behavior did not need a decoder change.
The adapters preserve external source/binary/input identities, stop their
owned Gear process and remove its temporary configuration. Authored adapters
and wrappers are public; the GPL reference implementation stays an external
input and is not included or linked into the runtime. Commands and source
pins are documented in [AUDIO_OUTPUT.md](AUDIO_OUTPUT.md#independent-digital-source-checks).
The fresh replay independently reproduces the earlier PCM/WAV values below
with the corrected source. Its retained 1,323,000-frame WAV has SHA256
`ee86382ebc96da7833c3b6fe36dd6b8c7703cc9a8f85d00e3f1d6d25b123d40f`.
Normal before/after source, input, capture and consumer-pin identity checks
pass. An earlier completed attempt failed its final context-identity check
after the concurrent consumer pin changed; that failed receipt remains
retained. The fresh run freezes the pin and passes the ordinary checks.
All seven protected inputs and the original code capture remain unchanged;
the owned headless child stopped. The earlier measurements below retain
their original qualification scope.

## Retained packaged Ys III consumer qualification

The separate [Ys III consumer revision 4046079](https://github.com/rages4calm/ys3recomp/commit/40460793193227f2ab6adadde5040f1b0a797f84)
rebuilds against the corrected toolkit revision `df7e16d` and source digest
above. The same 208 generated module files retain all 44,832 identities /
57 complete MPR contexts and are reused unchanged under ABI 13.
Its packaged desktop TCP replay independently reproduces the same complete
93,735-frame route, 25 guest image hashes/checkpoint states, original guest
and native/interpreted diagnostics, every source/mixed audio counter, PCM hash and WAV.
No extra assistance or audible-improvement claim is added.

Both the full and separate paced executions use an empty isolated working
directory and child `PATH` without SDK or packaged `bin` directories.
Live same-process inspection before and after execution confirms the
adjacent SDL DLL's path/hash against the bound executable and build receipt.
The full route intentionally mutes fast-forward device output.
The paced probe opens the default audio device, keeps fast-forward mute
false, and submits **710,526 frames**, with zero runtime discard, **2,680
pause-flush drops**, peak pending queue **1,583**, and final queue zero.
Timestamped snapshots at least 0.15 seconds apart prove paused guest/PCM
invariance; resume advances frame 901 to 962. TCP input, guest/presentation
captures and clean quit pass. Both owned children stopped.

All **116 consumer tests** pass. The fresh embedded authored build discovers
273 upstream Python tests with one nested SDK-discovery skip; that original
packaging test body passes separately with explicit SDK discovery and no
skip. This is distinct from the standalone expanded SDL build's all-273,
zero-skip result above. The final independent audit passes **137 checks**
and rehashes **487 actual artifacts**, with no pending evidence. Official
descriptor/build verification and direct TCP supervision retain separate
scopes; these are not official `project run` execution receipts.
See the [consumer package procedure](CONSUMER.md#verify-a-windows-desktop-package).

## Retained packaged Ys III qualification

This retained qualification precedes the PSG correction above.
The separate [Ys III consumer](https://github.com/rages4calm/ys3recomp)
builds its desktop executable through the official interface against toolkit
revision `cca01ca746cbee224f9050bb4064779f1800d093`, source digest
`cedf5f31116a20d7dd5eacdec8eeb156d67a962ef22f9c40316e9dd87f5dcfec`.
Consumer revision [97a013b](https://github.com/rages4calm/ys3recomp/commit/97a013b515a0b11d3a831ff1305d86f0607ddcf2)
records this qualification and its reusable package/queue validation tests.
The packaging correction changes neither runtime ABI **13** nor descriptor
schema **1**. The same 207 translation units and one generated header retain
44,832 identities / 57 complete MPR contexts and the original six-byte
promotion exclusion. No runtime/compiler source change was needed in this
qualification batch.

Both paced and full-route executions use an empty isolated working directory
and a child `PATH` without SDK runtime or packaged `bin` directories. Live
process inspection at startup and completion identifies the adjacent
`SDL3.dll`, matching the DLL hash bound in the new build receipt. The
executable and packaged DLL retain those hashes after execution. No SDK
`PATH` workaround, implicit DLL copy or owner environment change is used.

| Evidence | Result | Limit |
|---|---|---|
| Packaged desktop TCP replay | All 93,735 frames, 25 complete guest image hashes, 25 checkpoint states, 709 original transactions / 723 changed bytes and final original guest diagnostics match | Same assisted IPL-entry route and explicit `gear-good` profile; no extra assistance, progression or independent retail-route qualification |
| Native execution | 2,920,491,782 native / 981 interpreted retirements, 981 guard misses and all 460,685 block transfers native remain exact | Coverage measures this observed route, including firmware/wait loops; no complete-game coverage claim |
| Full-route digital output | 69,095,406 stereo frames, PCM hash 7,177,686,580,420,813,080 and all source counters match; zero runtime discard. The bounded 30-second WAV is byte-identical to the earlier audio qualification | Unthrottled presentation is explicitly muted; route PCM/WAV agreement is internal reproducibility, not audible or analog parity |
| Paced packaged SDL stream | 710,526 frames accepted/drained; device open, fast-forward mute false, zero runtime discard, peak pending queue 1,600 frames, final queue zero; 2,916 device frames discarded by explicit pause flushes | Separate paced TCP input, guest/presentation capture, pause/resume and clean-quit test; no RAM edits, listening or analog-output qualification |
| Test suites | Toolkit: 27 suites and all 254 Python tests pass; consumer: all 104 tests pass | Windows x64; retained default-source and other reference scopes remain below |

Official descriptor verification and build receipts bind the package. A
separately bounded direct TCP supervisor owns the execution tests; these are
not official `project run` execution receipts. One paused checkpoint's TCP
snapshot precedes the main-thread audio drain, retaining 29 generated frames
in the bounded 8,192-frame source queue. The other 24 checkpoints and final
drain have zero pending source frames. This source queue is checked separately
from the SDL queue and explicit device drops; runtime discard stays zero.
Both test children stopped.
The final evidence audit passes 92 checks and rehashes 238 artifacts. The
earlier qualifier failure remains retained: it incorrectly required every
checkpoint to have drained immediately. The corrected validator checks the
bounded pending frames, applies WAV quotas to actually drained frames, and
requires final queues to settle; authored acceptance/rejection regressions
cover those contracts. No runtime result or raw route receipt was changed.
Volatile BRAM, conditional firmware entry, unknown-command response and
assisted-encounter limits remain unchanged. The earlier consumer audio batch
used the SDK `PATH` workaround; its receipts remain retained under that scope.
This batch establishes the subsequent packaged execution rather than
retroactively changing those receipts. See the
[consumer package procedure](CONSUMER.md#verify-a-windows-desktop-package).

## Windows embedded desktop packaging correction

A parent-created desktop consumer now receives its selected SDL runtime DLL
beside the executable, with that DLL included in build/execution receipt hashes.
Previously the directory-local imported SDK target was hidden from the parent
packaging rule: an authored build succeeded but exited with loader status
`0xC0000135` before guest entry. Runtime metadata is now captured where the
target is visible; configuration mappings are preserved without global target
promotion or a CMake minimum increase.

Two added regression tests cover imported scope, single/multi-configuration
selection, static/built targets, actual SDK packaging, execution without SDK
DLL directories on `PATH`, and refusal after packaged-DLL tampering. The authored
consumer executes 200 native / zero interpreted instructions through the official
interface. Runtime sources, ABI 13 and consumer schema 1 are unchanged; the
audio/gameplay evidence below remains its original qualification scope.
The packaging-correction expanded/SDL builds pass 27 suites and all 254 Python tests. Clean
default public source passes 25 suites with seven desktop-only skips among
254 Python tests. These are Windows x64 results; other hosts remain unqualified.
The correction was qualified at code revision
`a4c1de1602b6d383436a5c20d4493ad22a7b3428`, source digest
`cedf5f31116a20d7dd5eacdec8eeb156d67a962ef22f9c40316e9dd87f5dcfec`.
The standalone runtime executable hashes are unchanged from the audio batch.

## Digital audio milestone — ABI 13

This retained milestone records the initial digital profile and its original
PCM/WAV results. The current PSG correction and larger oracle scope are above.

The runtime now produces 44,100 Hz signed-16 stereo PCM from centered
HuC6280A PSG synthesis, the unsigned 12-bit wrapping MSM5205 ADPCM decoder
and read-only CHD CDDA samples. Fixed one-third source gains, CD fader gating,
a bounded guest-clock queue, optional SDL playback and explicit bounded new
WAV capture are implemented. Guest cadence and device control/IRQ state remain
separate from host presentation. See [AUDIO_OUTPUT.md](AUDIO_OUTPUT.md).

At this retained milestone, native ABI was **13**; consumer TOML schema was **1**. ABI-12 code
observations can be regenerated into ABI-13 modules; compiled ABI-12 objects
must not be linked to the new runtime. The optional consumer `[runtime] audio`
setting selects `on|off`; omission preserves the host's default. Desktop
attempts audio by default; headless stays off unless explicitly requested or
capturing a WAV. Disabled audio preserves the previous reference path.
Unthrottled desktop execution mutes device presentation and reports
`fast_forward_muted`; source-clock PCM and bounded WAV capture continue.

| Evidence | Result | Limit |
|---|---|---|
| Focused authored digital tests | 20,692 mixer, 154 PSG, 4,220 ADPCM, 11,830 CDDA provider/cache and 8,374 CDDA stream-order checks pass | Source expectations are not an external oracle |
| Retained audio-batch builds | Expanded module: 27 suites / all 252 Python tests pass. Clean public-source default: 25 suites / 252 Python tests discovered, six desktop-only skips; clean SDL: 27 suites / all 252 Python tests pass | Windows x64; empty module selection in public-source builds; superseded test counts are recorded in the packaging correction above |
| Independent Geargrafx 1.8.4 raw CDDA | 56 stereo pairs / 112 scalar samples match, including 40 audio pairs and 16 data-track silent pairs | Authored CUE/BIOS; samples selected by observed LBA/frame identity; no CHD decompression, exact sample-clock/seek, mixed-output or hardware parity |
| Independent Geargrafx PSG phase | 24 settled waveform-index checks match at frequencies 64, 127 and 512 | Safe mid-period checkpoints after DDA fall; no raw PSG/ADPCM PCM, hidden noise/LFO state or analog output comparison |
| SDL audio host | 150 focused authored queue/pause/bounds checks passed; 18 CLI/WAV integration tests pass, including dummy-device unthrottled mute | Synthetic host/CLI checks, separate from real-device evidence |
| Paced real SDL device stream | 930,219 PCM frames submitted; device opens, `fast_forward_muted=false`, zero runtime discard, 1,032 pause-flush device drops, peak pending input 1,591 frames and final input queue zero; PCM hash 13,875,472,373,063,429,143 | Approximately 21 paced seconds; data accepted/drained through SDL, not listening, loopback, analog-level or complete-game audio qualification |
| Current Ys III bootstrap | 30 million instructions: ABI-13 audio-off report matches the retained baseline exactly; audio-on matches after removing only the new `audio_output` object; 783,067 PCM frames, 598,753 nonzero CDDA frames, 596,601 nonzero mixed frames, peak 10,366, zero queue discard | Bootstrap scope only; no PSG/ADPCM energy on this segment |
| Full ABI-13 audio-enabled Ys III SDL/TCP route | All 93,735 frames, 25 complete guest PNG hashes, 709 original RAM transactions / 723 changed bytes and every original final guest JSON value match the previous full-native ABI-12 run; 2,920,491,782 native / 981 interpreted instructions, 981 guard misses and 460,685 native / zero interpreted block transfers remain exact | Only new validated `audio_output`, ephemeral TCP port and SDL host telemetry are separate; no original guest-field projection, extra assistance or progression; no whole-RAM, independent retail-route or hardware parity |
| Full-route digital PCM and WAV | 69,095,406 stereo frames; nonzero PSG 27,644,755, ADPCM 4,030,681, CDDA 49,762,727, mixed 65,958,163; peak 13,000, PCM hash 7,177,686,580,420,813,080; zero runtime discard. WAV retains 1,323,000 frames / 5,292,044 bytes with truncation reported | Source counters overlap; WAV is the first bounded 30 guest seconds. Unthrottled device presentation intentionally drops all submitted frames under `fast_forward_muted=true`; this run is not playback proof |
| Official ABI-13 consumer contract | Twelve translation units / eleven identities / one MPR context execute 200 native / zero interpreted instructions; A=31, PC=16409, ticks=2385; four PCM frames at stereo (1,761, 0), peak 1,761 and hash 2,178,522,702,462,881,053; complete eleven-observation ABI-13 capture | Source/module/input/output/capture pins validated; authored program, not game sound or hardware parity |

The successful owned Gear process stopped and its temporary portable
configuration was removed. All three authored reference inputs remain
unchanged. The first probe correctly refused while the independent playback
delay was still pending; the final adapter observes seek and playback-delay
completion separately before comparing exact raw samples. No runtime
expectation was relaxed to make that reference check pass.
The full route and paced SDL test also stopped their owned children. Paced PCM contains 745,905
nonzero CDDA frames and 743,753 nonzero mixed frames, peak 10,366. These are
source/queue measurements; they do not establish what reached the speakers.
The full route's 306.1768-second wall time is an operational run bound, not a
controlled speed benchmark. Retained performance measurements below belong
to the prior ABI-12 dispatch batch. That audio qualification used revision
`d72d6583e492224656ec0638f52e02798738ffb8` and source digest
`f873f8d0e06418dffbf1ed478cd46bf1eae6fdf4511fc2797db8193bf04c99f6`;
documentation-only closeout does not change that source digest.

All seven protected input hashes remained unchanged. No original media,
owner save, installation or settings were modified.

## Retained dispatch and module-build milestone — ABI 12

Observed-code dispatch now uses full-MPR/page/PC routing, exact opcode/operand
keys and shared identical bodies. Source peeks remain pure, checking every
byte on each instruction; direct raw RAM changes cannot hide behind unchanged
generation counters. The dedicated native-source test passes 6,668 independent
expectation groups. That retained run used runtime ABI **12** and descriptor schema **1**.

The retained 44,832-identity module emits 207 independently compiled units
with a 256-identity partition target. Its largest same-PC group has 3,695
variants and deliberately stays together. The two hosts share one module
object library. Generated sources total 22,988,937 bytes including the header,
compared with the older 17,067,985-byte source: this change targets compiler
work and dispatch cost, not smaller source text. All listed sources and headers
are hash-pinned through consumer build/run receipts. Authored compiled tests
verify same-page partition boundaries, object reuse and tamper rejection.

The final 17-unit authored probe independently passes Geargrafx's same 78-plan
matrix in both tiers: 156 CPU/MPR/latch states, 156 clock deltas and 78 complete
8 KiB RAM matches per tier, plus 306 local unchanged-state guard checks.
Native execution is 156 instructions with zero fallback. See
[measurement details](PERFORMANCE.md) and [reference scope](REFERENCE.md).

That batch's expanded-module build passes all **21** enabled suites and **231 Python
tests**. An isolated clean source checkout with the same source digest passes
all **20 default suites** (231 tests, four desktop-only skips) and **21 SDL
suites** (all 231 tests), using empty module selection and authored inputs.
The official consumer interface separately builds a five-unit authored module
and verifies its header and every source in the receipt. Execution qualifies
200 native / zero interpreted instructions, A=41, X=140, PC=16387 and 1,794 ticks,
with a complete four-identity capture and unchanged source/input/output hashes.

The final optimized-module hidden SDL/TCP run reproduces all **93,735 frames**,
**25 complete guest PNG hashes** and the original **709 RAM interventions / 723
changed bytes**. It retires **2,920,491,782 native + 981 interpreted instructions**
and all **460,685 block transfers natively**. After checking ephemeral TCP port
and SDL host telemetry separately, its complete final runner JSON equals the
previous full-native run, including tier counts and 981 guard misses. No guest
field or tier counter is projected away in this additional comparison.
The earlier lower-coverage route remains a separate bridge. This adds no new
assistance, progression, boss victory or unassisted qualification. The owned
test host stopped; no new game screenshots were retained.

Local performance measurements separately record full-module compile time
**353.221 → 70.502 seconds** at the same two-job cap (one sample each), and
**1.09472×** authored dispatch throughput across five alternating measured
pairs with identical counters/checksums. A 30-million-instruction Ys III bootstrap
with 1,062 completed frames and zero fallback has identical complete final JSON;
whole-process medians are **3.059198 → 3.015789 seconds**. These scopes differ:
the bootstrap difference is roughly 1.4%, with startup/rendering/media overhead
included. Shared host load/caches are disclosed; no whole-campaign speed claim
is made. See [PERFORMANCE.md](PERFORMANCE.md) for controls and limits.

## Retained observed-code and consumer milestone

The shared compiler now accepts bounded retired-code observations and emits
multiple complete MPR contexts, source-byte variants and overlapping observed
interpretations. Logical PC, full mapping and exact instruction bytes remain
mandatory dispatch guards. The raw capture and generated game/firmware source
stay private. These retained results used runtime ABI **12** and consumer descriptor schema **1**.

| Evidence | Result | Limit |
|---|---|---|
| Complete profiling route | 93,735 frames; 44,836 observed identities, 57 full MPR contexts, 2,920,492,763 retirements; zero dropped/unreadable instructions | Complete for this observed run only, not all reachable game code |
| Expanded direct C++ module | 44,832 compiled identities in 57 contexts; four identities / 981 observed hits excluded because they touch the temporary patch span | Original and patched interpretations in that span both remain interpreted; raw capture, original hit totals and completeness are unchanged |
| Executed coverage, full SDL/TCP replay | 2,920,491,782 native + 981 interpreted; **99.9999664% native**, up from 0.1729351%; all 460,685 block transfers native | Retired instruction ratio includes firmware/wait loops; no whole-program coverage, controlled speed benchmark or campaign-completion claim |
| Replay correctness | All 93,735 frames, 25 complete guest PNG hashes, 709 original RAM interventions / 723 changed bytes and every exposed final guest CPU/device/source value match; total retirements and clocks exact | Tier splits/guard counts intentionally change; ephemeral TCP port and additive SDL telemetry checked separately. No whole-RAM, composed-pixel or independent retail-route parity |
| Final Geargrafx observed-code probe | 78 authored plans; per tier 156 CPU/MPR/latch states, 156 instruction-clock deltas and 78 complete 8 KiB RAM comparisons; native tier 156 instructions, zero fallback; 306 local unchanged-state guard checks | Seven contexts / 21 compiled identities; remap, variants, cross-page/wrap, T/decimal, TMA/TAM, PHA/RTI. No IRQ delivery, device timing, retail-route or hardware qualification |
| Consumer interface, authored build/run | Pinned tool/source/ABI/module/input identities verified; embedded shared runtime builds without retail data; 200 native / zero interpreted instructions, A=41, X=140, PC=16387, ticks=1794; valid complete four-identity capture receipt | Source digest equals clean public-source checkout; build/run/capture identities checked separately; parent test configuration preserved |
| Separate Ys III consumer integration | Official project build/run guards reproduce all 93,735 frames, 25 images and 709 interventions with 2,784,362,065 native / 136,130,698 interpreted instructions (95.3387764%) | Consumer deliberately chooses a smaller 2,048-identity / nine-context original-code hot set; same tool source digest. Internal cross-project reproduction, not a second emulator or hardware oracle |
| Current default public-source build | All 19 suites pass; 202 Python tests discovered, four desktop-only skips | Empty module selection; authored fixtures, no private title/firmware/generated module |
| Current SDL public-source and expanded-module builds | All 20 suites and all 202 Python tests pass in each; 119 actual TCP assertions, 18 client checks, 122 SDL renderer/input assertions | Windows x64 / Clang 22.1.8 / SDL 3.4.18; other hosts and physical-controller interaction still require runs |

The successful expanded route uses the same input and assistance journal as
its baseline. It adds no new game progression or RAM intervention. The first
storehouse boss encounter and observed damage remain explicitly assisted;
there is no victory claim. The `gear-good` unknown-response profile and volatile
BRAM conditions remain visible and unresolved as before. See
[CODE_CAPTURE.md](CODE_CAPTURE.md), [CONSUMER.md](CONSUMER.md) and
[REFERENCE.md](REFERENCE.md).

## Retained hardware and gameplay evidence

The following rows preserve earlier qualification scopes and counters. Their
BRAM/debug-batch totals and older native modules describe those retained runs;
the current compiler/consumer result is recorded above.

| Evidence | Result | Limit |
|---|---|---|
| Windows x64, Python 3.14.5, Clang 22.1.8, CMake 3.31.12, Ninja | Runtime, generated synthetic modules, headless runner and optional reference probe compiled | Other hosts require their own build/run evidence |
| Retained BRAM/debug default source checkout | Generic sandbox and optional reference probes compiled; all 19 suites pass; 155 Python tests discovered, with four desktop-only tests skipped | Windows x64; SDL disabled, empty module selection, no private dependencies or title inputs |
| Retained BRAM/debug desktop source checkout | All 20 suites and all 155 Python tests pass, including desktop and TCP host integration | Windows x64, SDL 3.4.18 SDK; empty module selection; authored fixtures only, no private game/firmware/generated module |
| Complete local verification, retained BRAM/debug batch | All 20 enabled suites pass, including 155 Python tests | Windows x64, optional SDL enabled; authored synthetic tests; public-source-only qualification is reported separately |
| Frontend/host unit suite, retained BRAM/debug batch | 155 tests pass, including initial-BRAM loader and execution-limit checks, 18 development-client checks and DMA-populated SATB/paused-observation checks | Media/analysis/decoding, loader/source protection, descriptors, controller/scripts, explicit response profiles, reference adapters and live runner/server integration; not retail game fixtures |
| Generic initial BRAM image, retained BRAM/debug batch | Optional read-only exact 2,048-byte seed loads into existing volatile BRAM; absent option preserves blank state; TCP/final JSON identify whether seeded | No formatting, file modification, export, persistent host saves or runtime ABI change; guest changes remain process-local |
| Local formatted-start SAVE/LOAD, retained BRAM/debug batch | Normal SAVE slot 1 at frame 17,886 and LOAD at 18,324 restore Weapon Shop with HP 20, EXP 0, gold 100 and STATUS strength/defense 20/25 | Authentic System Card FORMAT seed is read-only and unchanged; game uses existing volatile BRAM; no cross-process persistence/export or authentic-reset qualification |
| Independent Geargrafx formatted-start SAVE/LOAD and STATUS, retained BRAM/debug batch | Normal SAVE/LOAD slot 1 in Sarina retains STATUS 20/25; stable LEVEL 1 / STR 20 / DEF 25 / NEXT 100 text matches the local loaded scene: 80 × 32 crop, 2,560 pixels, zero differences | Crop aligned by (+24, +3); unrelated scene/menu/cursor/counters excluded; no full-frame, damage/reward, timing, CPU-state or hardware parity |
| Normal level progression, current local and reference routes | Local LEVEL 2, HP 30, EXP 102, gold 168, STATUS 25/30, NEXT 300; Geargrafx LEVEL 2, HP 30, EXP 108, gold 172, same STATUS 25/30/NEXT 300; both reach the four-exit junction | Separate normal-input routes with unequal EXP/gold: outcome classes and displayed stats only; no independent boss, full-route, campaign or audio qualification |
| Ordinary-input local route and current-host bridge | 60,338 frames; four-exit mine junction, normal slot-3 Mine Creek SAVE/LOAD at HP 17 / EXP 132, then stairway combat ending HP 6 / EXP 152; current host matches 14 complete PNG hashes and every original final CPU/device/source diagnostic | Zero RAM edits; only new host-control metadata is projected into older expectations; current-host reproducibility, not whole-route independent emulator or final SDL qualification |
| Assisted local route and retained replay checkpoint | Owner-authorized current-health refills; Roy's Pendant at frame 66,171 and Storehouse Key at 70,079 acquired through normal chest/dialogue triggers; temporary higher jump from 77,859; replay through 79,445 matches 18 complete PNG hashes, final diagnostics and 105 edits (104 health refills, one jump patch) | Separate from ordinary gameplay; no level/max-health/equipment/inventory/quest/position edits at this checkpoint; jump patch active there; no boss or final SDL result in that retained run |
| Later assisted storehouse-interior route, replayed through 87,449 | Clean requested quit after reaching green-brick storehouse interior through an ordinary room transition under position/height assistance; fresh headless replay matches 22 complete PNG hashes, final diagnostics and 346 edits: 128 health (one menu preview), 215 position/camera/cache/height experiments, one earned-item-state transfer after LOAD, two jump-patch transactions | Failed vertical/camera experiments were cleared by normal LOAD; higher-jump patch restored at 85,900; no extra PNG copies; no boss, final SDL or ordinary-gameplay qualification |
| Assisted first-storehouse-boss encounter, final route | Boss entered at frame 93,212; observed green wizard teleport/sword/fireball behavior; ordinary II attacks visibly reduce the ENEMY bar by frame 93,735; 523 boss frames with 14 current-health refills only | No code/position/camera-queue/inventory/quest writes after boss entry; jump patch restored at 85,900; successful approach restores actually earned item checkpoint, then uses queued ascent and height-held traverse, followed by ordinary room transition/Up door entry; no boss defeat, unassisted route or independent whole-route qualification |
| Final assisted local run, retained BRAM/debug batch | 93,735 frames / 33,650,360,835 ticks; 2,920,492,763 instructions: 5,050,558 native + 2,915,442,205 interpreted; 1,181 sectors, zero read errors; 372,199 IRQ/RTI sequences; 1,835,008 ADPCM DMA bytes; final actual/HUD HP 36 / maximum 40, EXP 466, gold 484, RP 75 | 709 RAM transactions / 723 changed bytes: 145 health (one historical menu preview), 463 position/cache/raw-camera experiments, 98 canonical queue, one earlier inventory test, two jump apply/restore; explicit unknown-response profile used 51 times; no victory or full native/AOT qualification |
| Final SDL cross-host replay | All 93,735 frames reproduce; 25 complete guest PNG hashes, all 709 edit transactions / 723 changed bytes and every exposed final CPU/device/source/debug diagnostic match; clean exit 0; zero new PNG files | Same frozen source and unchanged SDL binary; comparison covers exposed diagnostics and guest images, not whole RAM or every composed SDL pixel; internal reproducibility, not independent hardware/full-game parity |
| Independent Geargrafx assisted probes | Health readback/HUD checks, paired ordinary versus higher-jump arcs, and guarded horizontal relocation within the same loaded room | Scoped assist behavior only; no complete assisted route, boss, full-frame, timing, CPU-state or hardware parity; horizontal reference relocation is not local route evidence |
| Continuous video expectations, retained first-mine checks | 3,950 independent checks pass; existing 628,214 snapshot/palette expectations also pass | Historical palette/VRAM/SATB/scroll changes, CR/MWR latches, bounded publication/reset, all VCE timing controls, partitioning and unchanged guest state; physical fetch/contention and sprite IRQs excluded |
| Independent Geargrafx continuous video, retained video batch | Four authored plans × four distinct frames: 16 complete 256 × 192 RGB images / 786,432 pixels match byte for byte; final probe bridges all images and publication timestamps exactly | Active crop of Geargrafx's debug viewport; midline palette, line-latched scroll, VRAM changes, map wrap and sprite modes; no hardware/full-game frame qualification |
| Optional SDL3 desktop host, retained first-mine tests and earlier UI evidence | 122 renderer/input assertions pass; preceding video batch observed visible menu, Run-to-warning, pause/resume and fullscreen transitions | SDL 3.4.18 Windows x64; two-frame quick-tap retention and keypad direction aliases locally tested; physical controller and other operating systems unqualified |
| Loopback development server, retained BRAM/debug batch | 119 actual TCP assertions plus 18 Python client checks pass; both hosts' integration tests pass | Strict bounded protocol, five input slots, pause/step/status/capture/quit, paused RAM/ROM inspection and opt-in compare-before-write RAM edits; source invalidation, disabled/stale/cross-bank refusals, disconnect and stalled-peer behavior; no independent PC Engine oracle claim |
| Independent Geargrafx town controls, retained town batch | Authentic-reset route: 11,230 frames; two neutral-controlled I jump/land cycles; Select menu confirmed; aligned 72 x 40 menu text crop matches all 2,880 pixels | Different startup from local IPL sandbox; blinking cursor/unrelated scene excluded; no full retail-frame, CPU-state, combat, hardware or campaign parity claim |
| Independent Geargrafx first-mine combat, retained first-mine batch | Normal quest/shop progression and visible sword; HP 20 → 10, EXP 0 → 12, gold 100 → 108; death and settled Run retry restore HP 20 | Earlier selected-gear claim withdrawn: red slots alone were ambiguous; restored checkpoint STATUS remains 10/10. Different starting scene/cadence permits outcome-class corroboration only; no exact damage/reward/frame/CPU parity, kill count, boss, campaign, audio or hardware qualification |
| Internal native/interpreter checks | 14,912 comparisons across 233 opcodes pass | Shared framework assumptions can still be wrong |
| Independent IRQ/RTI expectations | 65,536 entry cases, 262,144 RTI cases, 32 sampling sequences, 15 guard/mapping/deadline groups and 779 register/timer groups pass | Both tiers/speeds; aggregate sampling contract, no physical bus-phase qualification |
| Independent Geargrafx IRQ/RTI check | 832 plans per tier: 2,496 CPU states, 832 complete work-RAM images and 832 complete-sequence clock deltas pass | Real pending sources in reference, corresponding injected lines in local probe; no native fallback; source edge/MMIO phases and hardware excluded |
| Independent palette/snapshot expectations | 628,214 checks pass | Palette byte/index/mirror sweep, tile planes, sprite sizes/flips/priority/line budget and no simulation mutation; current-state image only |
| Independent VRAM/SATB DMA expectations | 14,786 checks pass | Direction/overlap/address wrap, dot cadence, terminal registers, completion gates and SATB priority/repeat; CPU contention excluded |
| Independent Geargrafx palette/DMA check | 12 direct-device plans pass, including full VRAM/SATB/palette and 1,024 guest palette-read bytes | Settled device effects, no per-tier CPU execution, exact DMA phases, frame rendering or hardware claim |
| Independent PSG expectations | 2,144 register groups, 174,592 waveform/DDA/LFO cases and 769 bus/latch groups pass | Write-side state only, no oscillator clocks or PCM synthesis |
| Independent ADPCM expectations | 20,736 port/slot/control groups, 67 playback/length groups, 10 DMA groups and 257 bus groups pass | RAM/ports, consumed nibbles, length IRQs and CD DMA; no decoded PCM or audio output |
| Independent Geargrafx ADPCM/PSG check | Eight direct-device plans pass: 292 guest read bytes, complete ADPCM RAM and six PSG channel states | Settled manual ports only; ADPCM playback/DMA, waveform bytes, oscillators and mixed audio excluded |
| Independent CDDA control/fader/response-profile expectations | 7,134 checks pass | D8/D9/DA/DD state/position/response boundaries, fader and explicit unknown-command profile; deterministic seek and sector timeline, no live CDDA or PCM qualification |
| Independent input-script expectations | 4,136 checks pass | ASCII/size/event bounds, full 12-bit masks, integers and host snapshot format; no desktop polling or gameplay certification |
| Independently expected bit/stack checks | 92,160 cases pass across both tiers, plus mutation/mapping/fault checks | Instruction-level cycles checked; no bus-phase/IRQ model |
| Independently expected data checks | 7,340,032 arithmetic/logic cases and 340 addressing cases pass | All ADC/SBC byte pairs under C/D/T/V combinations in both tiers; instruction-level timing only |
| Independently expected RMW/JMP checks | 3,932,160 RMW and 16,384 indirect JMP cases pass, plus native wrap/MMU/fault checks | Every RMW byte/status combination in both tiers; instruction-level timing only |
| Independently expected bit-test/branch/BSR checks | 4,849,664 bit-test and 2,228,224 branch/BSR cases pass | Synthetic operands/status/stack cases; fixed native immediate/mask values, not every encoding of literals |
| Independently expected MPR/latch checks | 1,114,112 cases pass, plus remap/mutation/deadline sequences | All masks/byte values in both tiers; arbitrary-map OR sweep interpreted; instruction-level timing only |
| Independently expected speed checks | 524,288 cases pass, plus sequence/deadline/mutation/fault checks | All status/latch bytes, both entry speeds and tiers; independently specified split-cycle tick table |
| Independently expected CD-control/BRAM checks | 67,584 native/interpreter instruction cases, 2,048 BRAM readback sequences and 16,144 decoded register groups pass, plus extent/lock/alias/RMW/guard/deadline/fault checks | Both tiers/speeds and reference BRAM readback/undefined-read decoding; idle control scope, no transport/audio scheduler claim |
| Independent Geargrafx unknown-command response check | Three plans, 87 CPU/device checkpoints and three complete RAM/BRAM comparisons per tier pass | Explicit unknown-response profile; proves protocol response, not unknown-command operations or hardware |
| Independent Geargrafx BRAM/read decoding check | Four plans, 27 CPU/device checkpoints and four complete RAM/BRAM comparisons per tier pass | BRAM gate readback, lock/alias behavior and unused decoded CD read `$FF`; no subcode interpretation or persistence |
| Independently expected CD-transport checks | 8,369 groups pass: 4,096 latch/control byte groups, 4,096 RMW groups and directed handshake/timing/reset/IRQ/guard/refusal checks | Both execution tiers and CPU speeds; literal local deadlines, TEST UNIT READY only; no sector responses or live access-phase proof |
| Independently expected TOC/DATA IN checks | 418 groups pass: literal BCD/response bytes, manual/auto-ACK timing, status/message completion, data IRQs, reset/selection aborts, metadata validation and explicit refusal | Both execution tiers/speeds; four-byte Gear/Mesen metadata-response profile, no readable sector provider or hardware qualification |
| Independently expected joypad checks | 50,341 cases/groups pass: 32,768 button, 8,192 control, 136 tap, 9,228 bus and 17 host/configuration checks; eight synthetic headless tests also pass | Both execution tiers/speeds; selected Geargrafx reference profile, no desktop polling or physical controller qualification |
| Independent block-transfer expectations | 1,600 instructions plus 5,120 status/stack cases, four local destructive-opcode cases, 23 guards/deadlines, 8,204 device checks and four deferred IRQ groups pass | Both tiers/speeds for RAM and deferred IRQ; interpreted actual MMIO plus block-aware wrapper checks; aggregate cycle profile, no exact bus-phase claim |
| Independent Geargrafx block transfers | 810 completed-instruction CPU/MPR states, 810 full 8 KiB RAM comparisons and 810 matching complete-instruction clock deltas per tier; all 16 shards pass | Both speeds, all five zero-count transfers, overlap/wrap/stack/operand aliases; no native fallback; excludes opcode-overwrite/MMIO/access phases/IRQ delivery/hardware |
| Independent READ expectations | 621,096 checks pass: full 256-sector request, both CPU tiers/speeds and ACK modes, byte/backpressure/reset/failure/guard boundaries | Deterministic 1x timing constants; no physical seek or IRQ delivery proof |
| Independent provider expectations | 22,568 checks pass: SHA256 known answers, ISO, CHD geometry/cache through an authored decoder ABI double | ABI double does not test actual decompression |
| Independent Geargrafx READ check, retained evidence | Seven plans; 201 settled CPU/device checkpoints and seven complete sectors / 14,336 payload bytes per tier pass | 15,552,742 retired native vs interpreted instructions including delay NOPs; exact seek/access/stream-loop cadence not qualified; final probe bridged exactly |
| Private on-demand CHD provider check | Six real sectors / 12,288 bytes agree with Python slicing/mapping; six protected input hashes unchanged | Shared libchdr decoder, not independent decompression qualification |
| Independent Geargrafx 1.8.4 joypad check, retained evidence | 56 plans, 2,512 CPU/port-read checkpoints and 56 complete 8 KiB work-RAM comparisons per tier pass; 2,512 native vs 2,512 interpreted instructions | USA region with CD present/absent; Japanese line local/source-only; guest output observations, no direct internal controller-state, host event timing, hardware or gameplay proof |
| Independent Geargrafx 1.8.4 TOC/DATA IN check, retained qualified scope | 25 of 26 plans qualified; 1,964 settled CPU/device checkpoints and 25 full work-RAM/BRAM comparisons per tier; 653,294 native vs 653,294 interpreted instructions | `toc-reset-auto-response-pending` remains unqualified after two reference access violations; eight earlier TOC plans bridge exactly to final ABI-7 probe; no sector, exact access-phase, hardware or gameplay proof |
| Independent Geargrafx 1.8.4 CD-transport check, retained evidence | 21 plans; 743 settled CPU/device checkpoints and 21 full work-RAM/BRAM comparisons per tier pass | 1,007,851 native vs 1,007,851 interpreted instructions including settling NOPs; frozen original 18 plans bridged exactly to that batch's final build, three added edge plans checked live; no sector backend, access-phase, hardware or gameplay proof |
| Independently expected VDC checks | 77,824 instruction expectations, 8,192 register-width cases and 392,991 VRAM transfer/address cases pass, plus status/guard/deadline/fault checks | Both execution tiers for CPU cases; synchronous functional profile; fixed access waits, no raster/rendering/DMA |
| Independent raster expectations | 977 directed groups plus 240,015 native/interpreter cadence, alias, speed and refusal checks pass | Literal edges, CR gating, status acknowledgement, timing latches, partition independence, all eight VCE timing controls; no sub-instruction bus-phase or rendered proof |
| Independent Geargrafx 1.8.4 raster check, retained evidence | 15 plans; 4,165 exact-clock device checkpoints and 15 guest status acknowledgements pass | VCE/VDC positions, horizontal/vertical phases, sticky VBlank/RCR flags and local IRQ1; divider 4 / 262 lines; direct device probe, no per-tier live CPU or bus-phase claim |
| Independent Geargrafx 1.8.4 MCP check, retained VDC port batch | 48 sequences; 856 settled CPU/VDC states and 48 full work-RAM/VRAM comparisons per tier pass | Eight disjoint shards; 14,552 native vs 14,552 interpreted instructions including 13,696 settling NOPs per route; no live busy/status-event, dynamic timing, DMA, rendering or gameplay proof |
| Independent Geargrafx 1.8.4 MCP check, retained CD-control batch | 48 sequences; 720 CPU/device states and 48 full RAM/BRAM comparisons per tier pass | Two disjoint shards; authored synthetic bootstrap/CD; 720 native vs 720 interpreted instructions; no live nonzero IRQ-source, cycle/device-phase or gameplay proof |
| Independent Geargrafx speed batch, retained prior evidence | 24 sequences; 120 CPU/speed states and 24 final RAM/latch comparisons per tier agreed; 92 tick deltas per tier agreed | Not rerun this batch; 28 documented transition-timing differences per tier remain |
| Independent Geargrafx MPR batch, retained prior evidence | 524 sequences, 1,614 instruction states and 524 final RAM/latch comparisons per route passed | Not rerun in the retained BRAM/debug batch; native-first: 1,078 native + 536 interpreted after context changes |
| Independent Geargrafx bit-test/branch/BSR batch, retained prior evidence | 480 native + 480 interpreter comparisons across all 30 opcodes passed | Not rerun in the retained BRAM/debug batch |
| Independent Geargrafx RMW/JMP batch, retained prior evidence | 512 native + 512 interpreter comparisons across all 32 opcodes passed | Not rerun in the retained BRAM/debug batch |
| Independent Geargrafx data batch, retained prior evidence | 1,552 native + 1,552 interpreter comparisons across all 97 data encodings passed | Not rerun in the retained BRAM/debug batch |
| Independent Geargrafx bit/stack, retained prior evidence | 128 native + 128 interpreter comparisons across all 24 bit/stack opcodes passed | Not rerun in the retained BRAM/debug batch |
| Independent Geargrafx baseline, retained prior evidence | 188 native + 188 interpreter comparisons across the original 47 opcodes passed | Not rerun in the retained BRAM/debug batch |
| Local owner-supplied Ys III USA CHD | Track metadata, hashing, two-hunk decompression and 4 KiB initial program extraction verified | Filename/internal title identify the local input; no external dump-database certification |
| Supplied USA v3.0 firmware | Raw 256 KiB size and MD5 match the documented USA BIOS; SHA1/SHA256 pinned locally | Supplied patched USA/Japan images have distinct hashes and are excluded from the baseline; see FIRMWARE.md |
| Boot-program-only analysis | 203 discovered instruction sites, all 203 native-emittable, 25 unresolved records | Static discovery is not an execution-coverage measurement |
| Combined local boot/BIOS snapshot | 785 discovered sites, all 785 native-emittable, 47 unresolved records under a 1,024-instruction analysis limit | One initial MPR context; no speculative firmware services |
| Compiled local boot/BIOS module, retained ABI-11 conditional story route | 229,808,207 instructions: 7,234,070 native + 222,574,137 interpreted; 288 sectors, 589,828 DATA IN ACKs including four TOC bytes, 262,144 ADPCM DMA bytes and 18,191 IRQ/RTI sequences; 22 scripted host events; Beginning/Continue → Beginning → blank volatile-BRAM warning → Proceed → opening story portraits and river/mountains/bird scene | Tick-budget stop at 3,000,000,009 ticks, about 139.7 guest seconds, no runtime fault; requires explicit `--cd-unknown-status gear-good`, used twice; no continuous rendering in this retained run, controllable gameplay, campaign, authentic reset or audio-output proof |
| Compiled local boot/BIOS module, ABI-12 continuous menu route | 30 million instructions, 1,062 completed historical frames; all compared CPU/CD/VDC fields exactly match the retained menu route | Recompiled same initial snapshot; reference-response opt-in still required; actual desktop menu observed separately; no full native/AOT or gameplay qualification |
| Compiled local boot/BIOS module, ABI-12 continuous story route | 8,356 completed frames; 229,808,207 instructions: 7,234,070 native + 222,574,137 interpreted; 288 sectors, 262,144 ADPCM DMA bytes, 18,191 IRQ/RTI sequences and all 22 scripted events; historical image shows river/mountains/bird scene | Tick-budget stop at 3,000,000,009 ticks, about 139.7 guest seconds, no runtime fault; same response-profile condition and execution totals as the retained story route; no controllable gameplay, campaign, authentic reset, audible output or full native/AOT qualification |
| Actual SDL window with TCP-controlled Ys III route, retained video batch | Menu → Beginning → warning → Down selects Proceed → I confirms → boat/mast and opening portrait scenes; 8,000 frames, 2,871,925,884 ticks / 133.7 guest seconds; 7,301,883 native + 213,086,766 interpreted instructions; 16,037 IRQ/RTI, 288 sectors, zero read errors, 262,144 ADPCM DMA bytes; clean requested quit | Eight requested guest/SDL captures, no per-frame dump; final hidden GPU-window replay matches three retained guest-image hashes and final state totals; response-profile opt-in used twice; no gameplay/campaign, authentic reset or audible output claim |
| Compiled local boot/BIOS module, retained ABI-12 TCP town-control route | 25,476 frames / 9,145,722,501 ticks; 761,925,353 instructions: 8,504,219 native + 753,421,134 interpreted; 867 sectors, zero read errors, 1,251,328 ADPCM DMA bytes, 79,118 IRQ/RTI sequences; directional movement/camera, I jump, Select menu, world map and town return observed | Clean TCP quit; exact hidden SDL replay matches five complete guest PNG hashes and all final CPU/device diagnostics; explicit unknown-response profile used four times; retained 785-site module, mostly interpreted; no combat/mine/campaign/audio/authentic-reset qualification in that run |
| Compiled local boot/BIOS module, retained ABI-12 TCP first-mine combat route | 31,819 frames / 11,422,827,780 ticks, about 531.9 guest seconds; 948,642,279 instructions: 8,504,219 native + 940,138,060 interpreted; 915 sectors, zero read errors, 1,316,864 ADPCM DMA bytes, 104,414 IRQ/RTI sequences; Tigre unlocked normally, unarmoured death/Run retry, starter gear bought and positively selected, visible sword; final HP 20 → 2, EXP 0 → 12, gold 100 → 108 | Clean TCP quit; exact hidden SDL replay matches seven complete guest PNG hashes and every final CPU/device diagnostic; explicit unknown-response profile used nine times; retained 785-site module, mostly interpreted; no guest CPU/device patch needed; exact kill count, deeper mine/boss/campaign, audio, authentic reset and full native/AOT unqualified |

The first-mine EXP observation above corrects the prior transcription of 124.
Exact glyph checks on the retained frame establish EXP `00012` and the separate
RING field `004`. This corrects the HUD reading; the equipment, attack,
received-damage and gold-reward observations are unchanged. The retained BRAM/debug build's
155-test qualification is separate from retained first-mine gameplay evidence.
New formatted-start SAVE/LOAD, STATUS, ordinary-input mine progression and
the assisted checkpoints are qualified only as listed above. The local
first-boss encounter and visible enemy damage are established under health
assistance. Final route accounting and successful SDL replay are recorded above. No boss
defeat, complete campaign or ordinary-gameplay qualification is claimed.

The public baseline has no ROM, BIOS, extracted game bytes, generated game
source, save files or initialized personal install. Private derived data is
under ignored `.local/`. Original CHD SHA256 was established before work and
is checked again at closeout; nothing writes the original image.

The local toolchain does not provide a `ctest` binary; verification uses
`python scripts/check.py`. The retained pre-desktop batch passed all 17 suites
and 112 Python tests, including a separate generic public-source build.
The retained BRAM/debug build passed all 20 enabled suites, including 155 Python
tests, adding generic initial-BRAM loading and larger explicit execution limits.
The retained observed-code/consumer build passed all 202 Python tests as recorded above.
The retained first-mine build passed 138 Python tests. GitHub CI
template uses CTest on Windows/Linux/macOS runners and separately builds the
pinned optional CHD backend. The initial CLI credential lacks GitHub's
`workflow` scope, so `.github/ci-template.yml` is initially inactive. No remote
CI pass is claimed. Enable it using the instructions in the developer guide.

## Deliberate limits

- Decoder metadata covers 256 encoding slots; runtime support is 234 opcodes.
- Load/store, logical, ADC/SBC and comparison encodings are supported, including
  indexed/indirect data addressing, T destinations and decimal arithmetic.
- Shifts/rotates, INC/DEC memory/accumulator and both indirect JMP forms are supported;
  indirect destinations remain unresolved in static discovery.
- RMB/SMB, push/pop, BIT/TSB/TRB/TST, BBR/BBS and BSR are supported.
- TAM/TMA cover all masks and the persistent transfer latch. I/O open bus is
  separate and retained by the IRQ/PSG profile. Current native ABI is 16; regenerate older modules.
- CSL/CSH use two cycles at entry speed and one at selected speed.
  Geargrafx's live transition timestamps differ; see CPU_SEMANTICS.md.
- Idle CD-control/BRAM routing and opt-in clocked selection/REQ/ACK transport
  are implemented; TEST UNIT READY and directory/TOC modes 0/1/2 complete
  through DATA IN where needed, then status and message phases. Manual and
  `$1808` auto-ACK are supported for bounded metadata responses.
  See CD_CONTROL.md for exact registers, reference delays and discrepancies.
  REQUEST SENSE and raw captured subchannels still trap. CDDA D8/D9/DA/DD has
  functional control/position responses and separately enabled digital PCM output. READ `$08` requires a separately
  attached read-only provider. Metadata-only attachment does not verify an image;
  `--disc` hashes/derives geometry and enforces exact descriptor agreement.
  The deterministic 1x profile omits seek distance, reset jitter and accelerated speeds.
- Opt-in joypad I/O routes all `$1000..$13FF` mirrors, with two/six-button
  pads, a five-port TurboTap, region/CD bits and guest-write-sampled output.
  Headless flags provide held button snapshots and bounded tick-scripted input;
  the optional SDL3 host maps keyboard/gamepad input to slot zero. Other
  peripherals remain planned. See [INPUT.md](INPUT.md) and [DESKTOP.md](DESKTOP.md).
- Functional single-VDC ports/registers, buffered VRAM and ST0/ST1/ST2 are
  implemented; the extended profile adds VCE palette and VRAM/SATB DMA, while
  undriven reads still fault. See [VDC.md](VDC.md).
- Opt-in raster timing generates VBlank and raster-comparison events from
  master-clock horizontal/vertical phases. VCE timing control selects dot
  divisors and 262/263-line frames. Optional images inspect current VRAM,
  SATB, palette and registers. Separately enabled continuous output records
  historical lines and live-dot palette values; it preserves the legacy
  non-rendering path. Physical VRAM contention/fetch phases, narrow latch
  rewrites remain. Sprite collision/overflow IRQs use a separately qualified
  device-clock pipeline. See [VIDEO_OUTPUT.md](VIDEO_OUTPUT.md).
- TII/TDD/TIN/TIA/TAI have genuine stack effects, wrapped per-byte addressing,
  17+6*n base cycles and block-aware I/O. A started bounded block completes
  past the entry deadline; IRQ entry is deferred until the transfer completes.
  Fatal faults are nontransactional; there is no partial-transfer resume state.
- IRQ delivery, RTI and timer/interrupt registers are implemented using an
  explicit aggregate sampling profile. Finer device access phases, a complete
  interpreter, full System Card profile and general bus phases remain. Base WRAM
  mirrors are implemented.
- Unknown CD commands fault by default. Explicit `--cd-unknown-status gear-good`
  selects the source-documented reference-emulator GOOD-response quirk and
  counts each use. It does not implement unknown command operations or convert
  known unsupported commands to success. Retail menu evidence is conditional
  on that profile; strict mode remains an unresolved correctness boundary.
- Both runners accept `--bram RAW_2048_IMAGE`, a read-only exact 2,048-byte
  initial snapshot for existing volatile BRAM. The default remains blank;
  there is no format fabrication, export or host file persistence. Initial
  BRAM use is visible in TCP status and final JSON. A private blank seed
  produced by normal System Card FORMAT inputs in Geargrafx eliminates the
  local startup warning; normal game SAVE/LOAD is observed within volatile
  memory. No changes are written back to the seed. See [REFERENCE.md](REFERENCE.md#initial-bram-image-and-authentic-format-provenance).
- The explicit dispatcher step allowance is at most 20,000,000,000. Tick
  deadlines and optional 1–600-second wall limits still apply.
- PSG retains functional register state and adds an opt-in centered digital
  oscillator/noise/LFO profile. ADPCM decodes consumed nibbles, and CDDA can
  supply raw stereo PCM. Bounded digital mixing, SDL playback and WAV capture
  are implemented. Optional source filters match the scoped Geargrafx
  equations, and an authored FIR supports 48 kHz output. Complete-game audible
  correctness, source-transition aliasing, final emulator mix/device-conversion parity
  and the physical analog circuit remain unqualified. See [AUDIO_OUTPUT.md](AUDIO_OUTPUT.md).
- Deadline accounting is at instruction boundaries, not cycle-accurate.
- CFG-derived modules retain one MPR context and stop discovery at mapping
  changes. Observed-code modules support multiple full contexts and source-byte
  variants, preserving per-instruction guards and explicit fallback.
- Bounded retired-code capture and offline direct emission are implemented.
  No automatic in-process recompiler, persistent overlay cache or optimizing
  block IR is implemented.
- CHD reader supports v5 CD metadata and MODE1/RAW user sectors. Boot
  extraction supports only its documented loader subset. BIN/CUE is planned.
- The headless runner loads a single contiguous payload into an explicit
  sandbox, optionally with a supplied read-only 256 KiB System Card ROM.
  It is not an authentic console reset/BIOS state.
- The optional desktop displays completed frames with nearest pixels and
  guest-clock pacing, and supports resize/fullscreen/pause/focus/input. It has
  optional bounded SDL audio output; it has no settings persistence or owner-save access. Physical audio/gamepad
  and non-Windows host qualification remain.
- The optional `pce-dev-1` TCP interface controls only the running guest and its
  SDL composition. It binds loopback, is disabled by default, and bounds
  request/response storage, polling and idle peers. Captures are requested,
  not automatic. It does not capture the owner's desktop. Paused RAM edits
  require separate opt-in and whole-range expected bytes; edit counters
  distinguish assisted tests. See [DEV_SERVER.md](DEV_SERVER.md).
- No persistent host save files, save export, rewind, netplay or enhancement release. The full target remains in
  the roadmap.

## Next useful batch

Evaluate guarded multi-instruction blocks and persistent cache identity using
the measured partitioned-module baseline. Preserve exact
source/mapping invalidation, aggregate clock/IRQ behavior and explicit fallback.
Measure compile time, instruction/cycle work and controlled end-to-end performance
separately; hot firmware loops do not measure game completion.

The separate game consumer owns campaign progression, title configuration and
its chosen hot/cold native policy. Use its focused, hash-pinned defect reports
and additional authored diagnostic programs to expand the general toolkit.
Broader audio source timing beyond the qualified scheduler/DAC vectors,
final reference mix/device parity, exact device access phases and the unknown CD command's
operation remain separate correctness tasks. The response-profile opt-in does
not resolve hardware behavior; the IPL-entry sandbox is not authentic reset.
The guest-visible CDDA sample-latch ports `$1805/$1806` remain explicitly
unsupported; their future implementation must also work with PCM presentation
disabled. A separate live reference and real core-master-time fader/ADPCM slot
integration remain useful independent checks.

### Retained dispatch-batch closeout

That batch's seven protected input hashes match. No owner installation, original media,
saves or settings were modified. The final Geargrafx process stopped and its
temporary configuration was removed. The toolkit's test hosts have stopped;
the independently owned consumer chat may continue its own tests. Desktop
control was not used during this batch.

Existing SDKs and immutable inputs were reused. The full-route check reuses
retained images, creating zero new retail PNG files.

Contributor issues reviewed on 23 October 2026: #1 (RMB/SMB) and #2 (stack) are
closed; #3 (media fixtures) and #4 (cycle-aware traces/second oracle) remain
open. This batch adds an authored Geargrafx compilation-path probe and does
not close the second-oracle or bus-phase work.

Read [ARCHITECTURE.md](ARCHITECTURE.md), [REFERENCE.md](REFERENCE.md),
[CONSUMER.md](CONSUMER.md) and [ROADMAP.md](ROADMAP.md) before continuing.
