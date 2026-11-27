# Immutable rendering layers example

This original HuCard program writes a real VDC background tilemap, two SATB
sprites, a distinct VCE palette and PSG audio. It contains no game or firmware
data. The consumer renderer independently describes that known static scene as
immutable indexed planes and uses `pce/port_render.hpp` to compose it.

The renderer first reconstructs the original 256×240 image and checks every RGB
byte with `PresentationHistory`. It returns the original guest frame on any
mismatch. Only an exact reconstruction enables wider views and presentation-only
scenery lighting. The visible-sprite mask keeps the foreground actor unchanged;
a small reveal window demonstrates the sprite-under-background buffer.

This is an explicit authored scene, **not automatic historical VRAM recovery**.
The guest BAT is 32×32 cells. The consumer's 64×32 world repeats the same authored
tile and supplies its own coordinates for the two sprites. Extra columns are
consumer-owned extrapolation, not proof that the original guest loaded a larger
level. No spawn, collision, IRQ, sprite-budget or CPU behavior changes.

From a committed frozen SDK:

```powershell
python examples/render-layers/workflow.py generate .local/render-layers/generated
cmake -S examples/render-layers -B .local/render-layers/build -G Ninja -DCMAKE_BUILD_TYPE=Release -DPCE_EXAMPLE_GENERATED=ABSOLUTE_GENERATED_PATH -DSDL3_DIR=YOUR_SDL3_CMAKE_DIRECTORY
cmake --build .local/render-layers/build --parallel 2
python examples/render-layers/workflow.py qualify .local/render-layers/generated --binary .local/render-layers/build/pce-render-layers.exe --out .local/render-layers/proof01
```

Select the compiler explicitly if needed, just as in the toolkit's development
guide. Use a new generated/build/proof namespace for a fresh producer. This uses
the supported CMake `PORT_RENDERER` interface; it is not a Python
`project.build` audited-cache package. The private receipt binds the SDK, CMake
cache, compiler, authored sources, generated module, binary and adjacent DLLs.

Qualification forces SDL dummy video/audio and software rendering. It compares
literal expected guest RGB, complete own-producer typed checkpoints,
native/repeat/reference execution and checkpoint-restored 4:3, 16:9, 21:9 and
adaptive presentations. Paused redraws and resize must leave guest state and
checkpoint bytes unchanged. Effects use guest frame sequence, not host redraw
count. Checkpoint epochs reset temporal admission.

A separately labeled assisted case changes only a consumer marker in work RAM,
deliberately making reconstruction disagree. It must show the guest fallback,
then recover after clearing the marker. Its changed HOST/debugger accounting is
kept distinct; it is never normalized into an unassisted checkpoint comparison.

This proves bounded authored scene behavior. It does not certify retail games,
hardware timing, physical audio, real GPU presentation or arbitrary mid-line
palette histories. Per-row palettes supplied to the helpers must be row-stable;
when a port cannot reconstruct the original exactly it should preserve fallback.
