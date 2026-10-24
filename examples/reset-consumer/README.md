# Authored reset-vector consumer

This example creates an entirely authored 256 KiB System Card image and a
direct C++ native module. Its actual reset vector at physical `$1FFE` selects
logical `$E000`, where a five-byte program loads A with 41, increments A, and
loops. No firmware, disc, extracted program, saved state or download is used.

From a committed toolkit checkout with Python 3.11+, CMake 3.20+ and a C++20
compiler:

```sh
python examples/reset-consumer/prepare.py .local/reset-consumer
python -m pcerecomp.project verify .local/reset-consumer/project.toml
python -m pcerecomp.project build .local/reset-consumer/project.toml --build-dir .local/reset-consumer-build
python -m pcerecomp.project run .local/reset-consumer/project.toml --build-dir .local/reset-consumer-build --receipt .local/reset-consumer-run.json
```

Preparation requires a new output directory. `--tool-root PATH` selects the
exact source checkout to pin and use for generation; `--profile super` selects
Super System Card memory instead of the default Standard profile. The strict
schema-1 descriptor uses `[boot]` and a hashed `[bios]`, with no `[payload]`,
load address, caller-supplied PC or initial MPR mapping. ABI 17 is required.
The official consumer interface supports headless and optional SDL desktop
hosts; see [the consumer contract](../../docs/CONSUMER.md) for build and TCP
options.

The expected result is **200 native / zero interpreted instructions**, A = 141,
X = Y = SP = 0, PC = 57347 (`$E003`), and 7,176 master ticks. One two-cycle
LDA, 100 two-cycle INA instructions, and 99 four-cycle BRA instructions total
598 CPU cycles at the initial low-speed divisor of 12. Reset metadata retains
the initial PC `$E000`, rather than replacing it with the final PC.

The deterministic `gear-deterministic-zero-v1` initialization chooses zero
for otherwise undefined register/RAM/MPR state, sets P = 4, and starts the CPU
at low speed. It deliberately does not format BRAM; no BRAM image is attached
by this example. These choices support reproducible reference comparisons;
they are not a claim that physical hardware always powers on with zeros.

This is a synthetic reset-vector and native consumer proof. A successful run
does not qualify real System Card firmware, a CD boot, or a complete game.
Generated code/capture snapshot terminology retains its existing meaning:
the snapshot describes source identity for compilation, while `[boot]`
selects how the runtime starts the console.
