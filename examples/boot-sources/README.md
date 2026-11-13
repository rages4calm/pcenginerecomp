# Authored boot sources → native consumers

Create native modules directly from authored raw RAM payload or System Card
instruction declarations. No game, extracted disc or real BIOS is needed.
Use a committed checkout, Python 3.11+, CMake 3.20+ and a C++20 compiler.
Destinations must be new. Ninja is shown below.

```sh
python examples/boot-sources/workflow.py create .local/my-boot-source --source cd-ram
python examples/boot-sources/workflow.py prepare .local/my-boot-source
python examples/boot-sources/workflow.py qualify .local/my-boot-source --generator Ninja
```

Repeat with separate output directories and `--source work-ram`,
`--source system-standard` or `--source system-super` on the create command.
The creation receipt pins exact SDK/source hashes and original numeric/raw bytes.
Preparation copies the [boot-source declarations](../../docs/BOOT_SOURCE_DECLARATIONS.md)
into an official verified consumer, with shared emission for practical firmware
build times. Changed source/SDK inputs require a new experiment; do not repin proof.

Qualification compiles the exact consumer, runs its separate cold path and links
a probe against that official runtime archive/header/DLLs. Native and interpreter
probes check every literal CPU/MPR boundary, complete 8 KiB WRAM, clocks and exact
encoded keys/hits. The 23-instruction route exercises speed transition, mapped
source reads, stack traffic and a balanced call. Source-bank tags distinguish real
bank contents; raw mirror cases keep their own mapped identities.

| Source | Separately preset windows | Distinct declared keys | Retired instructions per tier |
| --- | ---: | ---: | ---: |
| CD RAM | 8 | 184 | 184 |
| WRAM aliases | 4 | 38 | 92 |
| Standard System Card | 128 | 2,944 | 2,944 |
| Super System Card | 104 | 2,392 | 2,392 |
| Total | 244 | 5,558 | 5,612 |

Positive native windows have zero interpreted work or guard misses. A separate
assisted negative changes a live source operand after five retired instructions;
native dispatch refuses it with one guard miss and no refusal-time CPU/clocks/
memory/generation effects. Source files remain unchanged. Windows probes run with
a system-only PATH. Preset matrix windows, official cold paths and negative host
edits retain separate evidence; no whole-title or hardware claim follows.

This workflow provides internal tier parity plus separate literal expectations.
External Geargrafx and managed-build evidence described in the policy documentation
was recorded separately in the development batch; `qualify` does not silently rerun
those experiments. Managed projects require stable layout; this shared example
does not change that contract.
