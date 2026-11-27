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
| `--display-shader off\|sharp\|crt\|smooth\|lcd\|mono\|crt-mask` | Choose the normal SDL renderer, crisp fractional scaling, CRT scanlines, eased transitions, an LCD grid, monochrome, or a CRT phosphor mask. The presets use their own sampling. |

SDL uses the drawable's pixel dimensions, including the current high-DPI scale.
Changing the output size or display mode affects the final picture only. Guest
rendering, scanline clocks and checkpoint data continue through the same
reference path. TCP `screenshot` with source `guest` returns that completed
guest frame. Source `present` returns the SDL output with scaling and effects
within the development server's screenshot size limit.
Capture composes the viewport at the drawable's current size, including when
the window is hidden or its swapchain is between sizes.

## Confirm display changes

F11 previews borderless fullscreen with a ten-second confirmation. Enter keeps
the change. Escape, F11 again, focus loss or expiry restores the previous
settings. The timer runs from host wall time in `poll()`, including while the
guest is paused. The window title shows the confirmation prompt. A frozen host
or failed graphics driver can prevent the timer from running.

Launchers can use `DesktopHost::preview_display(settings, timeout_ms)`, then
`confirm_display()` or `cancel_display()`. The transaction covers window size,
borderless fullscreen, display mode and sampling filter. Dimensions describe
the retained windowed size, including while fullscreen. It does not recreate
the GPU device or change shader presets. Startup flags remain explicit immediate
choices. No settings are silently written to disk. Pending changes reject a
second preview and ordinary TCP resizes.

TCP drivers can use `DevClient.preview_display(512, 384, mode='square')`,
`display_settings()`, `confirm_display()` and `cancel_display()`. Changes require
a settled remote pause. See [development commands](DEV_SERVER.md).

## Configurable shader parameters

Use `--shader-scanline`, `--shader-mask`, `--shader-grid` and `--shader-vignette`
with percentage values from 0 to 100. Defaults are 24, 22, 26 and 8.
Each control affects presets that use that effect. `--shader-brightness` and
`--shader-saturation` take 0 to 200, default 100. Zero brightness produces black;
zero saturation produces grayscale. Controls apply only with a shader preset.
`DesktopOptions::shader_parameters` and `DesktopHost::set_shader_parameters()`
expose the same validated percentages without creating another GPU device.
Consumer `presentation` dictionaries accept the six names without the prefix.

`--input-profile FILE` selects validated bindings for up to five guest ports.
[Input profiles](DESKTOP_INPUT.md)

## True widescreen in a consumer port

A port can supply a wider RGB frame through `pce::DesktopHost::present()`.
Use `DisplayMode::square` to fit that frame with square pixels across window
sizes. The SDL adapter accepts a frame up to 16,777,216 pixels with at most
8,192 pixels along either axis. The guard also checks the exact RGB byte count.
The standard PC Engine VDC path supplies the original frame.

Ports using the toolkit's desktop consumer host can link a renderer with
`pce_add_consumer(... DESKTOP PORT_RENDERER scene.cpp)`. That adds
`--port-view guest|4:3|16:9|21:9|auto` to the executable. The port modes request a
new frame from the renderer and default to square-pixel fit. The callback
gets the completed guest frame, frame sequence, drawable pixel extent and
read-only physical memory inspection. Its `camera_width` helper uses a fixed
logical height and caller-supplied width bounds. Auto mode derives this width
from the actual drawable and refreshes it on resize, including while paused.
The callback can defer to the guest frame on any call. A TCP restore redraws
the view from the restored state. [Authored widescreen consumer](../examples/widescreen/README.md)

For a port such as Ys III, the camera and world renderer determine what appears
beyond the original frame. The game must decide how to load and draw the extra
tiles and sprites, place the HUD, and handle edges of rooms and scripted
scenes. The 16:9 display mode stretches the existing view. A native wider
renderer should supply the added content and use square-pixel fit.

## Shader source and backend

Optional [software softness and persistence](PRESENTATION_EFFECTS.md) run before
the existing presentation pass and also work with the shader off. They use
completed-frame timing, preserve guest captures and reset temporal history on
checkpoint epochs. They are separate from the unchanged GPU shader presets.

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
48-byte uniform block in slot 0. `sharp` keeps the center of each texel crisp
and limits bilinear blending to the edges at fractional scales. `crt` adds
scanlines and a shallow vignette and fades the scanlines at small scales.
`smooth` eases between neighboring texels over a wider interval.
`lcd` shades the pixel boundaries in both directions and fades the grid
at small scales. `mono` converts the result to luminance. `crt-mask` adds an
RGB phosphor triad across the drawable columns over CRT scanlines. Presets
operate in the presentation pass after guest rendering.
[SDL custom GPU state](https://wiki.libsdl.org/SDL3/SDL_SetGPURenderState) ·
[SDL resource bindings](https://wiki.libsdl.org/SDL3/SDL_CreateGPUShader)
