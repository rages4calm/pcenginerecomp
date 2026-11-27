# Desktop input profiles

Desktop consumers share host-side keyboard and SDL-standard gamepad bindings.
They can select an optional JSON profile through `--input-profile FILE` or
`DesktopOptions::input_profile`. Ports do not need their own SDL input loop.
The launcher remains consumer-owned. The headless runner has no physical input.

```json
{
  "format": "pce-desktop-input-1",
  "schema": 1,
  "slots": [
    {
      "port": 0,
      "keyboard": {
        "i": ["Z"], "ii": ["X"],
        "select": ["Left Shift", "Right Shift"], "run": ["Return"],
        "up": ["Up", "Keypad 8"], "right": ["Right", "Keypad 6"],
        "down": ["Down", "Keypad 2"], "left": ["Left", "Keypad 4"],
        "iii": ["A"], "iv": ["S"], "v": ["D"], "vi": ["F"]
      },
      "gamepad": {"index": 0, "deadzone": 16000}
    },
    {"port": 1, "gamepad": {"index": 1, "deadzone": 12000}}
  ]
}
```

The file is ASCII JSON, at most 16 KiB. Its strings may use ASCII Unicode
escapes. Integers are exact unsigned decimal values. Unknown fields,
duplicate keys/ports, malformed values and conflicting bindings are refused
before the host opens a window or graphics device. An explicit profile starts
with every slot unbound. Omitted slots, keyboard maps and gamepads stay disabled.
An empty `slots` array deliberately disables all guest desktop input.

The twelve action names, in guest-mask bit order, are `i`, `ii`, `select`, `run`,
`up`, `right`, `down`, `left`, `iii`, `iv`, `v`, `vi`. A keyboard action accepts
zero to four SDL scancode names. A physical key can belong to only one action
and player slot. Escape, Space and F11 remain host quit, pause and fullscreen
commands and cannot be rebound to guest actions. Enter/Return remains guest
Run except while a host display confirmation explicitly consumes it.

Gamepad `index` is required and is within 0..15. It selects an ordinal among
the currently connected SDL-recognized gamepads, sorted by their SDL instance
IDs. This is a process-local device choice, not a permanent USB identity.
Existing connected assignments are retained across hotplug events; a device
already owned by another player is never stolen. If an ordinal is missing
or already assigned, that slot remains without a controller. Disconnecting
and reconnecting hardware can change the ordinal for future assignments.
Profiles should be checked with the actual connected devices before play.

Optional gamepad `buttons` maps actions to SDL-standard names such as `south`,
`east`, `back`, `start`, `dpup`, `dpright`, `dpdown`, `dpleft`, `west`, `north`,
`leftshoulder` and `rightshoulder`. A present buttons map replaces every default
button binding, and cannot assign the same button twice. Without this field,
the names above map to the twelve actions in the order shown. The left stick
always supplies guest directions. Its deadzone is 0..32767, default 16000;
movement strictly outside the threshold sets a direction. The profile does
not change the guest joypad's two/six-button or multitap protocol. Multiple
guest ports require the consumer's existing multitap option.

Without a profile, the original keyboard aliases and first available gamepad
remain on slot 0, with a deadzone of 16000. Simultaneous opposing directions
retain their original guest masks; no new cancellation policy is imposed.

`DesktopHost::buttons(slot)` returns a host mask for slots 0..4, while the
argument-free call still returns slot 0. Held keys/gamepads and two-frame tap
pulses combine per slot. Redraw/readback do not age taps. Focus loss, pause
and device removal clear pending input, and checkpoint quiescence examines
all slots. `reset_input()` clears keyboard state and all pending taps without
touching guest state. A held physical gamepad is sampled afresh on the next
poll. Bindings are host configuration and are not serialized into guest
checkpoints. They load once at host construction; editing a file does not
silently change a running session.

The interface was independently implemented using Dungeon Explorer PC's
per-player binding workflow as a design reference.
[Project credit](https://github.com/gorigamia/dungeon-explorer-pc)

Authored tests use SDL's dummy/software renderer and virtual gamepads. They
check default compatibility, parser refusals, independent five-slot input,
custom deadzones, tap lifetime, focus/reset behavior and controller ownership
after disconnect. They do not establish compatibility with every physical pad.
