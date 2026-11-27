# Completed-frame timing and software display effects

This authored example reuses the [render-layers HuCard fixture](../render-layers/README.md)
and its directly translated native module. It does not include game or firmware
data. The consumer callback independently reconstructs the original background
and sprites before selecting a diagnostic swatch image. These swatches are
explicit consumer graphics, not recovered offscreen scenery or a game port.

The callback uses `DesktopFrameInput.completed_ticks` for `PresentationHistory`.
`guest_ticks` remains the current CPU snapshot time. A partial-frame instruction
can advance CPU time without completing a new frame; the image's time and effect
phase must stay fixed. The swatch phase uses only the completed guest sequence.

`--display-softness 50 --display-persistence 50` applies host-only horizontal
softening and persistence. The fixture cycles red240, green160, blue80 and black
swatches over four completed frames. The Python workflow calculates every output
byte independently using the documented integer formulas. It bounds unknown
earlier history by zero and255, proves its disappearance, and explicitly checks
the chosen three-frame suffix converges before claiming equal presented images.
Persistence is an artistic frame-domain effect, not analog hardware simulation.

From a committed frozen SDK:

```powershell
python examples/render-effects/workflow.py generate .local/render-effects/generated
cmake -S examples/render-effects -B .local/render-effects/build -G Ninja -DCMAKE_BUILD_TYPE=Release -DPCE_EXAMPLE_GENERATED=ABSOLUTE_GENERATED_PATH -DSDL3_DIR=YOUR_SDL3_CMAKE_DIRECTORY
cmake --build .local/render-effects/build --parallel 2
python examples/render-effects/workflow.py qualify .local/render-effects/generated --binary .local/render-effects/build/pce-render-effects.exe --out .local/render-effects/proof01
```

Set your compiler explicitly when needed. Every new attempt uses new generated,
build and proof namespaces. This is a supported CMake `PORT_RENDERER` producer,
not a Python audited-cache build. The private receipt binds toolkit source,
compiler, CMake cache, generated module, example dependencies, executable and DLLs.

Qualification forces SDL dummy video/audio and software rendering:

- Native, repeat and interpreter reference follow identical finite routes;
  another native run uses pristine0/0 effects. Digital guest RGB, RAM, PCM and
  complete typed HOST/CORE states are compared, with exactly four permitted tier
  counters projected only for native/reference comparison.
- Each route stops after a genuine single wait-loop instruction without a new
  frame. Repeated captures and an adaptive wider resize retain completed-frame
  time and leave complete guest checkpoint bytes unchanged.
- Independent fresh hosts restore their own source checkpoint. Their initial
  presented image intentionally loses transient effect history. This is an
  expected host-only reset, never described as an identical restored picture.
  A separately calculated suffix then checks deterministic visual convergence
  and byte-identical complete ending checkpoints.

No GPU device, physical audio, live installation or retail route is exercised.
The main [render-layers example](../render-layers/README.md) separately qualifies
its wider authored scenery, masks and underlays. Game projects own world recovery,
cameras, actor spawning, HUD and gameplay changes.
