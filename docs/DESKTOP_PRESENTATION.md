# Desktop presentation and shaders

Build your consumer with SDL enabled and choose presentation options at launch.
Use the same flags on `launch-plan` to inspect the arguments for a launcher or
TCP driver. [Consumer build guide](CONSUMER.md)

```powershell
python -m pcerecomp.project run .local/my-port/project.toml --build-dir .local/my-port/build --receipt .local/my-port/video-run.json --display-mode square --window-scale 3 --fullscreen on --display-shader sharp
```

| Option | Behavior |
| --- | --- |
| `--display-mode integer` | Keep square pixels and use the largest whole-number scale that fits. Fall back to fractional fit for small windows. This is the default. |
| `--display-mode square` | Fill as much of the drawable as possible while keeping square pixels. Useful for arbitrary window sizes, fullscreen and native wide frames. |
| `--display-mode 4:3` | Stretch the full frame into a centered 4:3 viewport. |
| `--display-mode 16:9` | Stretch the full frame into a centered 16:9 viewport. |
| `--window-scale 1..6` | Set the starting window size relative to the 256×240 reference size. |
| `--fullscreen on\|off` | Choose startup fullscreen. F11 toggles fullscreen while the window has focus. |
| `--display-filter nearest\|linear` | Choose sharp texel edges or conventional bilinear sampling with the shader off. |
| `--display-shader off\|sharp\|crt\|smooth\|lcd` | Choose the normal SDL renderer, crisp fractional scaling, CRT scanlines, eased transitions, or a subtle LCD pixel grid. The presets use their own sampling. |

SDL uses the drawable's pixel dimensions, including the current high-DPI scale.
Changing the output size or display mode affects the final picture only. Guest
rendering, scanline clocks and checkpoint data continue through the same
reference path. TCP `screenshot` with source `guest` returns that completed
guest frame. Source `present` returns the SDL output with scaling and effects
within the development server's screenshot size limit.

## True widescreen in a consumer port

A port can supply a wider RGB frame through `pce::DesktopHost::present()`.
Use `DisplayMode::square` to fit that frame with square pixels across window
sizes. The SDL adapter accepts a frame up to 16,777,216 pixels with at most
8,192 pixels along either axis. The guard also checks the exact RGB byte count.
The standard PC Engine VDC path supplies the original frame.

Ports using the toolkit's desktop consumer host can link a renderer with
`pce_add_consumer(... DESKTOP PORT_RENDERER scene.cpp)`. That adds
`--port-view guest|4:3|16:9` to the executable. The two port modes request a
new frame from the renderer and default to square-pixel fit. The callback
gets the completed guest frame, frame sequence and read-only physical memory
inspection. It can defer to the guest frame on any call. A TCP restore redraws
the view from the restored state. [Authored widescreen consumer](../examples/widescreen/README.md)

For a port such as Ys III, the camera and world renderer determine what appears
beyond the original frame. The game must decide how to load and draw the extra
tiles and sprites, place the HUD, and handle edges of rooms and scripted
scenes. The 16:9 display mode stretches the existing view. A native wider
renderer should supply the added content and use square-pixel fit.

## Shader source and backend

The presets require SDL 3.4 or newer with Direct3D 12 or Vulkan available.
The normal display modes also work with the SDL 3.2 build. A requested shader
reports an error if its GPU device fails to start. The plain SDL path is
available with `--display-shader off`.

The original HLSL source builds into the checked-in SPIR-V and DXIL header.
Consumers can tune or extend that pass in their source SDK. Standard consumer
builds use the embedded header and require no shader compiler. Regenerate or
verify the header with the DirectX Shader Compiler. The embedded outputs were
generated with DXC 1.8.0.5123 (3f85295cf).

```
python scripts/build_display_shader.py
python scripts/build_display_shader.py --check
```

The fragment shader takes SDL's completed frame as texture slot 0 and a
16-byte uniform block in slot 0. `sharp` keeps the center of each texel crisp
and limits bilinear blending to the edges at fractional scales. `crt` adds
scanlines and a shallow vignette and fades the scanlines at small scales.
`smooth` eases between neighboring texels over a wider interval.
`lcd` shades the pixel boundaries in both directions and fades the grid
at small scales. Every preset leaves the guest screenshot and clock path intact.
[SDL custom GPU state](https://wiki.libsdl.org/SDL3/SDL_SetGPURenderState) ·
[SDL resource bindings](https://wiki.libsdl.org/SDL3/SDL_CreateGPUShader)
