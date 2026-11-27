# Completed-frame timing and host effects

The desktop host supports two optional RGB effects before its existing scaler
and shader pass. They work with the plain software renderer as well as an
enhanced port's wider frame; neither requires a GPU shader.

| Option | Meaning |
| --- | --- |
| `--display-softness 0..100` | Mix a horizontal three-pixel soft filter into the source image. |
| `--display-persistence 0..100` | Retain bright output from the preceding admitted completed frame. |

Both default to zero. Consumer `presentation` dictionaries accept `softness`
and `persistence`; `launch-plan` and `run` accept the same command-line flags.
They require a desktop producer. This is presentation only: guest RGB captures,
CPU work, device clocks, audio and checkpoint payloads remain independent.
Existing GPU presets are unchanged. Combining these controls with a GPU preset
still requires that preset's separate backend qualification.

## Time belongs to the completed image

`DesktopFrameInput::guest_ticks` retains its original meaning: current CPU time.
The new `completed_ticks` member names the actual completed guest-frame boundary.
Use `completed_ticks` together with `sequence` and `presentation_epoch` for frame
animation and history. A paused scalar instruction can advance CPU time while
the displayed frame and its completed timestamp remain unchanged. A screenshot,
resize or paused redraw must not count as another guest frame.

This follows the useful new-frame-only history policy in
[Geargrafx](https://github.com/drhelius/Geargrafx/commit/c948242486abdafce05f9a778145adfbcfb6ff90).
It does not claim Gear's historical pixel clock, chroma or per-line metadata:
this runtime does not retain those histories. Current VCE registers cannot
reconstruct them. The declared digital grayscale profile is unchanged.

## Reusable deterministic RGB helper

`pce/presentation_effects.hpp` exposes `PresentationEffects`,
`PresentationEffectSettings` and an `apply(frame, stamp, settings)` operation.
It reuses [PresentationHistory](PRESENTATION_HISTORY.md) for continuity. Comparing
the supplied image with itself establishes continuity only; it does not qualify
a port's original-size reconstruction. Perform that gate independently before
selecting an enhanced image.

For each RGB channel, softness first computes the edge-clamped horizontal
`[1, 2, 1] / 4` filter, rounded to nearest with ties up. It mixes that value with
the source channel by the requested percentage, again rounding to nearest with
ties up. Persistence then selects the maximum of the filtered current channel
and `floor(previous_output * persistence / 100)`. It applies that retention once
per admitted new completed frame, never once per screenshot or host redraw.
This is an artistic effect per completed frame, not an analog phosphor model or
a physical decay constant. At 100%, old bright values remain until history resets.

Settings changes, epoch/scene/view changes, cuts, image/drawable extent changes,
sequence gaps and invalid or discontinuous clocks reset history. Repeated input
with the same stamp returns the cached result unchanged. Changed RGB under that
same stamp clears the trail rather than returning stale pixels. Invalid shapes
and percentages fail explicitly. Source images are bounded to 8,192 pixels per
axis and 16,777,216 total pixels; retained image buffers stay within that scope.
Zero/zero selects the caller's frame without allocating RGB history.

Scene and cut resets require the caller to supply those identities. The current
standard CMake `PORT_RENDERER` callback returns only RGB/selection and cannot
announce a semantic room cut to the desktop effect. The host does not infer cuts
or reconstruction failures from pixels. A guest fallback still passes through
explicitly selected global effects, including persistence. Use zero persistence
for immediate fallback, or a custom host with explicit scene/cut stamps when
that boundary matters. A richer port metadata channel remains future work.

A CMake port can instead own `PresentationEffects` inside its renderer callback,
using its verified room identity in the stamp and invalidating the helper when
original-image reconstruction fails. Leave the stock desktop persistence off in
that arrangement to avoid applying a second trail. This supplies per-port control
without replacing the desktop host; game-specific identities remain in the port.

Results borrow storage until the next call or invalidation. Copy a result before
feeding it back to the same helper; direct aliasing is refused. Consumer inputs
must remain immutable during each call.

## Checkpoints and custom hosts

Trail buffers are host presentation state and are deliberately not serialized.
Checkpoint restore starts a fresh presentation epoch and clears the previous
trail. The first restored picture can differ from a pre-restore trail even when
the guest checkpoint is byte-identical. Fresh suffixes converge only when their
actual inputs establish it; generic immediate visual equality is not promised.

Custom desktop hosts can supply a `PresentationStamp` to `present`/`redraw` and
choose settings through `DesktopOptions` or `set_effect_settings`. Persistence
requires explicit completed-frame timing. Legacy unstamped calls retain their
existing behavior with effects off and support stateless softness; they do not
invent a guest cadence for temporal effects. Explicit stamps require a nonzero
sequence and a bounded, nonempty output extent even when effects are off. The
desktop host uses its actual drawable extent for history admission.

```cpp
pce::DesktopOptions options;
options.effect_settings = {.softness=25, .persistence=50};
pce::DesktopHost host(options);
// Caller-owned identities: use the completed image's clock, not current CPU time.
host.present(frame, {.sequence=sequence, .ticks=completed_ticks,
    .scene=scene_identity, .epoch=presentation_epoch,
    .width=frame.width, .height=frame.height});
// Paused refresh of that same source/stamp uses redraw(), not another present().
```

Enabling effects from the default off state does not reconstruct a raw image
from the scaled texture. A custom host must redraw or present its retained source
to refresh a paused image. Switching settings while effects already hold a source
can reprocess that source immediately. No runtime ABI or checkpoint format
change is introduced. New source-bound builds still require their own baseline.

The [authored example](../examples/render-effects/README.md) exercises the clock,
RGB formulas, paused sub-frame stepping, adaptive redraw and checkpoint resets
using dummy/software SDL. It is not a retail-game or physical-GPU qualification.
