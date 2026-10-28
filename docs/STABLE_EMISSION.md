# Stable observed-code source layout

`emit-capture --partition-layout stable` is an opt-in layout for a private
retired-code capture. The default `balanced` layout retains its existing source
bytes, filenames and partition-count behavior. Neither layout changes the
runtime ABI or the meaning of an observed source identity.

```sh
python -m pcerecomp emit-capture observed-code.json --out new-module --partition-layout stable
```

Stable output always uses a dispatcher and separate parts, including a capture
with one supported instruction. A part is identified by all eight MPR bytes,
packed little-endian into a 64-bit value, and a fixed 256-byte logical-PC range.
For example, `module_m008483828180f8ff_p4000.cpp` contains observations at
logical `$4000..$40FF` under MPR `[255,248,128,129,130,131,132,0]`.
No digest truncation or capture-order/global index determines a part's name.

Adding an earlier PC or another mapping does not rename existing parts. Adding
or changing an observation can change its own range's source, the dispatcher,
declarations and manifest. Adding only an exact-source variant at an existing
PC leaves the dispatcher and declarations unchanged. Changing hit counts changes
capture provenance and accounting in the manifest without changing source bodies.

Parts include the runtime header directly and do not include the global module
declarations. Thus a declaration-list change does not itself create a textual
dependency from every part. The dispatcher includes the declarations, and the
manifest still pins every emitted source and header by SHA-256. Consumers and
CMake validate those pins before compilation.

`partition_size` remains a balanced-layout identity-count target. Stable mode
requires its default value of 256 and rejects `--single-unit` or a nondefault
`--partition-size`; its fixed logical range is not an identity-count limit.
All same-PC opcode/operand variants stay together, so a part may contain more
than 256 identities. Sparse mappings can produce more small parts than the
balanced layout; stable output alone does not establish faster compilation.

The stable manifest adds:

```json
{
  "partition_layout": "stable",
  "pc_bucket_size": 256,
  "partition_identity": "full_mpr_logical_pc_range_v1"
}
```

The entry checks the instruction deadline and all eight live MPRs. Each part
selects the logical PC, peeks every exact fetched source byte, then executes
translated C++ operations. Physical fetches across an MPR boundary or `$FFFF`
wrap remain individually guarded. Unseen, changed or unreadable code returns
`Exit::miss` before mutating guest state. This is the same dispatch contract as
balanced emission, with different source placement.

Emission still requires a new directory. Stable layout is a prerequisite for
useful incremental builds, not an object cache or permission to edit a previously
qualified package in place. A managed producer must verify ownership and old
hashes, preserve unchanged timestamps, account for removed files, invalidate
old build/run bindings, and perform a real rebuild before claiming changed-unit
reuse. Historical capture ABI labels and runtime/package identities retain
their existing requirements.

Authored tests cover 8,192 sites in eight mappings: adding one earlier site or
an earlier mapping preserves all 32 existing part files byte-for-byte. Further
tests cover exact variants, source wrap, empty/unsupported captures, capture
ordering/provenance, option refusal and the unchanged balanced default. A real
CMake test compiles a shared stable module into two consumers and a guard probe,
executes six native instructions with no fallback per consumer, and checks
source/mapping/deadline refusals and manifest tampering. These are finite source
layout and native guard checks, not broad library or performance qualification.
