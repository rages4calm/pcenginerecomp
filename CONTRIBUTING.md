# Contributing

Start with [status](docs/STATUS.md), [architecture](docs/ARCHITECTURE.md), and
the [roadmap](docs/ROADMAP.md). Open a focused issue or use an existing one
before a large architectural change. Small, well-evidenced fixes are welcome
without an elaborate proposal. All experience levels can contribute;
hardware/source review and clear reproductions are particularly useful.

## Useful first work

- Add independent HuC6280 expectations for existing instructions: all flags,
  logical-address wrapping, stack wrapping, MPR aliases and cycle totals.
- Extend synthetic media tests: virtual gaps, stored gaps, postgaps, multiple
  data tracks, malformed metadata and user-data sector selection.
- Improve portable build diagnostics and run the synthetic suite on another
  host architecture.
- Review source citations and platform facts. Report contradictions instead
  of silently picking the behavior convenient for a test.

CPU, CD, sound, and video work must include a source-backed behavior contract
and a focused test. A test copied from the implementation is insufficient.
The existing native/interpreter comparisons detect translation differences;
both tiers can still share a mistaken hardware assumption.

## Code and verification

Python 3.11+ for tooling; C++20 for runtime/generated output. Keep the core
dependency-light and game-agnostic. Generated code is never edited to repair
a game: change the analyzer/emitter or supply a documented game profile.

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
python scripts/check.py
```

Include the relevant test result and the evidence level in a PR: synthetic
semantics, generated/compiled code, executed CPU steps, emulator parity,
display/audio verification, or gameplay route. Report unsupported cases.
Do not infer whole-game compatibility from instruction counts or a title
screen. Performance changes require matched workloads and measurements.

## Data and licensing

Do not commit images, firmware, extracted assets, generated game source,
captured code, personal paths, or saves. Use ignored `.local/` for private
experiments. Public fixtures must be original synthetic programs or have
documented redistribution permission. Screenshots and logs need the same
review. The source audit runs in CI, but is not a legal review or a complete
secret scanner.

By contributing original code you agree to its distribution under this
project's MIT license. Retain third-party notices and identify copied or
adapted work. Do not copy PolyForm/GPL implementation code into the MIT
runtime. Propose an appropriately isolated dependency if reuse is needed.

AI-assisted work is welcome. Contributors remain responsible for reading,
understanding, and validating their changes and citing external material.
There is no requirement to disclose private prompts or account data.

## Pull request checklist

- State the concrete behavior change and any affected runtime ABI/schema.
- Link primary hardware/tool documentation for non-obvious semantics.
- Add a meaningful reproducer or focused test and report its actual result.
- Keep reference behavior available when adding an enhancement.
- Update status/docs when a capability changes.
- Check `git diff --cached` and run `python scripts/audit_public.py`.
