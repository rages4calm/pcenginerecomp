# Authored consumer example

This six-byte program is written for this repository. It loads A with 41,
copies A to X, then increments X in a loop. Its generated native module and
payload are prepared locally; no game, firmware, disc or downloaded dependency
is involved.

From a source checkout with Python 3.11+, CMake 3.20+ and a C++20 compiler:

```sh
python examples/consumer/prepare.py .local/consumer-example
python -m pcerecomp.project verify .local/consumer-example/project.toml
python -m pcerecomp.project build .local/consumer-example/project.toml --build-dir .local/consumer-build
python -m pcerecomp.project run .local/consumer-example/project.toml --build-dir .local/consumer-build --receipt .local/consumer-run.json
```

The expected 200 retired instructions are all native, with A = 41, X = 140,
PC = 16387 and 1,794 master ticks. These literal expected values come from
two setup instructions and 99 INX/BRA pairs at the sandbox's initial high CPU speed.
This is an authored compiler/runtime check; independent device or game parity
requires separate evidence. See [the consumer contract](../../docs/CONSUMER.md)
for adapting a private project and using TCP.
