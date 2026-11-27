"""Qualify disc-byte origins through real authored CD reads and checkpoints."""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pcerecomp.project import sha256, source_identity
from scripts.dev_client import DevClient

FIXTURE = ROOT / "examples/live-overlays/fixture.py"
spec = importlib.util.spec_from_file_location("authored_cd_fixture", FIXTURE)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


@contextmanager
def session(runner, output, name, tracked, *, restore=False):
    directory = output / name
    directory.mkdir()
    argv = [str(runner), "--system-card-reset", "standard", str(output / "firmware.bin"),
            "50000000", "100000000", "hybrid", "--disc", str(output / "disc.iso"),
            "--video-output", "continuous", "--audio-output", "off", "--wall-seconds", "60",
            "--dev-port", "0", "--dev-start-paused", "on", "--dev-reference", "on",
            "--dev-memory-write", "on", "--checkpoint-dir", str(output / "checkpoints"),
            "--checkpoint-context", hashlib.sha256(b"authored-disc-origin-example-v1").hexdigest()]
    if tracked:
        argv.extend(("--disc-origin", "on"))
    if restore:
        argv.extend(("--checkpoint-load", "ready-1.pcec"))
    if name == "untracked":
        argv.extend(("--code-capture", str(directory / "capture.jsonl"),
                     "--capture-profile", "extended", "--capture-limit", "65536"))
    write(directory / "launch.json", dict(argv=argv, runner_sha256=sha256(runner)))
    environment = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_RENDER_DRIVER="software", SDL_AUDIODRIVER="dummy")
    with (directory / "stdout.log").open("xb") as stdout, (directory / "stderr.log").open("xb") as stderr:
        process = subprocess.Popen(argv, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL,
                                   env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 15
            while True:
                text = (directory / "stderr.log").read_text(encoding="utf-8", errors="replace")
                match = re.search(r"PCE_DEV_PORT=(\d+)", text)
                if match:
                    break
                require(process.poll() is None and time.monotonic() < deadline, text or "TCP startup timed out")
                time.sleep(0.02)
            with DevClient(int(match[1]), journal=directory / "wire.jsonl") as client:
                yield client, directory
                client.call("quit")
            require(process.wait(timeout=15) == 0, f"{name} host failed")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


def origins(client, address, length):
    values, epoch = [], None
    for start in range(0, length, 256):
        count = min(256, length - start)
        report = client.call("disc_origin", address=address + start, length=count)["disc_origin"]
        require(report["schema"] == 1 and report["address"] == address + start and report["length"] == count,
                "Origin response geometry differs")
        require(len(report["offsets"]) == count, "Origin response byte count differs")
        if epoch is None:
            epoch = report["epoch"]
        require(report["epoch"] == epoch, "Origin epoch changed while paused")
        values.extend(report["offsets"])
    return dict(epoch=epoch, offsets=values)


def wait_stage(client, wanted, *, reference):
    for _ in range(50):
        stage = client.read_memory(0x1F0000, 1)[0]
        if stage == wanted:
            return
        require(stage < wanted, "Authored stage passed its expected gate")
        client.advance(1, reference=reference)
    raise ValueError(f"Authored loader did not reach stage {wanted}")


def state(client, phase, *, finished=False):
    status = client.call("status")
    wram = client.read_memory_block(0x1F0000, 8192)
    cd = client.read_memory_block(0x100000, 65536)
    require(wram == fixture.expected_wram(phase, 0, released=finished, finished=finished), "Literal WRAM differs")
    require(cd == fixture.expected_cd(phase), "Literal CD RAM differs")
    return dict(frame=status["frame"], ticks=status["ticks"], cpu=status["host"]["cpu"],
                native=status["host"]["native_steps"], interpreted=status["host"]["interpreter_steps"],
                wram_sha256=hashlib.sha256(wram).hexdigest(), cd_sha256=hashlib.sha256(cd).hexdigest())


def run(runner, output, *, native=False):
    output.mkdir(parents=True, exist_ok=False)
    (output / "checkpoints").mkdir()
    (output / "firmware.bin").write_bytes(fixture.firmware()[0])
    (output / "disc.iso").write_bytes(fixture.disc())
    identity = source_identity(ROOT)
    binary_hash = sha256(runner)
    baseline = []
    with session(runner, output, "untracked", False) as (client, directory):
        for phase in (1, 2):
            wait_stage(client, phase, reference=not native)
            baseline.append(state(client, phase))
            client.write_memory(0x1F0001, bytes((phase,)), bytes((phase - 1,)))
        wait_stage(client, 3, reference=not native)
        baseline.append(state(client, 2, finished=True))
        client.call("save_checkpoint", name="untracked-end.pcec")
    reports = []
    with session(runner, output, "tracked", True) as (client, directory):
        for phase in (1, 2):
            wait_stage(client, phase, reference=not native)
            require(state(client, phase) == baseline[phase - 1], "Tracking changed guest execution")
            report = origins(client, 0x100000, 2048)
            require(report["offsets"] == list(range(phase * 2048, (phase + 1) * 2048)),
                    "CD stream byte origins differ from literal sector positions")
            require(origins(client, 0x100800, 256)["offsets"] == [None] * 256, "Untouched RAM gained provenance")
            reports.append(report)
            write(directory / f"sector-{phase}-origins.json", report)
            if phase == 1:
                client.call("save_checkpoint", name="ready-1.pcec")
                # Equal bytes still represent a new host write and lose origin.
                value = client.read_memory(0x100020, 1)
                client.write_memory(0x100020, value, value)
                require(origins(client, 0x100020, 1)["offsets"] == [None], "Equal host write kept a stale origin")
            client.write_memory(0x1F0001, bytes((phase,)), bytes((phase - 1,)))
        wait_stage(client, 3, reference=not native)
        require(state(client, 2, finished=True) == baseline[-1], "Tracking changed final guest execution")
        # The additional diagnostic write changes host mutation counters, so
        # byte-identical end checkpoints are checked on the untouched replay.
    with session(runner, output, "restored", True, restore=True) as (client, directory):
        require(state(client, 1) == baseline[0], "Restored guest state differs")
        require(origins(client, 0x100000, 2048)["offsets"] == [None] * 2048,
                "Restore inherited origin claims from another observer epoch")
        client.write_memory(0x1F0001, b"\x01", b"\0")
        wait_stage(client, 2, reference=not native)
        require(state(client, 2) == baseline[1], "Restored continuation differs")
        require(origins(client, 0x100000, 2048)["offsets"] == list(range(4096, 6144)),
                "Restored read did not reacquire sector-two provenance")
        client.write_memory(0x1F0001, b"\x02", b"\x01")
        wait_stage(client, 3, reference=not native)
        require(state(client, 2, finished=True) == baseline[-1], "Restored final state differs")
        client.call("save_checkpoint", name="restored-end.pcec")
    require(sha256(output / "checkpoints/restored-end.pcec") == sha256(output / "checkpoints/untracked-end.pcec"),
            "Observer reset/continuation changed serialized checkpoint bytes")
    require(source_identity(ROOT) == identity and sha256(runner) == binary_hash, "Verification source changed")
    work = dict(native=baseline[-1]["native"], interpreted=baseline[-1]["interpreted"])
    require((work["native"] > 0 and work["interpreted"] == 0) if native
            else (work["native"] == 0 and work["interpreted"] > 0), "Actual execution tier differs")
    receipt = dict(passed=True, tool=identity, runner_sha256=binary_hash,
                   fixture_sha256=sha256(FIXTURE), firmware_sha256=sha256(output / "firmware.bin"),
                   disc_sha256=sha256(output / "disc.iso"), samples=baseline,
                   observed_disc_bytes=4096, restored_reacquired_bytes=2048,
                   equal_host_write_invalidated=True, checkpoint_bytes_equal=True,
                   actual_work=work, policy="native" if native else "interpreter",
                   scope="Authored CD READ route; origins are host diagnostics learned within an epoch")
    write(output / "receipt.json", receipt)
    print(json.dumps(receipt, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--native", action="store_true",
                        help="Require an entirely native route using the supplied generated executable")
    args = parser.parse_args()
    run(args.runner.resolve(strict=True), args.out.resolve(), native=args.native)


if __name__ == "__main__":
    main()
