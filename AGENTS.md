# Project instructions

Follow the owner's working preferences:

- Do not agree for the sake of agreeing. Make firm technical decisions and
  explain evidence that contradicts a premise.
- Use the available skills, MCP tools, current primary documentation, and
  source inspection instead of guessing.
- Read `docs/STATUS.md` and `docs/ARCHITECTURE.md` before continuing work.
- Do not use the `recomp-workbench` skill for this project. The owner has
  explicitly disabled it. Choose implementation scope from the requested
  milestone and the evidence needed to verify it.

## Engineering rules

- This is a general PC Engine recompilation toolkit. Keep title-specific
  addresses and behavior out of `pcerecomp/` and `runtime/`.
- Ys III is a test case for the toolkit. Use game progression to qualify
  shared capabilities and diagnose defects; prioritize the general tool's
  compiler, runtime and contributor interfaces over campaign completion.
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
- The owner's existing output allowance is 1 GiB of new disposable data per
  batch, shared across build scratch, diagnostics and other generated output.
  Keep long-running extraction, generation, traces and CI output controlled.
- Do not copy research-reference code across incompatible licenses. Preserve
  attribution for third-party material.
