# Authored widescreen consumer

Walk through the same 512-pixel room using a 240×180, 320×180, or 420×180 camera.
The 21:9 view shows 50 more columns on each side of the centered 16:9 view.
Auto mode uses the drawable's aspect at a fixed 180-pixel logical height
with a camera width between 240 and 512 pixels. Every view draws the same world
at the same logical scale. The camera
clamps to the room edges, clips the avatar, and anchors the HUD to the viewport.
The fixture generates every byte it needs from this directory.

## Build and walk

Use Python, CMake, a C++20 compiler, Ninja and an SDL3 development package.
Generate into a new directory and substitute the path to your SDL3 CMake package.

```sh
python examples/widescreen/workflow.py generate .local/wide-fixture
cmake -S examples/widescreen -B .local/wide-build -G Ninja -DCMAKE_BUILD_TYPE=Release -DPCE_EXAMPLE_GENERATED=.local/wide-fixture -DSDL3_DIR=/path/to/SDL3/lib/cmake/SDL3
cmake --build .local/wide-build
python examples/widescreen/workflow.py play .local/wide-fixture --binary .local/wide-build/pce-widescreen
```

On Windows use `pce-widescreen.exe`. Use Left and Right to walk, F11 to toggle
fullscreen and Escape to quit. Use `--view 4:3` for the smaller camera or
`--view 21:9` for the two outer landmarks. Launch with `--view auto` and
resize the window to see the adaptive camera reveal more of the room.
`--view guest` shows the authored card's original VDC output and changing
backdrop. Add `--fullscreen --shader crt-mask` for a fullscreen shader run on
a supported GPU. [Desktop presentation options](../../docs/DESKTOP_PRESENTATION.md)

## Adapt the renderer

Pass `DESKTOP PORT_RENDERER scene.cpp` to `pce_add_consumer` alongside the
port's generated module and manifest. The linked renderer implements
`pce::render_desktop_frame` from `pce/desktop_view.hpp`. It receives the
requested aspect, drawable pixel extent, completed guest image and frame sequence. Use the
side-effect-free physical `peek` to read your game's RAM and source data.
Produce a complete RGB24 frame in the reusable output buffer. Return false
to use the guest image, for example while your renderer's game state is loading.

`--port-view guest|4:3|16:9|21:9|auto` selects the callback and aspect on these builds.
Use `input.camera_width(height, minimum, maximum)` to size a square-pixel view
within your room bounds. Height and widths are logical camera pixels.
The port views default to square-pixel fit. `--display-mode` can still
override the host's scaling. The sample reads only an authored player position
and readiness flag. In a title port, decode the camera, room/scroll state,
tiles, sprites and HUD in your own renderer, using your project's data.

Build the frame from the borrowed input during the callback and release all
references when it returns. Keep gameplay and render decisions that affect
checkpoint replay in the guest's serialized state. The host calls the renderer
again on restore and when an adaptive drawable changes. Redraws during
pause preserve guest frame counters and the lifetime of pending input pulses.

## Run the TCP qualification

```sh
python examples/widescreen/workflow.py qualify .local/wide-fixture --binary .local/wide-build/pce-widescreen --out .local/wide-proof
```

The driver saves after authentic reset and runs the same bounded controls in
the guest, 4:3, 16:9, 21:9 and adaptive views. It checks both room edges,
original guest RGB, CPU, full WRAM, clocks and byte-identical ending checkpoints.
It compares overlapping world pixels at integer scales, checks the side
landmarks and HUD placement, and uses TCP window resizes while paused.
Adaptive mode matches fixed 21:9 at an 840×360 drawable and letterboxes when
the window is wider than the room.
Rendered PNGs, the original TCP journal and a JSON receipt go into the new
private output directory. Add `--gpu-driver direct3d12` or
`--gpu-driver vulkan` to repeat the restored route with every shader preset.
