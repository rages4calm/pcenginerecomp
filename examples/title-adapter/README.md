# Consumer gameplay-adapter example

This small authored program earns three EXP and five gold once, spends two gold,
and uses a two-frame, guest-VBlank-driven post-hit countdown. Its optional C++
adapter changes the earned input at those exact source-qualified instructions.
It never periodically multiplies the balance or treats spending as a reward.
EXP and gold multipliers are independent choices from 1x through 8x. Protection
changes this toy countdown from two to four guest frames; it is not a claim about
the timing or implementation of any retail game.

The original guest first programs and warms up its VDC timing. The workflow
records the first completed gameplay frame as an explicit origin, then checks
the countdown against subsequent guest frames; transient power-on timing is
not mistaken for gameplay time. No debugger writes or CPU teleport is used.

The adapter keeps every persistent counter and guest-frame expiry in its
declared SDK-owned state span. Reads use the narrow context view; register and
volatile RAM edits are expected-value transactions. It has no mutable globals,
wall-clock decisions, PC redirection, owner-save writes, or guest retirement
counter edits.

Run from the frozen SDK being qualified:

```sh
python examples/title-adapter/workflow.py \
  --out .local/title-adapter-proof \
  --toolchain-root PATH_TO_AUDITED_LLVM_MINGW \
  --dependency-root PATH_TO_SDL3_SDK \
  --cmake-arg=-DSDL3_DIR=PATH_TO_SDL3_CMAKE_DIRECTORY
```

The supported audited producer performs three real consumer builds: original,
scalar adapter and an eight-instruction native-span adapter. SDL is forced
to dummy video, software rendering and dummy audio, so no monitor or physical
audio device is used. `--headless` omits the optional paced desktop comparison.
No game image or firmware is needed. The output directory must be new; failed
artifacts are preserved rather than overwritten.

Qualification compares the original program with a compiled adapter in pristine
mode and explicit 1x/off mode. Enhanced native, repeat and interpreter runs use
the same own-package checkpoint, with different frame-step chunking and an
optional paced run. Literal balance, spending, health and countdown expectations
are checked at guest-frame boundaries. Full serialized host, adapter and machine
state, work RAM, guest RGB and nonzero digital PCM are compared, projecting only
the four execution-tier counters where native and reference work differ.
Native repeat checkpoints must match byte-for-byte.
The span consumer creates its own bound seed, exercises actual local native
continuations and compares its complete guest/adapter state and original
retirement counts with the scalar consumer. No checkpoint identity is spoofed
to transfer state between those different recipes.

The enhanced checkpoint contains nonzero persistent adapter state and pending
audio. Settings/mode mismatches must refuse restore, and changed adapter source
or manifest must refuse launch. Unknown or invalid settings and attempts to
capture enhanced execution as original-program discovery are rejected before
launch. Enhancement diagnostics use a separate audit output; they are not guest
native instructions or original-code capture hits.

`receipt.json` records the actual source pin, producer hashes, build receipts,
fresh versus imported retirement counts, state/audio comparisons and negatives.
This example qualifies the shared extension contract, not a retail enhancement,
whole-game coverage, original hardware behavior or audible playback.

The initial frozen-SDK qualification passed all three audited cache-miss builds
and thirteen runtime comparisons. Enhanced scalar and span suffixes each retired
119,208 native instructions with zero fallback or guard misses, matching the
interpreter reference. The span run exercised 104,307 local continuations with a
maximum of eight instructions. Seeds retained 39 nonzero pending PCM frames;
each suffix checked 2,977 stereo samples against literal `(1761, 0)` output.
Pristine and 1x/off matched the original guest's complete HOST/CORE state.
Independent review rehashed 192 retained files and checked raw TCP evidence.
