# Development control over TCP

Both runners have an optional development server for controller input, bounded
frame advancement, status, and screenshots. It is disabled unless `--dev-port`
is present. This uses the runner's own video and SDL targets; it never captures
the owner's desktop or accesses other applications.

Append these options to an otherwise valid runner invocation:

```text
--video-output continuous --dev-port 0 --dev-start-paused on --wall-seconds 120
```

Port zero selects an available port. The runner prints `PCE_DEV_PORT=N` to
standard error after initialization. A fixed port from 1 through 65535 can also
be requested. `--dev-start-paused` defaults to `off`; `--wall-seconds`, if set,
stops the process after 1 through 600 host seconds even when paused. The normal
guest instruction and master-tick limits still apply. Continuous output is
required when the server is enabled, so a screenshot always refers to a
completed historical frame rather than a newly synthesized snapshot.

The standard-library Python client supports both runners:

```sh
python scripts/dev_client.py --port 4370 status
python scripts/dev_client.py --port 4370 screenshot new-frame.png --source guest
python scripts/dev_client.py --port 4370 screenshot new-window.png --source present
python scripts/dev_client.py --port 4370 frames 2
python scripts/dev_client.py --port 4370 input 0x8 --slot 0 --frames 2 --resume
```

PNG and PPM capture paths are selected by the local Python caller, created
exclusively, and never overwritten. The server receives no file paths. Screenshots
are emitted only when requested. `present` requires the SDL desktop runner;
`guest` works in either runner after the first complete frame.

For a sequence, retain one connection:

```python
from scripts.dev_client import DevClient, write_capture

with DevClient(4370) as client:
    client.call("pause")
    client.call("set_input", port=0, mask=0x8)  # Run, using normal joypad semantics
    client.advance(2)
    client.call("clear_input")
    metadata, rgb = client.capture("guest")
    write_capture("new-frame.png", metadata, rgb)
    client.call("resume")
```

Input is a held 12-bit host mask for each of five controller slots. It is ORed
with the configured script/desktop input and reaches the existing joypad
snapshot; it does not force a guest controller latch or alter input hardware
semantics. The relevant six-button/multitap profile must still be enabled if
needed. Disconnect clears all network-held masks, so a one-shot `set_input`
followed by closing the socket is not an input pulse. The CLI `input` command
holds its connection for a selected number of frames or seconds, then clears
the masks. A seconds-based hold preserves the current run/pause state.

## Wire contract: `pce-dev-1`

IPv4 TCP, `127.0.0.1` only. Each request is one flat ASCII JSON object followed
by LF; CRLF is accepted. Responses use the same connection and one JSON object
per line. Request fields use ASCII strings or unsigned decimal integers;
JSON string escapes for ASCII are accepted. Duplicate or unknown fields,
objects/arrays/booleans/null, negative/floating-point/exponent numbers, invalid
escapes, non-ASCII text, leading-zero integers, and trailing text are rejected.

```json
{"id":1,"cmd":"ping"}
{"id":1,"ok":true,"protocol":"pce-dev-1"}
```

`id` is required and ranges from 0 through 9,007,199,254,740,991, the largest
integer exactly representable in JavaScript. Successful and rejected valid
requests echo it. Malformed requests whose ID cannot safely be established
return `"id":null`. Errors have `"ok":false,"error":"reason"`; they do not
silently fall back to another operation.

| Command | Additional request fields | Result or effect |
| --- | --- | --- |
| `ping` | None | Protocol identifier; also refreshes the idle lease |
| `status` | None | `frame`, current CPU `ticks`, aggregate `paused`, `local_paused`, and a trusted `host` status object |
| `set_input` | Required `mask` 0..4095; optional `port` 0..4, default 0 | Holds that slot's network mask |
| `clear_input` | Optional `port` 0..4 | Clears one slot, or all slots when omitted |
| `pause` | None | Pauses simulation at the next host polling safe point; cancels pending frame advancement |
| `resume` | None | Releases the network pause and cancels pending advancement |
| `step_frames` | Required `frames` 1..600 | Sets `target_frame`, runs toward it, then leaves the network pause engaged |
| `screenshot` | Optional `source`: `guest` (default) or `present` | Inline RGB24 capture |
| `present_shot` | None | Alias for a `present` screenshot |
| `quit` | None | Requests an orderly runner exit and clears network input |

Frame advancement is asynchronous. The immediate response contains
`target_frame`; poll `status` until `frame >= target_frame` and `paused` is true.
Simulation stops at instruction/host polling boundaries, so this is not a
sub-instruction debugger and a single long instruction can span the target.
Desktop local pause is independent; frame-step requests are rejected until it
is released. Network `resume` never overrides the owner's local pause.
Disconnect retains the pause/step state, allowing a new client to
inspect and resume a deliberately paused runner.

The runner's `host` object retains its flat `pc`, execution/IRQ/sector counters,
`adpcm_dma_bytes`, and five `buttons` masks. Additional bounded objects expose
stored state for debugging a stalled guest:

| Object | Stored observations |
| --- | --- |
| `cpu` | A/X/Y/SP/P, clock divisor, MPR transfer latch, sampled IRQ/vector, eight MPRs, physical PC, seven nullable instruction bytes with corresponding physical addresses and bank generations |
| `cd_control` | Enable, interrupt enable/active bits, ACK/reset and port read/write counters |
| `scsi` | Phase/signals, pending status, host/drive latches, event and ACK deadlines, response length/index, acknowledged bytes, TOC replies, sector-provider presence, read/load positions and retries, current command size and last CDB (at most 16 bytes) |
| `cd_audio` | Enable, state and stop mode, start/current/stop/seek positions, seek/sector/playback deadlines, played sectors, command count and fade state |
| `adpcm` | Enable/play/pending/nibble and IRQ state, control/DMA/rate, addresses/length, transaction deadlines, sample phase/count, port and DMA counters |
| `vdc`, `raster`, `interrupts` | VDC status/IRQ, 20 registers, DMA progress, raster clocks/phases/events and interrupt mask/timer progress |

These observations use direct stored values and non-mutating instruction
peeks. They never read MMIO ports, acknowledge an IRQ, consume CD response
data, or advance a device clock. Instruction peeks return `null` for I/O,
unmapped or other non-RAM/ROM banks. Each of the seven bytes is translated
separately through the current MPRs, including logical address wrap; generations
are invalidation hints, while mapping and exact bytes identify the source.
There is no RAM dump or memory-write command. Repeated status requests while
paused preserve all reported guest state. The final runner JSON also includes
the same `cd_audio` and `adpcm` objects.

CD audio states are `0` playing, `1` idle, `2` paused and `3` stopped; stop modes
remain the numeric command modes. Timeline progress does not imply decoded PCM
or audible output. Ticks and deadlines are guest master ticks, not wall time.

Screenshot responses additionally contain:

```json
{"id":2,"ok":true,"source":"guest","width":2,"height":1,"frame":12,"ticks":345,"frame_ticks":340,"encoding":"rgb24-base64","data":"AAEC/f7/"}
```

Decoded `data` contains exactly `width * height * 3` bytes, RGB row-major with
no padding. `frame_ticks` identifies publication of the captured guest frame;
`ticks` identifies the current CPU safe point and can be later. A `present`
capture includes the current SDL composition/letterbox. It is not a screenshot
of the complete operating-system window or desktop. Capturing before the first
complete guest frame returns an error.

## Bounds and ownership

- One active client; the listener is nonblocking and exclusively bound on
  Windows. No remote address or configurable bind interface is supported.
- Requests including LF are at most 8,192 bytes. Response storage is capped at
  17 MiB; each `poll` moves at most 64 KiB over the socket.
- Guest images are at most 1,024 × 512 pixels. SDL composition captures are at
  most 4,000,000 pixels. Only one RGB copy and one encoded response are needed;
  large response storage is released after transmission or disconnect.
- Idle connections, incomplete requests, and outgoing responses have five-second
  bounds. An active script should issue a command at least once every five
  seconds; the CLI's timed hold sends a ping each second. Slow peers cannot
  indefinitely retain the response buffer or block simulation.
- Socket polling, command handling, SDL readback, and input snapshot application
  happen on the main thread. There is no unsynchronized worker touching guest
  memory, no memory-write/evaluate/upload command, and no automatic trace dump.
- This is an opt-in local development interface, without authentication. It is
  not an internet service. Loopback access has the same user-session trust
  boundary as launching the development runner locally.

## Verification and source lineage

The authored TCP suite exercises actual loopback sockets: fragmented/pipelined
requests, strict parser refusals and integer limits, all five input slots,
pause/resume/frame targets, exact RGB/base64 bytes and capture metadata,
capture failures, reconnect/input release, maximum request length, stalled
partial requests, and a stalled maximum-size presentation response. The runner
integration tests separately verify that input/status/screenshots control the
real headless and optional SDL host. A TCP transport check is not an independent
PC Engine video or gameplay oracle; those results retain their separate scopes.

The newline JSON envelope and useful development operations were reviewed from
[psxrecomp's TCP documentation](https://github.com/RetroPortingToolKit/psxrecomp/blob/31df2e1e0e0a6525733e68ff70e72ecbef84bb09/docs/TCP_COMMANDS.md)
and the
[snesrecomp server interface](https://github.com/RetroPortingToolKit/snesrecomp/blob/a410b7be2620b20d7ee03a031db54e97b5854b7b/runner/src/debug_server.c).
This server and its strict parser are original C++ implementations. Reference
implementation code was not copied across the projects' license boundaries.
Only the documented subset above is supported; command compatibility with
either reference server is not implied.
