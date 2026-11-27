# Reconstruction and presentation continuity

`pce/presentation_history.hpp` supplies an optional host-only gate for ports
that reconstruct guest scenes before adding smooth motion. It follows the
useful reconstruction check in [YsRecomp](https://github.com/Fabiano-Gelain/YsRecomp/blob/7452c1b295d1298f54f96474a59a507a100ae5a1/runtime/app/redraw.c)
with an independently written, game-independent interface.

The port draws a reference image at the original positions and original guest
resolution. `PresentationHistory::observe` compares its exact RGB bytes and
geometry against the completed guest image. A missing, malformed or different
reconstruction selects the original guest image and clears temporal history.
An invalid original image or invalid presentation extent throws `pce::Fault`.
All images are bounded to 8,192 pixels per axis and 16,777,216 total pixels.

```cpp
#include "pce/presentation_history.hpp"

// Host/port ownership. Choose this bound from the port's completed-frame clock
// contract, not from monitor refresh. Retain the object between frame calls.
pce::PresentationHistory history(maximum_guest_ticks_between_frames);

auto result = history.observe(guest, reconstructed, {
    .sequence = completed_frame_sequence,
    .ticks = guest_master_ticks,
    .scene = opaque_scene_identity,
    .epoch = host_presentation_epoch,
    .width = drawable_width,
    .height = drawable_height,
    .cut = scene_transition,
});
// result.frame is a borrowed original or exact reconstruction.
// Only result.interpolation permits this frame's continuous motion pair.
```

The first exact frame warms history. A later pair permits interpolation only
when both reconstructions are exact, frame sequences are consecutive, guest
ticks strictly increase within the caller's bound, scene and epoch agree, and
the original and presentation extents are unchanged. An explicit scene cut
blocks that pair. Repeated exact paused redraws neither enable interpolation
nor consume history. The helper stores only the previous stamp and dimensions.
It does not retain RGB buffers or infer actor identities, motion, scenes or
game addresses. The returned frame reference cannot outlive its input frame.

Advance the supplied host epoch or call `history.invalidate()` after loading a
checkpoint, rewinding, editing state or switching presentation content outside
normal frame publication. This is required even when a restored frame has the
same sequence, ticks and pixels as a previously observed one. The first exact
post-reset frame warms history again. This helper is not serialized into guest
checkpoints and changes neither guest simulation cadence nor runtime ABI.

Existing wide renderers remain opt-in and unchanged. A wide image is not an
original-resolution reconstruction. Use the reference reconstruction to
qualify the scene before rendering an enhanced image; comparing a wide image
directly against the guest frame fails the gate. Scene metadata and any actual
interpolation renderer or high-refresh schedule still belong to the port.

The authored C++ test exercises byte mismatches, malformed images, bounds,
scene changes, cuts, resize, missing frames, clock gaps, paused redraws and
checkpoint invalidation without SDL, a window or a GPU.

Toolkit consumer callbacks receive `input.guest_ticks` and
`input.presentation_epoch`. The host advances the epoch after checkpoint import
and successful changed-byte debugger RAM/CPU edits. Set the stamp's `view` from
the requested port view, so switching views breaks a pair even at the same size.
Custom hosts own this invalidation themselves. An edit need not redraw the
current paused image immediately; the next callback observes the new epoch.
