# Project instructions

Follow the owner's working preferences:

- Do not agree for the sake of agreeing. Make firm technical decisions and
  explain evidence that contradicts a premise.
- Use the available skills, MCP tools, current primary documentation, and
  source inspection instead of guessing.
- Read `docs/STATUS.md` and `docs/ARCHITECTURE.md` before continuing work.

## Engineering rules

- This is a general PC Engine recompilation toolkit. Keep title-specific
  addresses and behavior out of `pcerecomp/` and `runtime/`.
- Never stage images, BIOS files, extracted data, generated game source,
  code captures, personal paths, or saves. Private experiments go in
  `.local/`; dependencies go in `.deps/`; research downloads in `.research/`.
- Synthetic fixtures in public tests must be authored, not disc excerpts.
- Generated code must contain translated operations. Calling an interpreter
  once per emitted opcode does not count as static recompilation.
- Include logical PC, MPR mapping, and source identity in dispatch reasoning.
  A physical bank or logical PC alone does not identify an overlay.
- Unsupported semantics stop explicitly. Do not stub them to success, silently
  execute unknown opcodes as NOPs, or invent firmware services.
- Use independent expected values and eventually independent emulator traces.
  Agreement between this runtime and this emitter is internal evidence only.
- Run `python scripts/check.py` after a relevant build. Document actual
  native/interpreted work, unresolved semantics, and the test scope.
- Keep guest simulation cadence separate from host presentation. Extensions
  must preserve a reference path and describe save/state compatibility.
- No live install or owner save is used by the baseline. Preserve this
  isolation when adding a desktop host.
- Default work budget: 1 GiB new disposable output, 256 MiB diagnostics.
  Bound extraction, generation, traces, and CI artifacts explicitly.
- Do not copy research-reference code across incompatible licenses. Preserve
  attribution for third-party material.
