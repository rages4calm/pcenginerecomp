"""Build or qualify a wider world view using an authored card and scene."""
from argparse import ArgumentParser
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pcerecomp.project import DISPLAY_SHADERS, sha256, source_identity
from scripts.dev_client import DevClient, write_capture

WRAM = 0x1F0000
PLAYER_OFFSET = 0x40


def require(condition, message):
    if not condition:
        raise ValueError(message)


def command(binary, card, view, shader, *, verify):
    steps, ticks, seconds = (25_000_000, 180_000_000, 90) if verify else (1_000_000_000, 2_600_000_000, 120)
    return [str(binary), "--hucard-reset", "base", str(card), str(steps), str(ticks), "native",
            "--rom-header", "none", "--rom-encoding", "linear", "--audio-output", "off",
            "--port-view", view, "--display-shader", shader, "--wall-seconds", str(seconds)]


@contextmanager
def session(argv, output, name, environment):
    log = output / f"{name}.stderr"
    with (output / f"{name}.stdout").open("xb") as stdout, log.open("xb") as stderr:
        process = subprocess.Popen(argv, env=environment, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 10
            while True:
                message = log.read_text(encoding="utf-8", errors="replace")
                match = re.search(r"PCE_DEV_PORT=(\d+)", message)
                if match:
                    break
                require(process.poll() is None and time.monotonic() < deadline, f"{name} did not start: {message}")
                time.sleep(0.02)
            with DevClient(int(match[1]), timeout=30, journal=output / f"{name}.tcp.jsonl") as client:
                yield client
                client.call("quit")
            require(process.wait(timeout=10) == 0, f"{name} refused or faulted")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def guest_state(client):
    status = client.call("status")
    require(status["paused"], "State comparison requires a paused guest")
    ram = client.read_memory_block(WRAM, 8192)
    metadata, pixels = client.capture("guest")
    host = status["host"]
    return dict(frame=status["frame"], ticks=status["ticks"], frame_ticks=metadata["frame_ticks"],
                cpu=host["cpu"], native=host["native_steps"], interpreted=host["interpreter_steps"],
                player=ram[PLAYER_OFFSET], wram_sha256=hashlib.sha256(ram).hexdigest(),
                guest_sha256=hashlib.sha256(pixels).hexdigest(),
                guest_size=[metadata["width"], metadata["height"]])


def drive(client, scene_width=None):
    results = []
    route = ((0x20, 8), (0x80, 3), (0, 2), (0x20, 128), (0x80, 260), (0, 2))
    for buttons, frames in route:
        client.call("set_input", port=0, mask=buttons)
        client.advance(frames)
        state = guest_state(client)
        results.append(state)
        if scene_width and state["player"] in (0, 255):
            x = 0 if state["player"] == 0 else scene_width - 2
            require(scene_pixel(client.capture("present"), scene_width, x, 121) == bytes((236, 107, 97)),
                    "The camera or player sprite escaped the room edge")
    return results


def scene_pixel(capture, scene_width, x, y):
    metadata, rgb = capture
    width, height = metadata["width"], metadata["height"]
    # The example qualifies in a window taller than either fitted scene.
    scene_height = width * 180 // scene_width
    require(scene_height <= height, "Qualification expects a width-fitted viewport")
    px = int((x + 0.5) * width / scene_width)
    py = int((height - scene_height) / 2 + (y + 0.5) * scene_height / 180)
    offset = (py * width + px) * 3
    return rgb[offset:offset + 3]


def qualify(binary, card, output, gpu_driver):
    output.mkdir(parents=True, exist_ok=False)
    identities = dict(tool=source_identity(ROOT), binary=sha256(binary), card=sha256(card))
    context = hashlib.sha256(json.dumps(identities, sort_keys=True).encode("utf-8")).hexdigest()
    checkpoint = "start.pcec"
    environment = os.environ.copy()
    if gpu_driver:
        for key in ("SDL_VIDEODRIVER", "SDL_RENDER_DRIVER"):
            environment.pop(key, None)
        environment["SDL_GPU_DRIVER"] = gpu_driver
    else:
        environment.update(SDL_VIDEODRIVER="dummy", SDL_RENDER_DRIVER="software")

    def arguments(view, shader, *, restore=False):
        argv = command(binary, card, view, shader, verify=True) + [
            "--hidden", "on", "--unthrottled", "on", "--dev-port", "0", "--dev-start-paused", "on",
            "--checkpoint-dir", str(output), "--checkpoint-context", context,
        ]
        return argv + ["--checkpoint-load", checkpoint] if restore else argv

    with session(arguments("guest", "off"), output, "guest", environment) as client:
        client.advance(4)
        start = guest_state(client)
        require(start["player"] == 128, "Authored scene did not start at world x=256")
        client.call("save_checkpoint", name=checkpoint)
        guest_capture = client.capture("present")
        baseline = drive(client)
        client.call("save_checkpoint", name="guest-end.pcec")
    positions = [row["player"] for row in baseline]
    require(positions[:3] == [152, 143, 143] and positions[3:] == [255, 0, 0],
            f"Authored input and room-edge endpoints differ: {positions}")
    require(start["native"] > 0 and all(row["interpreted"] == 0 for row in [start, *baseline]),
            "Expected only native retirement on the authored guest route")
    end_hash = sha256(output / "guest-end.pcec")

    captures = {}
    variants = [("4:3", "off"), ("16:9", "off")]
    if gpu_driver:
        variants.extend(("16:9", shader) for shader in DISPLAY_SHADERS if shader != "off")
    for view, shader in variants:
        name = f"{view.replace(':', 'x')}-{shader}"
        with session(arguments(view, shader, restore=True), output, name, environment) as client:
            require(guest_state(client) == start, f"Guest state differs after {name} checkpoint load")
            captures[name] = client.capture("present")
            width = (240 if view == "4:3" else 320) if shader == "off" else None
            require(drive(client, width) == baseline, f"Guest route differs with {name}")
            ending = f"{name}-end.pcec"
            client.call("save_checkpoint", name=ending)
            require(sha256(output / ending) == end_hash, f"Ending checkpoint bytes differ with {name}")
        write_capture(output / f"{name}.png", *captures[name])

    narrow, wide = captures["4x3-off"], captures["16x9-off"]
    require(wide[1] != guest_capture[1], "Port presentation matches the unmodified VDC view")
    require(scene_pixel(wide, 320, 16, 116) == bytes((211, 153, 85)), "Missing left landmark")
    require(scene_pixel(wide, 320, 304, 116) == bytes((126, 205, 155)), "Missing right landmark")
    for y in range(24, 180):
        for x in range(240):
            require(scene_pixel(narrow, 240, x, y) == scene_pixel(wide, 320, x + 40, y),
                    f"Overlapping world pixels differ at {x},{y}")
    require(scene_pixel(narrow, 240, 185, 9) == scene_pixel(wide, 320, 265, 9) == bytes((24, 36, 50)),
            "Right HUD did not move to the new viewport edge")
    hashes = {name: hashlib.sha256(capture[1]).hexdigest() for name, capture in captures.items()}
    require(len(set(hashes.values())) == len(hashes), "Presentation variants must have distinct pixels")
    require(sha256(binary) == identities["binary"] and sha256(card) == identities["card"]
            and source_identity(ROOT) == identities["tool"], "Verification inputs changed")
    receipt = dict(passed=True, inputs=identities, renderer=gpu_driver or "SDL software",
                   checkpoint_sha256=sha256(output / checkpoint), state_at_restore=start,
                   end_checkpoint_sha256=end_hash, route_samples=baseline, present_sha256=hashes,
                   overlap_pixels=240 * (180 - 24))
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"Passed {len(variants)} restored views, {receipt['overlap_pixels']:,} shared world pixels, "
          f"{baseline[-1]['native']:,} native instructions per complete route.")


def main():
    parser = ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("generate").add_argument("generated", type=Path)
    for action in ("play", "qualify"):
        args = sub.add_parser(action)
        args.add_argument("generated", type=Path)
        args.add_argument("--binary", required=True, type=Path)
        if action == "play":
            args.add_argument("--view", choices=("guest", "4:3", "16:9"), default="16:9")
            args.add_argument("--shader", choices=DISPLAY_SHADERS, default="off")
            args.add_argument("--fullscreen", action="store_true")
        else:
            args.add_argument("--out", required=True, type=Path)
            args.add_argument("--gpu-driver", choices=("direct3d12", "vulkan"))
    args = parser.parse_args()
    generated = args.generated.resolve()
    if args.action == "generate":
        from fixture import emit_fixture
        emit_fixture(generated)
    else:
        binary, card = args.binary.resolve(strict=True), generated / "authored-card.pce"
        if args.action == "qualify":
            qualify(binary, card, args.out.resolve(), args.gpu_driver)
        else:
            launch = command(binary, card, args.view, args.shader, verify=False)
            if args.fullscreen:
                launch.extend(("--fullscreen", "on"))
            subprocess.run(launch, check=True)


if __name__ == "__main__":
    main()
