# Documentation

[Project overview](../README.md) · [Current status](STATUS.md) · [Contributing](../CONTRIBUTING.md)

## Start a port

| Guide | Use it for |
| --- | --- |
| [Development setup](DEVELOPMENT.md) | Build the toolkit and configure optional dependencies. |
| [Authored native workflow](../examples/native-workflow/README.md) | Try capture, preparation, native compilation and qualification without game data. |
| [Prepare a project](PREPARE_PROJECT.md) | Turn your machine/media recipe and code inputs into a native consumer project. |
| [Consumer projects](CONSUMER.md) | Build, package, run and upgrade a prepared port. |
| [Native CD workflow](NATIVE_CD_WORKFLOW.md) | Qualify System Card startup and CD-loaded code. |
| [Readiness](TOOLKIT_READINESS.md) and [roadmap](ROADMAP.md) | Review current capabilities and remaining acceptance goals. |

## Find and compile code

- [Executed-code captures](CODE_CAPTURE.md) and [extended captures](EXTENDED_CAPTURE.md)
- [Static discovery](STATIC_DISCOVERY.md) and [discovery-backed consumers](DISCOVERY_CONSUMERS.md)
- [Live RAM overlays](LIVE_OVERLAYS.md), [disc origins](DISC_ORIGINS.md) and [guest loader sweeps](LOADER_WORKFLOWS.md)
- [Declared code](DECLARED_ROOTS.md), [boot sources](BOOT_SOURCE_DECLARATIONS.md) and [source sets](SOURCE_SETS.md)
- [Offline CD load maps](CD_LOADS.md)
- [Shared RAM/CD calls, returns and writable-data permissions](RAM_CD_ANALYSIS.md)
- [Resident-source composition and proven stack transfers](RESIDENT_FAR_CALLS.md)
- [Observation histories](OBSERVATION_HISTORY.md) and [mixed observation profiles](OBSERVATION_PROFILES.md)
- [Native coverage gaps](NATIVE_GAPS.md)
- [Compare native extensions](NATIVE_EXTENSIONS.md)

Advanced analysis includes [ROM data](ROM_DATA.md), [register evaluation](REGISTER_EVAL.md),
[branch facts](BRANCH_FACTS.md), [saved stacks](STACK_VALUES.md), [WRAM values](WRAM_VALUES.md),
[memory flow](MEMORY_FLOW.md), [mapper transitions](MAPPER_FLOW.md) and
[synchronous software interrupts](SOFTWARE_INTERRUPTS.md).

## Build and distribute a port

- [Stable emission](STABLE_EMISSION.md) and [shared compilation](SHARED_EMISSION.md)
- [Incremental builds](INCREMENTAL_BUILDS.md), [package cache](BUILD_CACHE.md) and [interrupted-build recovery](BUILD_RECOVERY.md)
- [Native spans](NATIVE_SPANS.md) and [performance](PERFORMANCE.md)
- [Launch planning](LAUNCH_PLANS.md), [save persistence](PERSISTENCE.md) and [migration contracts](NATIVE_MIGRATIONS.md)
- [Consumer gameplay adapters and settings](TITLE_ADAPTERS.md)
- [Licensing and third-party dependencies](../THIRD_PARTY.md)

## Add presentation and controls

- [Desktop host and pacing](DESKTOP.md)
- [Display modes, fullscreen and shaders](DESKTOP_PRESENTATION.md)
- [Five-player input profiles](DESKTOP_INPUT.md)
- [Widescreen and ultrawide example](../examples/widescreen/README.md)
- [Frame reconstruction and continuity](PRESENTATION_HISTORY.md)
- [Completed-frame timing, softness and persistence](PRESENTATION_EFFECTS.md)
- [Immutable scene layers, sprite masks and tilemap sampling](PORT_RENDER_LAYERS.md)
- [Audio output, filtering and resampling](AUDIO_OUTPUT.md)

## Debug and verify

- [TCP development server](DEV_SERVER.md) and [state-aware routes](STATE_ROUTES.md)
- [Sparse checkpoint scenario example](../examples/state-routes/README.md)
- [Developer checkpoints](DEVELOPER_CHECKPOINTS.md) and [interpreter reference mode](REFERENCE_MODE.md)
- [Audited additive-module continuation](CHECKPOINT_CONTINUATIONS.md)
- [Read-only checkpoint BRAM diagnostics](CHECKPOINT_BRAM.md)
- [Typed checkpoint inspection and comparison](CHECKPOINT_INSPECTION.md)
- [Paused observations](PAUSED_OBSERVATIONS.md), [validated RAM edits](PAUSED_WRITES.md) and [semantic frame stepping](SEMANTIC_STEPS.md)
- [Bus-event traces](BUS_TRACES.md), [reference traces](REFERENCE_TRACES.md) and [audio traces](AUDIO_TRACES.md)
- [Burst border-color references and known core differences](BURST_COLOR.md)
- [Upstream reference review and remaining opportunities](REFERENCE_UPDATES.md)
- [Evidence helpers](EVIDENCE_HELPERS.md) and [raw-audit integration](RAW_AUDIT_INTEGRATION.md)
- [Bounded GPU probes and Windows diagnostics](GPU_TESTING.md)

## Understand the hardware model

| Area | References |
| --- | --- |
| Architecture and CPU | [Architecture](ARCHITECTURE.md), [CPU semantics](CPU_SEMANTICS.md), [timer](TIMER.md) |
| Media and boot | [Media](MEDIA.md), [HuCards](HUCARD.md), [System Card boot](SYSTEM_CARD_BOOT.md), [Arcade Card](ARCADE_CARD.md) |
| Video | [VDC](VDC.md), [continuous output](VIDEO_OUTPUT.md), [queued VRAM accesses](VDC_ACCESS.md), [scroll timing](VDC_SCROLL.md) |
| CD and audio | [CD transport](CD_CONTROL.md), [drive timing](CD_TIMING.md), [CD audio](CD_AUDIO.md), [subchannels](CD_SUBCHANNEL.md) |
| Input | [Joypad and TurboTap protocol](INPUT.md) |

## Follow development

[Current results](STATUS.md) · [Milestone history](MILESTONES.md) · [Compatibility corpus](COMPATIBILITY_CORPUS.md)
· [Research](RESEARCH.md) · [Peer projects](PEER_PROJECTS.md) · [Contribution guide](../CONTRIBUTING.md)
