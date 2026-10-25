# Authored persistent BRAM consumer

This example uses only authored bytes. Each launch increments BRAM offset zero
once, reads it into CPU X, locks guest BRAM and loops in translated native code.
It does not format a game filesystem or bypass real firmware.

```sh
python examples/persistent-consumer/prepare.py .local/persistent-example
python -m pcerecomp.project build .local/persistent-example/project.toml --build-dir .local/persistent-build --generator Ninja
```

Create a dedicated, empty save directory. Read the digest from the generated
`save-contract.txt`, then pass that value as `CONTRACT_SHA256` below:

```sh
python -m pcerecomp.project run .local/persistent-example/project.toml --build-dir .local/persistent-build --receipt .local/persistent-first.json --save-root EXPLICIT_EXISTING_DIRECTORY --save-namespace counter --save-contract CONTRACT_SHA256
python -m pcerecomp.project run .local/persistent-example/project.toml --build-dir .local/persistent-build --receipt .local/persistent-second.json --save-root EXPLICIT_EXISTING_DIRECTORY --save-namespace counter --save-contract CONTRACT_SHA256
```

With a new namespace, the receipts should report X=1 then X=2, 200 native and
zero interpreted instructions each. Guest BRAM is locked at both endpoints;
the persistent payload still contains the actual counter. Without session
options, each launch starts at X=1. Every run needs a new receipt path.

See [persistence contracts and failure boundaries](../../docs/PERSISTENCE.md).
The generated observation entries are authored emitter fixtures, not recorded
retirements. Execution receipts distinguish the later actual runtime work.
