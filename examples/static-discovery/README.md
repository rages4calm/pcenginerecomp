# Bounded static discovery from two numeric seeds

This authored 16 KiB HuCard demonstrates ROM discovery without fabricating retired
observations. Two numeric instruction seeds expand to **15 source-qualified
candidates across three complete MPR contexts**, within three explicitly allowed
decoded-ROM code ranges. The output is an ordinary declared-roots input, plus a
separate recomputable discovery graph and diagnostics.

The startup first maps WRAM through a known `LDA`/`TAM`, then switches its executing
ROM bank through another known `LDA`/`TAM`. The second bank contains a conditional
poll loop and direct call. Its post-call continuation is an **explicit second
seed**. Calls follow the callee only; returns and unknown call continuations are
not guessed. Filler data outside the allowed code ranges is never scanned as code.

This is not automatic routine recovery, complete reachability or a game port.
Discovery retains unresolved call/return boundaries even when its bounded queue
closes. Static candidates, emitted operations, successful compilation and actual
executed instructions are separate evidence.

## Reproduce

Build a fresh no-module headless host from the same pinned SDK first. Use new
private output names and keep the image, initial seeds and SDK unchanged:

```sh
python examples/static-discovery/workflow.py create .local/static-demo
python examples/static-discovery/workflow.py capture .local/static-demo --runner build/pce-headless.exe
python examples/static-discovery/workflow.py discover .local/static-demo
python examples/static-discovery/workflow.py prepare .local/static-demo --with-history
python examples/static-discovery/workflow.py qualify .local/static-demo --generator Ninja
python examples/static-discovery/workflow.py probe .local/static-demo
```

On other platforms use the corresponding host filename. Pass explicit compiler
and Ninja paths when needed, for example
`--cmake-arg=-DCMAKE_CXX_COMPILER=/path/to/clang++` and
`--cmake-arg=-DCMAKE_MAKE_PROGRAM=/path/to/ninja` to `qualify`.

`capture` is optional. It records a genuine 100-interpreted-instruction prefix and
retains its original history separately. Discovery itself accepts only numeric
seeds, the supplied image and explicit code ranges. To compile a pure static
candidate, omit `capture` and omit `--with-history` from `prepare`; no empty capture
or history is manufactured.

The discovery closure contains exactly `seed-roots.json`, `roots.json` and the
last-published `discovery.json`. The original ROM is supplied separately and is
not copied into the closure. `roots.json` is consumed by existing declared-module
preparation. The consumer does **not** automatically archive discovery provenance:
retain and revalidate the separate graph/receipt alongside build/run evidence.

The workflow checks its expanded per-instruction PC, complete MPR mapping and
every decoded-ROM byte offset against a literal 15-entry plan. It also checks
real captures by complete source keys and exact per-key native/interpreted hits;
it does not join live row numbers or infer bytes from later RAM.

## Independent finite expectations

The seven setup instructions cost 21 CPU cycles. Four pre-CSH instructions consume
14 slow cycles; CSH consumes two slow cycles and one fast cycle, followed by four
fast cycles for LDX/TXS. Setup therefore consumes 207 master ticks.

The remaining 93 prefix instructions are 47 absolute LDA operations at five cycles
and 46 taken BEQs at four cycles. The prefix totals are **440 cycles /1464 ticks**.
It ends at `$E10F`, A 0, X 255, Y 0, SP 255, P 6 and MPRs
`[0,248,0,0,0,0,0,1]`. All 8192 WRAM bytes are zero. An official native-only run
retires 100 native instructions, zero interpreted and zero guard misses, recording
nine actual source identities; six expanded candidates remain unexecuted.
The official run binds CPU state and capture membership. Prefix whole-RAM
validation happens in the separate compiled probe before its flag write.

The compiled probe explicitly writes the WRAM poll flag from the host without
retiring a guest instruction. This is developer assistance. Ten subsequent guest
instructions execute a real native call and return. They consume
`4+5+2+7+2+5+5+7+4+5 = 46` fast cycles. The final endpoint is **486 cycles /1602
ticks**, with 110 native retirements and all 15 exact identities exercised. A
separate interpreter process checks the same literal state and all 8192 RAM bytes.
Final WRAM differs from zero only at offsets `1 = 42`, `$1FE = $13` and `$1FF = $E1`.
The stack bytes encode the JSR return address `$E113`.

A separate negative changes only an in-process copy of the callee operand. After
104 native instructions, at `$E140`, the byte guard refuses with one guard miss
and no additional retirement or clocks: **458 cycles /1518 ticks**. Its RAM has
the host flag at offset 0 and the same two stack bytes; the callee has not run.
The original image file remains unchanged. Fresh captures and complete RAM dumps
are retained for each actual probe process.

## Refusal and frontier controls

The public tests also use authored ROM entries outside the positive code ranges:

- An indirect JMP remains an `indirect_jump` frontier.
- A RAM-loaded unknown accumulator followed by TAM stops at `mapping_change`.
- A reserved opcode is reported as `unassigned_opcode`; it is not a NOP.
- A direct call to a disallowed callee reports a boundary and return uncertainty.
  Its allowed fallthrough is absent unless separately seeded.
- Explicit small limits report frontiers; altering a sealed seed/report/root or
  adding an unlisted file invalidates the discovery closure.

These are bounded compiler/source/CPU checks. They do not establish independent
emulator or hardware parity, universal code discovery, live overlays or gameplay.
