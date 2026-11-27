# PC Engine peer projects reviewed

Reviewed on 26 November 2026. Repository statements describe the authors'
reported scope. Local source inspection establishes the integration decisions
below. Retail gameplay from these projects has not been qualified here.

## PCERecomp

Fabiano Gelain's toolkit at `1b9d25ab1c099a405f1b1b0a6add67889db6cc02`
has an MIT license. Its Geargrafx reference bridge has a separate GPL license.
The disc-map reader describes CD load families, bank/window assignments, entry
points and routine records. Runtime origin tracking propagates disc provenance
through RAM loads and block copies. This is useful input for future declared
overlay imports, with full byte and mapping guards retained in this toolkit.
Weak pointer guesses need to stay candidate evidence until execution confirms
them. [Disc map source](https://github.com/Fabiano-Gelain/PCERecomp/blob/1b9d25ab1c099a405f1b1b0a6add67889db6cc02/tools/recomp/pcerecomp/discmap.py)

The frame comparison script produces darkened context, highlights differences
and reports the first mismatch. This batch adapts that MIT script with bounded,
strict RGB8 PPM parsing, comment/CRLF handling and exclusive output creation.
It is usable with PPM captures from independent reference cores and consumers.
The original full license is retained. [Upstream frame comparison](https://github.com/Fabiano-Gelain/PCERecomp/blob/1b9d25ab1c099a405f1b1b0a6add67889db6cc02/tools/trace/compare_frames.py)

The BIOS-in-C validation checks are a useful design reference for independently
qualified service replacements. Importing those services requires explicit
contracts for each entry, clock/device effects, and comparison with actual
firmware. Their availability alone establishes no compatible behavior here.
[Toolkit overview](https://github.com/Fabiano-Gelain/PCERecomp/tree/1b9d25ab1c099a405f1b1b0a6add67889db6cc02)

## YsRecomp

MIT source at `7452c1b295d1298f54f96474a59a507a100ae5a1` uses PCERecomp
as a submodule. Its app layer has redraw capture, smooth fades, GPU composition,
controller configuration, timed screen-mode confirmation and multiple CRT masks.
Its Fill display mode crops and rearranges the game's panel. That mode needs
title-specific scene/window interpretation when adapted to other games.
Smooth motion similarly relies on captured scroll/sprite information.
[Presentation source](https://github.com/Fabiano-Gelain/YsRecomp/tree/7452c1b295d1298f54f96474a59a507a100ae5a1/runtime/app)

Before enabling interpolation, YsRecomp redraws a captured frame at its
original positions and compares exact pixels. Failed reconstruction selects
the original frame. This is a valuable reference gate for raster effects
and mid-frame video memory changes.

Reusable follow-ups are timed rollback for display changes, a generalized
scene discontinuity contract before interpolating motion, and configurable
shader parameters. Each should qualify checkpoint restore and menu transitions.
[Feature description](https://github.com/Fabiano-Gelain/YsRecomp/blob/7452c1b295d1298f54f96474a59a507a100ae5a1/README.md)

## Dungeon Explorer PC

Source at `6f8cf680052ba9e3d7f1019604376ddb15f4e33f` includes JavaScript
tools, C++ runtimes, and a C#/WPF interface. Its package manifest runs Node
tests. It offers a media inspection flow, per-player binding profiles and
native HuCard/CD consumer implementations. No top-level reuse license was
found in this inspected revision, so source remains a design reference.
[Project source](https://github.com/gorigamia/dungeon-explorer-pc/tree/6f8cf680052ba9e3d7f1019604376ddb15f4e33f)

The integration focus is runtime behavior, input handling and media validation.
The controller selector and CD transfer implementation deserve independent
comparison cases. Hardware differences must be resolved against reference
traces before altering the shared runtime. Its README identifies ongoing
Dungeon Explorer II input/interrupt investigation, which limits conclusions
about that route. [Reported scope](https://github.com/gorigamia/dungeon-explorer-pc/blob/6f8cf680052ba9e3d7f1019604376ddb15f4e33f/README.md)
