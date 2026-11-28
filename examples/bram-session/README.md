# Optional initial backup memory through a real consumer

This example uses original authored System Card reset firmware and four zero
sectors. It reads all 2,048 backup-memory bytes through guest instructions,
updates two bytes, reads them back, and locks the device through its normal
ports. No retail BIOS, game image or player save is needed.

```sh
python examples/bram-session/workflow.py create .local/bram-session-example
python examples/bram-session/workflow.py qualify .local/bram-session-example --generator Ninja
```

Pass compiler and Ninja paths with repeated `--cmake-arg=...` when needed.
The headless workflow uses no physical display, GPU or speaker.

The reference bootstrap records genuine execution for the native consumer.
Blank default, explicit formatted seed, existing blank save and existing
patterned save cases compare native/reference TCP execution and own-package
checkpoint suffixes. Full WRAM/RGB and canonical HOST/CORE must agree with only
four execution-tier counters projected. A guest WRAM copy supplies complete
backup-memory readback; the TCP controller does not peek into BRAM.

Cold native runs separately export and explicitly commit the qualified result,
then reopen that save. Reference and checkpoint-fork runs never publish. An
invalid-option host refusal also checks that an existing saved envelope remains
unchanged. Seed provenance distinguishes requested policy, actual seed origin,
seed digest and a preceding committed save.

The optional 2 KiB developer seed is `48 55 42 4D 00 88 10 80` followed by
2,040 zero bytes. This follows [Beetle PCE](https://github.com/libretro/beetle-pce-libretro/blob/974fe085a9842be2069afc95beaf469a90e9ae44/mednafen/pce/huc.cpp#L30)
and [RetroRecomp](https://github.com/ArthurReboulSalze/RetroRecomp/blob/f8d506c5e949125b2df2cba00cf06653515ee03c/native/pce_machine.cpp#L238).
[Geargrafx's initial header](https://github.com/drhelius/Geargrafx/blob/03de98dcb94d83cec763959936463b06fc440c00/src/memory.h#L161) instead advertises `$A000`; this example
does not claim exact Gear header parity or factory hardware contents. Existing
saved bytes always win, including an already blank image; corrupt saved
envelopes remain errors instead of being silently reformatted.

This qualifies an authored persistence interface, not an authentic game SAVE,
retail compatibility, cross-package checkpoint portability or a campaign.
