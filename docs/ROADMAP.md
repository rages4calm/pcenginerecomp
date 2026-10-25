# Roadmap and acceptance criteria

The target is a complete, contributor-friendly recompilation ecosystem.
These are ordered dependencies, not delivery dates. A planned feature is
not an available capability. Broader platform coverage must not postpone
finishing the base PC Engine/CD correctness path.

| Stage | Deliverable | Acceptance gate | Status |
|---|---|---|---|
| 0 | Media → snapshot → decoder/CFG → direct C++ → bounded CPU sandbox | Synthetic semantics and a real local image reach compiled native execution with explicit limits | Implemented foundation |
| 1 | Complete HuC6280 interpreter and independent reference adapter | All supported encodings, addressing modes, flags and boundary cases have independent evidence; unsupported slots remain explicit | 234 opcode encodings implemented; 22 reserved slots trap; bus/reference gaps stay explicit |
| 2 | Complete native lowering and multi-context analysis | Differential runs cover all implemented semantics, indirect flow, T/decimal modes, TAM/TMA and self-modification | Direct lowering, source guards and observed multi-context/byte-variant modules implemented; general multi-context CFG recovery remains |
| 3 | Cycle/event scheduler, timer/IRQ and actual memory map | Speed-change phases, bus waits, IRQ entry/return, mirrors and device ordering match reference traces | Aggregate clocks, raster, timer/IRQ implemented; base WRAM mirrors implemented; bus phases and hardware qualification remain |
| 4 | HuCard loader, System Card and CD transport | Authentic loader path, command/sector timing, overlay loads, failures and identity checks | Base HuCard cartridge/vector startup and Standard/Super firmware boot, TOC, read-only ISO/CHD/bounded BIN-CUE providers and audio timelines implemented with bounded checks; enhanced mappers, broader commands and hardware reset/bus timing remain |
| 5 | Reference video/audio/input/persistence | Correct frames and sound for diagnostic software and bounded real-title routes; isolated BRAM save/load | Continuous rendering, input, volatile BRAM and decoded/mixed digital audio implemented with bounded reference checks; host persistence and broader hardware qualification remain |
| 6 | First Ys III playable vertical slice | Cold boot, title, new game, field movement, scene transitions, sound and saves, with documented native/interpreted work | Separate cold-boot-to-opening and conditional movement/combat/progression tests demonstrated with audio; one unified native cold-boot/gameplay route, persistence and full native execution remain |
| 7 | Overlay capture/compile/cache and optimizations | Bounded capture, reproducible modules, stale-cache rejection, parity and measured performance | Retired-code capture, partitioned native emission, exact-key dispatch, shared module objects and pinned consumer builds implemented; persistent module cache and multi-instruction blocks remain |
| 8 | Desktop/player and mod ecosystem | Reproducible packages, input picker/remapping, settings, accessibility and guarded extensions | Optional SDL/TCP development hosts implemented; player configuration, packages and ecosystem remain |
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
   reference. Extend independent evidence to remaining CPU semantics,
   source edge/bus phases and cycle/event traces. Existing CPU, block-transfer
   and IRQ/RTI state checks retain their separately documented scope.
2. **CPU and device coverage.** The implemented CPU families are listed in
   [CPU_SEMANTICS.md](CPU_SEMANTICS.md). CPU interrupt entry/RTI, block
   transfers, controller I/O, VDC/raster/DMA and continuous video now have
   bounded verification. ABI 16 adds independently checked BRK, base WRAM
   mirrors and sprite collision/overflow events. CD control, TOC, read-only sector streaming and
   CDDA/ADPCM timelines support conditional private gameplay tests. Continue
   with remaining CD command/sense/subcode behavior, additional firmware/media
   profiles and device timing. ABI 17 implements explicit Standard/Super memory
   profiles and reset-vector firmware startup; warm reset and electrical
   power-on details remain separate. The unknown-command diagnostics
   identify repeatable command sources without implementing their semantics.
   HuCard loading and mapper profiles need their own authored and real-software
   qualification. Base HuCard startup, explicit SF2 banking and Populous RAM
   are now implemented. Optional Arcade Card Duo port/RAM hardware is also
   implemented on Super System Card profiles, with authored and independent
   device checks. Pro, SuperGrafx, further boards and persistent RAM remain
   separate work. Two-bit background
   decoding and digital monochrome also have exhaustive authored and isolated
   MesenCE function/filter checks; full fetch/bus timing remains open.
   Extend decoded/mixed audio evidence separately.
   Volatile guest SAVE/LOAD is exercised;
   persistent host saves and state restore remain separate work. Resolve the
   unknown-command reference profile rather than treating it as hardware
   qualification. Avoid BIOS stubs or fabricated status events.
3. **Bus phases and scheduler.** Instruction retirement advances raster and CD time
   in both execution tiers. Replace the documented instruction-entry access
   approximation with explicit bus/event ordering, then extend qualified RAM/device profiles and
   remaining I/O and timer scheduling. Preserve code-write/bank-change guards
   before optimizing native blocks.
4. **Media edge cases.** Add independently constructed CUE/multitrack
   fixtures and clarify IPL addressing variants. Keep extraction bounded and
   retain the original image byte-for-byte.
5. **Capture inspection and trace coverage.** Paused, bounded read-only TCP
   summaries and retired source-span pages are implemented, including exact
   native/interpreted counts, completeness/loss and deferred-window metadata.
   They preserve guest state and the final capture contract. Future
   chronological or bus-access traces require separate bounded storage and
   semantics; the current accumulated identity set is not such a trace.

The first playable release needs a clearly scoped qualification record. It
does not need every enhancement, but must accurately report what executes
natively, which fallback paths remain, and which gameplay/save routes were
actually tested.
