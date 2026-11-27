# Burst border color and reference scope

Frame-latched VDC burst output now selects VCE palette entry `$100` instead of
forcing RGB black. The burst decision remains latched at the physical frame
boundary. A mid-frame CR display disable outside burst continues to emit ordinary
transparent index `$000` at the existing HDS latch. Palette and digital monochrome
conversion retain the per-dot VCE profile; unemitted padding stays black.

The current-state snapshot inspector assumes both CR display enables clear means
burst and selects `$100`; it cannot reconstruct a historical mid-frame disable.
Continuous output retains that distinction. Scheduler clocks, VRAM fetch ordering,
IRQ state and checkpoint encodings are unchanged. New binaries need their own
baseline; old source-bound checkpoints are not rebound.

## Independent authored evidence

Five byte-identical authored HuCards set `$000` red and `$100` green. An unchanged
full [Beetle PCE core](https://github.com/libretro/beetle-pce-libretro/tree/b96c11e095b6a40a412d2da02766ae1c3f4fd539)
and an isolated software/headless [Geargrafx oracle](https://github.com/drhelius/Geargrafx/tree/d3e264c937be5ddaf67722899ec67293303f96c6)
executed each input. Admissions sample the center column at rows 40/80/120/180;
they do not establish full-frame parity or electrical hardware behavior.

| Input | Beetle | Geargrafx | Toolkit choice |
| --- | --- | --- | --- |
| Latched burst, CR `$00` | Green `$100`. | Literal black. | Green `$100`. |
| Stable sprite-only `$40`, transparent pixel | Green `$100`. | Red `$000`. | Keep red `$000`. |
| Background `$80` | Red `$000`. | Red `$000`. | Red `$000`. |
| BG+sprites `$C0`, transparent pixel | Red `$000`. | Red `$000`. | Red `$000`. |
| Mid-frame `$80` → `$00`, outside burst | Red `$000`. | Red `$000`. | Keep red `$000`. |

[Mesen source](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceVdc.cpp)
also distinguishes burst/outside-picture palette 256 from in-picture transparent
zero. Mesen was inspected, not executed here. Current
[Geargrafx source](https://github.com/drhelius/Geargrafx/blob/5f3817cc2041edf066a22b21384f7c8aba9bbbc3/src/huc6270_inline.h)
retains explicit burst black and nonburst zero-color remapping.

Both cross-core differences remain visible. This update follows Beetle plus Mesen
for burst, and retains the Mesen/Gear nonburst profile. It does not claim Gear
verified the new burst color or resolve sprite-only output.
[Rondo's transition fix](https://github.com/gminustwo/RondoRecomp/commit/2b17d6f1fe44d7c01abe81df4dfbcd873f1a5e36)
was the useful lead; its current-CR shortcut is not copied.

`scripts/blanking_reference.py` and its authored libretro wrapper reproduce the
optional matrix. Literal unit expectations remain separate from those full-core
executions. Local tests also check per-dot border palette/monochrome changes and
next-frame admission. External per-dot palette timing remains unqualified.
The original mistaken sprite-only prediction and an unsuccessful supplemental
burst/RCR palette-change probe stay failed, not counted as passing cases.
