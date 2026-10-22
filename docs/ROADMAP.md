# Roadmap and acceptance criteria

The target is a complete, contributor-friendly recompilation ecosystem.
These are ordered dependencies, not delivery dates. A planned feature is
not an available capability. Broader platform coverage must not postpone
finishing the base PC Engine/CD correctness path.

| Stage | Deliverable | Acceptance gate | Status |
|---|---|---|---|
| 0 | Media → snapshot → decoder/CFG → direct C++ → bounded CPU sandbox | Synthetic semantics and a real local image reach compiled native execution with explicit limits | Implemented foundation |
| 1 | Complete HuC6280 interpreter and independent reference adapter | All supported encodings, addressing modes, flags and boundary cases have independent evidence; unsupported slots remain explicit | Next |
| 2 | Complete native lowering and multi-context analysis | Differential runs cover all implemented semantics, indirect flow, T/decimal modes, TAM/TMA and self-modification | Planned |
| 3 | Cycle/event scheduler, timer/IRQ and actual memory map | Speed-change phases, bus waits, IRQ entry/return, mirrors and device ordering match reference traces | Planned |
| 4 | HuCard loader, System Card and CD transport | Authentic loader path, command/sector timing, overlay loads, failures and identity checks | Planned |
| 5 | Reference video/audio/input/persistence | Correct frames and sound for diagnostic software and bounded real-title routes; isolated BRAM save/load | Planned |
| 6 | First Ys III playable vertical slice | Cold boot, title, new game, field movement, scene transitions, sound and saves, with documented native/interpreted work | Planned |
| 7 | Overlay capture/compile/cache and optimizations | Bounded capture, reproducible modules, stale-cache rejection, parity and measured performance | Planned |
| 8 | Desktop/player and mod ecosystem | Reproducible packages, input picker/remapping, settings, accessibility and guarded extensions | Planned |
| 9 | Enhanced presentation and game-specific features | Each feature meets its own reference, state and gameplay gate below | Planned |
| 10 | Additional hardware and broad library qualification | Separate profiles, dedicated fixtures, real software routes and compatibility reporting | Planned |

## Full feature target

| Feature | Framework responsibility | Game-specific or qualification work |
|---|---|---|
| Native Windows/Linux/macOS, x64/ARM64 | Portable generated code, CMake, reproducible packages, host backend | Actual builds and runtime checks on each target; no ARM64 claim from x64 tests |
| HuCard, CD-ROM², Super CD-ROM² | Input identity, mappers, System Card and RAM profiles | Title/revision/patch recipes and loader behavior |
| CHD and BIN/CUE, ISO | Shared TOC and bounded sector provider, CDDA, subcode policy | Disc layouts, pregap/index behavior and multitrack fixtures |
| SuperGrafx and Arcade Card | Additional VDC/priority/RAM/device profiles | Dedicated titles and hardware-specific parity routes |
| Fast startup and loading | Immutable data caching, asynchronous host I/O, native overlay cache | Preserve observable CD timing unless an explicit compatible speed mod is enabled |
| Overlay compilation | Content/mapping/ABI-keyed modules and safe invalidation | Discover real entry points; retain fallback for genuinely dynamic code |
| Enhanced renderer | Software reference, GPU backend, scaling, palette/aspect controls | Software/GPU parity, raster effects, render-thread ownership |
| Widescreen and ultrawide | Expanded presentation and hooks | Camera/world streaming, sprite culling, HUD/menu layout, scene limits |
| High refresh / interpolation | Separate guest cadence and host presentation | Object/camera matching and discontinuity handling; intentional logic-rate mods separately tested |
| Texture/tile/sprite replacements | Content hashes, packs, resource budgets and renderer hooks | Safe replacement identity, asset permission and scene coverage |
| Audio improvements | PSG/ADPCM/CDDA fidelity, mixer, latency and optional replacement audio packs | Track maps, loops, fades, seek behavior and A/V synchronization |
| Controllers / multitap | Keyboard/gamepad remapping, hotplug, two/six-button and multitap protocol | Per-title button/protocol policy and multiplayer support |
| Saves / states / rewind | Isolated atomic BRAM, versioned snapshots, bounded history | Identity/ABI/mod compatibility and device-state reconstruction |
| Local co-op / rollback netplay | Input routing, deterministic states, session compatibility | Title-specific player logic/camera, ownership and desync diagnosis |
| Mods / patch packages | IDs, revision guards, expected-byte writes, dependency/conflict checks | Reference-preserving title hooks, patch ownership and compatibility |
| Localization | Text/font/tile replacement infrastructure and pack selection | Translation rights, encoding/font coverage, layout and story review |
| Achievements / accessibility | Event hooks, remapping, readable settings and user opt-ins | Stable game events; external API policy and per-title tests |
| Debugger / profiling | Bank-aware disassembly, breakpoints, bounded tracing, native/fallback counters | Independent trace adapters, useful symbolic maps and real routes |
| Project generation | Input/profile validation, build recipes, diagnostics and contributor scaffold | Reviewed title-specific annotations and asset handling |

## Immediate contributor batches

1. **Reference adapter and CPU vectors.** Define a compact code-free trace
   metadata format and an adapter for a separately supplied Mesen/Beetle
   reference. Extend independent evidence to the remaining read/modify/write,
   bit, block-transfer and interrupt semantics and cycle/event traces.
2. **Further CPU coverage.** RMB/SMB and push/pop families are implemented
   and checked against Geargrafx. Load/store and logical/arithmetic/comparison
   addressing, T and decimal semantics are implemented. Continue with
   shifts/rotates, INC/DEC, indirect JMP, bit branches and BIT/TSB/TRB/TST. The local Ys III route then
   needs real System Card execution; avoid inventing BIOS stubs to reach a
   screenshot.
3. **Actual bus and scheduler.** Specify RAM mirrors, I/O dispatch and device
   event ordering. Cover a code write during a native block and a bank change
   between instructions before optimizing guards.
4. **Media edge cases.** Add independently constructed CUE/multitrack
   fixtures and clarify IPL addressing variants. Keep extraction bounded and
   retain the original image byte-for-byte.

The first playable release needs a clearly scoped qualification record. It
does not need every enhancement, but must accurately report what executes
natively, which fallback paths remain, and which gameplay/save routes were
actually tested.
