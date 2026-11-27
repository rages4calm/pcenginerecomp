# Immutable scene layers for port rendering

`pce/port_render.hpp` supplies host-only scene composition and tilemap sampling.
These original implementations use the useful interfaces in
[RondoRecomp](https://github.com/gminustwo/RondoRecomp/blob/a4f254542e3e85244c229e3e12643f85ee9e162b/runtime/pce/video.h)
as a reference. No upstream implementation or game data is included.

Ports supply immutable scene data and qualify an original-size reconstruction
against completed guest RGB before enhancing it. The helpers perform no guest
memory reads, device clocks, collision checks, interrupts or state writes.
ABI 29 and checkpoint encodings are unchanged.

## Composition and masks

`compose_port_layers(PortLayerInput)` accepts complete BG/sprite index planes,
or empty planes for backdrop/no sprites. BG indices are zero or 1..255 with a
nonzero low color nibble. Sprite indices are zero or 257..511 with a nonzero low
nibble. The port first resolves sprite ordering into one candidate per pixel.
A zero/one priority flag accompanies every sprite-plane pixel; behind-BG sprites
remain visible through transparent BG zero.

Supply one complete 512-color GRB9 palette, or one palette per row. Controls are
empty for standard RGB, one VCE control byte, or one per row. The explicit
backdrop index defaults to zero; a caller can select 256 for a known burst scene.
The helper does not infer display mode or recover palette history.

The returned `PortLayerFrame` owns its buffers:

| Field | Contents |
| --- | --- |
| `image` | Composited RGB. |
| `sprite_visible` | One byte per pixel: candidate sprite visibility. |
| `background` | BG alone, including the selected backdrop. |
| `behind_background` | Candidate sprite RGB where opaque BG hides it; BG otherwise. |

These buffers support scenery lighting that preserves actors, or revealing a
known underlay while moving scenery. Hardware sprite limits, collisions and
gameplay visibility remain unchanged.

## Wider tilemaps

`sample_port_tilemap(PortTilemapView, PortViewport)` returns BG indices from an
explicit host tilemap. Cells choose a decoded 8×8 four-bit tile, palette and
optional X/Y mirroring. Mirroring is a host enhancement, not a claim that PCE BG
hardware flips tiles. Inputs are decoded host data, not packed BAT or live VRAM.

Signed X/Y origins and optional per-output-row scroll offsets support wider
views and raster bands. Offsets are added to the origin, not substituted for it.
Choose wrap or clip explicitly; negative origins use mathematical wrapping.
An optional half-open output clip rectangle limits sampling; other pixels receive
the supplied outside index. Ports own room limits, streaming, actors and cameras.

Outputs are bounded to 8,192 pixels per axis and 16 million total pixels. Maps
are bounded to 1,024 cells per axis/one million cells; up to 65,536 complete 8×8
tiles are allowed. Invalid shapes, indices and colors fail explicitly. All source
spans must remain immutable for the call.

## Reconstruction, timing and checkpoints

Use [PresentationHistory](PRESENTATION_HISTORY.md) to compare the original-size
reconstruction before selecting an enhanced frame. Supply guest sequence/ticks,
scene identity, presentation epoch, view and drawable geometry. Preserve guest
fallback on mismatch. Effects should use guest sequence/ticks, so paused redraws
and resizing do not advance their animation.

Guest output retains composite RGB and line indices, not complete separate-layer
history. Current RAM/VRAM cannot establish what earlier dots looked like. Per-row
palettes only describe row-stable data; mid-line writes need a more precise source
or fallback. Consumer snapshots/temporal buffers must be invalidated or rebuilt
after checkpoint epoch changes. No helper metadata is added to guest checkpoints.

The [authored CMake example](../examples/render-layers/README.md) programs real
BG/SATB, checks exact original RGB, then demonstrates wider sampling, masks and
underlays. Its wider repeated pattern is authored extrapolation, not recovered
offscreen game data. It uses CMake `PORT_RENDERER`; Python consumer descriptors
do not yet declare renderer source graphs.
