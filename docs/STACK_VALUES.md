# Saved stack values in static discovery

`discover-roots --stack-facts --alu-facts --branch-facts --call-depth 8`
adds an explicitly opt-in relative stack model. The Python API uses
`stack_facts=True, alu_facts=True, branch_facts=True, call_depth_limit=8`.
Omitting the new option retains every older policy and byte encoding.

This helps ordinary save/restore prologues preserve facts needed by TAM,
indexed ROM data/JMP and conditional discovery. It does not replace runtime
pushes or pops, fold stack memory, infer initial SP/RAM, or establish routine,
interrupt or whole-game closure. The runtime, emitter and ABI 29 are unchanged.


## Synchronous BRK/RTI derivations

The opt-in [software-interrupt policy](SOFTWARE_INTERRUPTS.md) extends memory-flow
facts through proven BRK vectors and balanced protected three-byte RTI frames.
It preserves partial saved status, nested caller provenance and current return
MPR/selector/source identity. Optional SF2 mapper facts compose explicitly.
Readers rederive every witness; omission preserves previous policy bytes.
Runtime lowering/ABI 29 are unchanged. This does not establish asynchronous IRQ
closure or support modified/unmatched frames.


## Values and status bits

Each source/calling/depth state carries bottom-first saved cells as
`{known_mask, value}`. Bits outside the mask are zero in the representation,
not known zero in guest memory. A/X/Y remain byte facts or unknown; the status
facts are C/D/T/N/Z/V plus I in this policy only. Seeds start unknown with an
empty **modeled** stack, not a claim that guest stack memory is zero.

- PHA/PHX/PHY save a known byte or an entirely unknown cell.
- PLA/PLX/PLY recover a full register only when every bit is known. They can
  recover N from a known sign bit or Z from a proved zero/nonzero partial byte.
  Ordinary T clearing remains in force.
- PHP stores B=1 and T=0, even following SET. Other known status bits survive;
  unknown bits remain masked. A guaranteed stored B bit can prove nonzero
  after PLA without proving the whole accumulator.
- PLP restores each independently known C/D/T/N/Z/V/I bit and ignores B.
  In particular, a PHA/PLP sequence can restore T=1. CLI/SEI update I normally.
- JSR/BSR push the encoded return word, high byte then low. RTS needs a
  balanced existing frame and two fully known matching bytes, then continues
  in the current full MPR/source view, not a copied caller mapping.

At a join, scalar conflicts become unknown. Cell masks intersect only equal
known bits. Different relative depths/calling contexts remain separate states;
optimistic edges made stale by a later join are retracted by reachability.
`stack_facts`, `stack_event`, `stack_bytes`, incoming/evaluated flags and summary
counts are derivation evidence. They are not instruction hits or observations.
Events list pushed bytes bottom-first and popped bytes top-first.

## Explicit safety frontiers

Stack accesses require MPR1 in $F8–$FB, the canonical base WRAM aliases. Alias
changes preserve cells. Changing to a different mapping with live cells or
frames stops. Ordinary writes which may touch any canonical stack-page alias,
unknown indexed/indirect destinations and block writes stop while cells/frames
are live. Known safe destinations and zero-page writes remain allowed.

No absolute SP is invented. TXS is permitted only with no modeled cells or
frames, as a rebase; otherwise it stops. TSX remains unknown. A pop below the
modeled root stops rather than reading guessed preexisting memory. Callee pops
cannot consume return-frame bytes. Capacity is 256 relative bytes, with an
explicit frontier before overwrite, and call depth remains bounded at 1–64.
In the stack-only policy, unbalanced returns, unproven return words,
unframed RTS, RTI, BRK and unsupported
source/fetch/mapper behavior remain visible frontiers. Asynchronous interrupt
paths and their memory effects are not statically closed by this policy.

All existing instruction/context/code/source/vector/data/table and serialized
size bounds remain in force. Data and vector permissions stay separate from
code permissions. Full selector/MPR/source identity remains part of dispatch.

## Admission and consumer preparation

The policy is `bounded-source-qualified-stack-values-v1`. It requires literal
true ALU, branch and stack options and an explicit valid call depth. It composes
with authorized ROM operands, known or enumerated ROM vectors and calls.
`verify-discovery` rederives the entire canonical three-file graph; masks,
restored facts, events, edges, flags, options and summaries cannot be admitted
merely by recomputing stored hashes. Older readers reject the new policy.

Preparation retains and rederives the closure through ordinary discovery-backed
consumers, compilation inputs and archives. There is no observation fabrication
and no new runtime dispatch tier. Re-pin/rebuild to adopt the updated SDK; source,
package and exact-build checkpoint identities still matter even with ABI 29.
Original receipts and checkpoint producers must not be retagged to publication HEAD.

## Qualified scope

The [original native workflow](../examples/stack-values/README.md) has a 39-operation
banked main route with nested JSR/BSR, alias changes and a status predicate. The
prior branch-only mode stops at unknown mapping / out-of-range conditional arms
with 35 main candidates; the new mode admits all 39 without unresolved frontiers.
The full 282-seed graph grows 1,975 → 1,979 exact source identities. Separate
281-preset matrices execute 1,940 instructions per tier, including every PLP/PHP
input byte and partial status. Every declared identity executes across these
windows. Main: 39 native / zero interpreted / zero guards, 137 cycles / 1,644 ticks.
Literal full CPU/flags/MPR/clocks/WRAM and exact source keys/hits pass. Changed
saved RAM drives the actual restore/branch to an omitted source after 31 native,
zero interpreted / one guard, with no guest effects at refusal.

Fresh Geargrafx 1.8.4 passes 282 CPU/full-WRAM endpoints and 1,979 before/after
instruction points. All 11,049 known incoming components and 5,434 masked saved
bits agree; 8,741 scalar components remain unknown. Reference setup is separate
from every verified source byte. This is independent CPU/RAM evidence, not
external clocks, interrupt/device, retail or hardware qualification. Behavioral
references are [Gear opcode operations](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/huc6280_opcodes.cpp),
[stack/P/dispatch helpers](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/huc6280_inline.h)
and [BSR helpers](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/huc6280_opcodes_inline.h).
Implementation and fixture bytes are original; no GPL reference code was copied.

Fresh Rondo TCP boot/file creation/introduction regression retires 404,669,933
native / zero interpreted / zero guard misses, with 25,621 exact source keys/hits
and 17 paused reported-state/full-WRAM/CD-RAM/RGB samples. Own same-build checkpoint
forks match 59,672 new instructions and 753 keys; the imported 379,716,149-native
prefix remains separate. Paired/no-write raw journals, full original memory bytes
and independently decoded PNG CRC/pixels pass after closure. This is a captured
route regression, not retail use of stack discovery, playable action, whole-game
or external retail/hardware/audio parity. Host audio is off; Ys III stays parked.
Original producers remain original.

Frozen **548ba3f2354e4e0d66801ddafcf4a0a60c6ad005** passes **2,246 Python tests
without skips, 74 C++ suites and 12 fresh-process audio cases**, with all
796 tracked inputs unchanged through the required unmodified checker.
SDK source `1ba77db15a8f7760be9ea8a2e7eb9283200791fe5af3e64b14bd5aba31a587ef`
covers 98 files. Later publication changes are Markdown only. All 72 older graph
combinations byte-match `4ee42af8`; its reader rejects the stack policy. Runtime,
emitter, ABI 29 and checkpoint encoding remain unchanged. New source/package/build
contexts still require fresh exact-build checkpoints.

General writable-memory facts, noncanonical stack mappings, modified return
frames, interrupt closure, live RAM/CD code discovery, broader library/hardware
and player milestones remain open. Saved stack analysis alone is not evidence
of complete console compatibility or a completed native port.
