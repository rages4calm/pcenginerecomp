# Upstream reference review — 27 November 2026

References inform independent implementations and explicit tests. Repository
updates do not automatically replace the pins or meanings of historical proof.
No upstream runtime implementation or title-specific patches are vendored here.

## RondoRecomp

The reviewed tree [a4f2545](https://github.com/gminustwo/RondoRecomp/tree/a4f254542e3e85244c229e3e12643f85ee9e162b)
is 49 commits beyond our earlier credited `c94048b` reference. Its expanded
renderer exposes sprite masks, underlays, row palettes and wider scene handling.
These useful interfaces informed our [immutable port helpers](PORT_RENDER_LAYERS.md).
Ports still own scene recovery, room limits, actor spawning, HUD and gameplay.
The new example extrapolates its authored pattern, not unknown game data.

The upstream [blanking correction](https://github.com/gminustwo/RondoRecomp/commit/2b17d6f1fe44d7c01abe81df4dfbcd873f1a5e36)
led to an independent phase-specific check. We corrected only frame-latched burst;
current CR bits alone do not identify it. [Evidence and differences](BURST_COLOR.md)
keep sprite-only and mid-frame behavior separate. Rondo's title patches, artwork,
pause menu, BIOS replacements and extra-CPU slowdown mode are not shared defaults.

## Geargrafx

Reviewed HEAD [5f3817c](https://github.com/drhelius/Geargrafx/tree/5f3817cc2041edf066a22b21384f7c8aba9bbbc3)
is [38 commits beyond the fixed `d3e264c` oracle](https://github.com/drhelius/Geargrafx/compare/d3e264c937be5ddaf67722899ec67293303f96c6...5f3817cc2041edf066a22b21384f7c8aba9bbbc3).
Latest release at review was 1.8.9. The current source review and executions of
our older pinned oracle remain distinct evidence.

| Update | Toolkit assessment |
| --- | --- |
| [VCE B&W support](https://github.com/drhelius/Geargrafx/commit/20c48a2b043478d4e715c5b7bfb73c8d1b112f28) and [shader flag fix](https://github.com/drhelius/Geargrafx/commit/435755f1c9d6de54a2f39199485d671aa8b27288) | Useful additional reference. Gear rounds luminance and uses horizontal-sync latching; our declared Mesen digital profile truncates and samples per dot. That difference needs its own qualification, not an undocumented replacement. |
| [Video timing uniforms](https://github.com/drhelius/Geargrafx/commit/937ea1eaf47859b36273713d21d289801acc24bd) and [frame-aware shader history](https://github.com/drhelius/Geargrafx/commit/c948242486abdafce05f9a778145adfbcfb6ff90) | Useful future temporal/composite shader inputs. Our current presets are stateless. The layer example uses guest sequence and checkpoint epochs, so paused redraw/resize does not advance its effect. No new temporal GPU shader is claimed. |
| [Clock-based pacing](https://github.com/drhelius/Geargrafx/commit/134d8b424443352b839829120e374aee38a7618c) | Our host already uses guest-clock pacing and late rebasing. Preserve separation from guest simulation and avoid unqualified catch-up/audio bursts. |
| [CUE backslash paths](https://github.com/drhelius/Geargrafx/commit/f7237015e04e5a980e958d2a772a231fbc611207) | Already implemented and tested here. |

The changed core files did not identify another new HuC6280, CD transport or PSG
correction to adopt in this review. Gear's current burst output still differs
from Beetle/Mesen; that is documented rather than hidden behind a parity claim.
Hardware, broader title routes and per-dot analog behavior remain separate gates.

## Completed-frame presentation follow-up

A fresh review found both heads unchanged at the pins above. The next useful
transfer is Gear's new-frame-only history policy: our
[completed-frame timing and effects](PRESENTATION_EFFECTS.md) distinguish the
current CPU clock from the timestamp of the displayed guest image. Softness and
bounded bright-value persistence have a deterministic software path; screenshots
and paused redraws do not supply extra effect frames. Existing GPU binaries and
the Mesen digital grayscale profile remain unchanged.

Rondo's shared layer/mask/underlay and tilemap interfaces are already included.
Its game-specific wider world, camera rules and assets remain consumer work.
Audited Python renderer-source graphs are still a separate gap: the supported
renderer source integration remains CMake `PORT_RENDERER`.
