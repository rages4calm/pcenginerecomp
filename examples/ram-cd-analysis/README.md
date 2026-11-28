# Shared RAM/CD call analysis

This authored example loads two alternative CD sectors using actual guest CD
READ commands. Each overlay calls a balanced PHA/STZ/PLA/RTS routine, then takes
one of two branches. One explicitly writable data byte lies inside the loaded
source range. No proprietary inputs are required.

```sh
python examples/ram-cd-analysis/workflow.py create .local/ram-cd-example
python examples/ram-cd-analysis/workflow.py qualify .local/ram-cd-example --generator Ninja
```

Pass explicit compiler, Ninja and SDL paths with repeated `--cmake-arg=...`
when required by your toolchain. Qualification uses SDL dummy video/audio and
software presentation. It opens no visible game window and makes no GPU claim.

The workflow binds its original authored firmware/disc/recipe and source files.
It declares CD candidates before guest execution, then captures authentic paused
RAM after each real load. The two adapters must derive identical identities.
Separate overlay and CD consumers combine those candidates with genuine firmware
history, compile translated operations, and run both branch choices natively
and through the same-build interpreter reference. Literal full WRAM/CD RAM and
final CPU expectations are checked alongside complete paused status comparisons.
Each consumer also checks native/reference suffixes restored from its own
checkpoint. All child processes quit or are retired on failure.

The controller explicitly supplies branch choice and data-release gates through
checked paused writes. This is internal authored execution evidence, not retail
coverage, hardware timing validation, cross-build migration or routine closure.
See [analysis contracts and remaining frontiers](../../docs/RAM_CD_ANALYSIS.md).
