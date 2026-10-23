# Optional desktop presentation host

The SDL3 desktop executable uses the same bounded sandbox setup, interpreter /
generated-module dispatch, guest master clock and isolated volatile state as
the headless runner. SDL is optional; a default build and all non-desktop tests
have no SDL dependency. No settings, owner installation, saves or BRAM files
are read or written by the host.

## Presentation and cadence

`DesktopHost` accepts completed RGB frames. It does not render guest memory,
advance guest clocks, relatch a controller or mutate CPU/device state.
The caller owns simulation and decides when to publish completed frames.
The streaming RGB24 texture uses nearest-neighbor pixels and a black integer
letterbox. A window smaller than the guest frame uses a nearest-neighbor fit
instead of cropping. Geometry changes replace the texture. Resize/expose events
redraw the retained frame while paused. This currently displays square pixels;
there is no analog pixel-aspect, CRT filter, interpolation or widescreen mode.

VSync is explicitly disabled. Normal pacing converts elapsed guest master ticks
at 21,477,273 Hz to a monotonic SDL wall-clock deadline. Waiting changes only
host time. An unthrottled run disables that wait; neither mode changes emulated
cycles or disc/audio event deadlines. The host cannot make a slow simulation
run in real time. After a host stall greater than 250 ms the anchor resets,
preventing an extended catch-up burst. Pause/resume also resets the anchor.
Presentation and input run on the main thread; no unsynchronized GPU or guest
worker is introduced.

## Controls

| Action | Keyboard | First available SDL gamepad |
|---|---|---|
| I / II | Z / X | South / East |
| Select / Run | Either Shift / Enter | Back / Start |
| Directions | Arrow keys or keypad 8 / 6 / 2 / 4 | D-pad or left stick |
| III / IV / V / VI | A / S / D / F | West / North / Left shoulder / Right shoulder |
| Pause / resume | Space | Keyboard only |
| Fullscreen | F11 | Keyboard only |
| Quit | Escape or window close | Keyboard only |

The guest must be configured for a six-button controller to observe its extra
buttons. Keypad direction aliases use physical SDL scancodes, independent of
Num Lock. Left-stick thresholds are strictly outside -16,000 / +16,000. Keyboard
and gamepad masks combine; simultaneous opposing directions remain explicit.
Host changes pass through `Joypad::set_pressed` in the caller. The guest port
still samples only on its own writes. Scripted input can combine with the live
mask without replacing this protocol. Only controller slot zero has a live
host mapping in this batch; other slots retain their explicit/scripted state.

Fresh keyboard and recognized-gamepad button-down events also create a bounded
host pulse. A down/up pair drained in the same event poll therefore remains
visible to the guest. Each button pulse expires after two completed guest-frame
presentations: the first boundary may finish a partial frame, and the second
finishes one complete intervening frame. This normally holds a short tap for
about 16.7–33.4 ms of guest time. A long instruction that skips multiple frame
publications can extend that interval; it does not change guest I/O sampling.
Held buttons continue through their live state, without a new pulse on release
or keyboard repeat. Resize/expose redraws and readbacks do not consume pulses.
Stick axes use their live state and are not stretched. Focus loss and pause
clear all pending pulses; disconnect clears the gamepad's pending pulses.
This is a desktop input policy, not a change to the reference joypad protocol
or deterministic input-script timing.
Diagnostics count keyboard events, recognized gamepad button events and newly
created input pulses. An unmapped fresh key-down also records its SDL scancode
and a counter, excluding the three host controls Space, F11 and Escape. Repeat
and release events do not increment that counter. This distinguishes an
unsupported host key from a mapped tap without changing guest button mappings.

Gamepads are opened at startup or on SDL hotplug and reselected after removal.
Focus loss releases keyboard state and gates all live controller input; return
of focus does not resurrect stale keyboard keys. A connected gamepad resumes
its current held state. Pausing gates the mask and suspends simulation in the
caller. No global hotkeys or background input capture are installed.

## Output and evidence

`readback()` redraws the current SDL texture and reads the actual renderer
target before presentation, as required by SDL. It includes the window's black
bars, rather than returning the original guest RGB buffer. Captures are capped
at 4,194,304 pixels. `capture()` writes a new PPM using exclusive creation;
an existing file is refused even if it appeared after command-line validation.
No automatic screenshots, recordings or growing history are retained.

A renderer-target readback establishes upload, scaling and readback behavior.
It does not establish how the operating-system compositor displayed a window.
Dummy/software tests are also distinct from a visible real-window run, and
neither establishes guest frame accuracy against an independent emulator.

The authored desktop test covers exact RGB uploads/nearest pixel boundaries,
black bars, changing frame geometry, resized and paused/exposed targets,
small-window fit, fullscreen toggling/repeat, all twelve key and virtual
gamepad button mappings, stick deadzone boundaries, focus release, disconnect,
combined input, pause/repeat/resume, quit paths, exclusive capture and the
master-clock wait/reset. Same-poll short taps survive two frame boundaries;
focus recovery, pause/resume and disconnect do not resurrect stale pulses.
The virtual controller is created in the test process;
this is not physical-controller qualification. Run it with SDL's dummy video
and software renderer in CI. The default headless reference route is preserved.

## Dependency and API sources

The tested Windows x64 SDK is SDL **3.4.18**. Its official MinGW development
archive SHA256 is
`cd98158c8d025a816f430a600b4e9526524e6219ee884ec72bd498b80fd3bf58`.
SDL is zlib-licensed and is not vendored in the source repository. Supply an
installed SDK through `SDL3_DIR` when enabling `PCE_BUILD_DESKTOP`; keep the
matching runtime library beside the executable. CMake deploys the shared DLL
on Windows for the desktop executable and its test target.

API syntax was checked using the SDL wiki through Context7 and official SDL3
documentation. The implementation is original project code. Relevant primary
contracts are [streaming texture uploads](https://wiki.libsdl.org/SDL3/SDL_UpdateTexture),
[logical presentation](https://wiki.libsdl.org/SDL3/SDL_SetRenderLogicalPresentation),
[VSync defaults](https://wiki.libsdl.org/SDL3/SDL_SetRenderVSync),
[readback timing and viewport](https://wiki.libsdl.org/SDL3/SDL_RenderReadPixels),
[gamepad enumeration](https://wiki.libsdl.org/SDL3/SDL_GetGamepads),
[virtual devices](https://wiki.libsdl.org/SDL3/SDL_AttachVirtualJoystick) and
[nanosecond waits](https://wiki.libsdl.org/SDL3/SDL_DelayNS).

Host GPU handles, native window IDs, key arrays, connection handles, wall-clock
anchors and presentation counters are disposable host state. They must not be
serialized as guest state. No save-state format or compatibility promise is
introduced by this host.
