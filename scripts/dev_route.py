"""Run finite, data-only state predicates over one paused DevClient connection.

Schema 1 plans contain max_frames, max_seconds and steps (assert/wait/pulse).
Predicates are status, memory, source, all or any objects. No expression language,
memory edits, implicit resume, or implicit pause is provided. Frame limits bound
requested advances; a host overshoot is recorded and stops the route.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
import sys
import time

try:
    from scripts.dev_client import DevClient, DevError
except ModuleNotFoundError:  # Direct invocation from scripts/.
    from dev_client import DevClient, DevError


MAX_FRAMES = 10_000_000
MAX_STEPS = 256
MAX_DEPTH = 16
MAX_LEAVES = 256
QUIESCENCE_IGNORED_PATHS = (("id",), ("host", "audio_output", "host"))


class RouteError(ValueError):
    """A route guard, predicate, or finite execution limit failed."""


def _keys(value, required, optional=()):
    if type(value) is not dict or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise RouteError(f"expected fields {sorted(required)}, optional {sorted(optional)}")


def _int(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise RouteError(f"{name} requires integer {low}..{high}")
    return value


def _number(value, name):
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
        raise RouteError(f"{name} requires a finite number")
    return value


def _hex(value, maximum=256):
    if type(value) is not str or not 2 <= len(value) <= maximum * 2 or len(value) % 2 or any(
            c not in "0123456789abcdefABCDEF" for c in value):
        raise RouteError(f"bytes require 1..{maximum} contiguous hex pairs")
    return bytes.fromhex(value)


def _predicate(value, leaves, depth=0):
    if depth > MAX_DEPTH or type(value) is not dict or len(value) != 1:
        raise RouteError("predicate requires one operator within depth limit")
    kind, spec = next(iter(value.items()))
    if kind in ("all", "any"):
        if type(spec) is not list or not 1 <= len(spec) <= MAX_LEAVES:
            raise RouteError("all/any requires 1..256 predicates")
        for child in spec:
            _predicate(child, leaves, depth + 1)
        return
    leaves[0] += 1
    if leaves[0] > MAX_LEAVES:
        raise RouteError("plan exceeds 256 predicate leaves")
    if kind == "status":
        if type(spec) is not dict:
            raise RouteError("status requires an object")
        if "eq" in spec:
            _keys(spec, ("path", "eq"))
            if type(spec["eq"]) not in (int, float, bool, str, type(None)):
                raise RouteError("status equality requires a typed scalar")
            if type(spec["eq"]) in (int, float):
                _number(spec["eq"], "eq")
        else:
            _keys(spec, ("path", "min", "max"))
            if _number(spec["min"], "min") > _number(spec["max"], "max"):
                raise RouteError("status range is reversed")
        path = spec["path"]
        if type(path) is not list or not 1 <= len(path) <= 16 or path[0] in ("id", "ok"):
            raise RouteError("status path requires 1..16 data keys/indices")
        for item in path:
            if not ((type(item) is str and 1 <= len(item) <= 64) or
                    (type(item) is int and 0 <= item <= 65535)):
                raise RouteError("invalid status path component")
    elif kind == "memory":
        if type(spec) is not dict:
            raise RouteError("memory requires an object")
        if "bytes" in spec:
            _keys(spec, ("address", "bytes"), ("mask",))
            length = len(_hex(spec["bytes"]))
            if "mask" in spec and len(_hex(spec["mask"])) != length:
                raise RouteError("memory mask extent differs from bytes")
        else:
            _keys(spec, ("address", "size", "endian", "min", "max"))
            length = _int(spec["size"], 1, 4, "size")
            if length not in (1, 2, 4) or spec["endian"] not in ("little", "big"):
                raise RouteError("memory integer requires size 1/2/4 and little/big endian")
            _int(spec["min"], 0, (1 << (8 * length)) - 1, "min")
            _int(spec["max"], spec["min"], (1 << (8 * length)) - 1, "max")
        _int(spec["address"], 0, 0x200000 - length, "physical address")
    elif kind == "source":
        _keys(spec, ("pc", "mpr", "bytes", "physical"))
        _int(spec["pc"], 0, 65535, "source pc")
        if type(spec["mpr"]) is not list or len(spec["mpr"]) != 8:
            raise RouteError("source requires all eight MPRs")
        for bank in spec["mpr"]:
            _int(bank, 0, 255, "MPR")
        data = _hex(spec["bytes"], 7)
        if type(spec["physical"]) is not list or len(spec["physical"]) != len(data):
            raise RouteError("source physical extent differs from bytes")
        for offset, address in enumerate(spec["physical"]):
            _int(address, 0, 0x1fffff, "source physical address")
            logical = (spec["pc"] + offset) & 65535
            if address != (spec["mpr"][logical >> 13] << 13) | (logical & 8191):
                raise RouteError("source physical identity differs from PC/MPR translation")
    else:
        raise RouteError(f"unknown predicate {kind!r}")


def validate_plan(plan):
    """Validate the entire plan without contacting or mutating a host; return a copy."""
    _keys(plan, ("schema", "max_frames", "max_seconds", "steps"))
    _int(plan["schema"], 1, 1, "schema")
    _int(plan["max_frames"], 0, MAX_FRAMES, "max_frames")
    if not 0 < _number(plan["max_seconds"], "max_seconds") <= 3600:
        raise RouteError("max_seconds requires (0,3600]")
    if type(plan["steps"]) is not list or not 1 <= len(plan["steps"]) <= MAX_STEPS:
        raise RouteError("steps requires 1..256 entries")
    leaves = [0]
    for step in plan["steps"]:
        if type(step) is not dict:
            raise RouteError("step requires an object")
        op = step.get("op")
        if op == "assert":
            _keys(step, ("op", "predicate"))
        elif op == "wait":
            _keys(step, ("op", "predicate", "poll_frames", "max_frames", "port", "mask"))
            _int(step["poll_frames"], 1, 600, "poll_frames")
            _int(step["max_frames"], 1, MAX_FRAMES, "step max_frames")
        elif op == "pulse":
            _keys(step, ("op", "frames", "port", "mask"))
            _int(step["frames"], 1, 600, "pulse frames")
        else:
            raise RouteError(f"unknown step {op!r}")
        if op in ("wait", "pulse"):
            _int(step["port"], 0, 4, "controller port")
            _int(step["mask"], 0, 4095, "controller mask")
        if "predicate" in step:
            _predicate(step["predicate"], leaves)
    return copy.deepcopy(plan)


def _path(status, path):
    value = status
    for part in path:
        if type(value) is dict and type(part) is str and part in value:
            value = value[part]
        elif type(value) is list and type(part) is int and 0 <= part < len(value):
            value = value[part]
        else:
            raise RouteError(f"unknown status path {path!r}")
    return value


def _memory_ranges(predicate):
    kind, spec = next(iter(predicate.items()))
    if kind in ("all", "any"):
        return set().union(*(_memory_ranges(p) for p in spec))
    if kind == "memory":
        return {(spec["address"], len(bytes.fromhex(spec["bytes"])) if "bytes" in spec else spec["size"])}
    return set()


def _quiescence_projection(status):
    """Ignore transport identity and SDL audio presentation telemetry only.

    Guest PCM hashes/counters, processing history, device flags and all unknown
    future fields outside the exact presentation subtree remain compared.
    The original replies are retained in the receipt without this projection.
    """
    result = copy.deepcopy(status)
    for path in QUIESCENCE_IGNORED_PATHS:
        parent = result
        for key in path[:-1]:
            if type(parent) is not dict or key not in parent:
                break
            parent = parent[key]
        else:
            if type(parent) is dict:
                parent.pop(path[-1], None)
    return result


def _same_typed_value(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_same_typed_value(left[key], right[key]) for key in left)
    if type(left) is list:
        return len(left) == len(right) and all(_same_typed_value(a, b) for a, b in zip(left, right))
    return left == right


def _evaluate(predicate, observation):
    kind, spec = next(iter(predicate.items()))
    if kind in ("all", "any"):
        # Evaluate all branches so a malformed/missing observation cannot hide
        # behind an already true/false branch.
        matches = [_evaluate(p, observation) for p in spec]
        return all(matches) if kind == "all" else any(matches)
    status = observation["status"]
    if kind == "status":
        actual = _path(status, spec["path"])
        if "eq" in spec:
            if type(actual) is not type(spec["eq"]):
                raise RouteError("status equality type differs from predicate")
            return actual == spec["eq"]
        return spec["min"] <= _number(actual, "observed status range") <= spec["max"]
    if kind == "memory":
        length = len(bytes.fromhex(spec["bytes"])) if "bytes" in spec else spec["size"]
        data = next(bytes.fromhex(row["data"]) for row in observation["memory"]
                    if (row["address"], row["length"]) == (spec["address"], length))
        if "bytes" in spec:
            expected = bytes.fromhex(spec["bytes"])
            mask = bytes.fromhex(spec["mask"]) if "mask" in spec else bytes([255]) * length
            return all((a & m) == (b & m) for a, b, m in zip(data, expected, mask))
        return spec["min"] <= int.from_bytes(data, spec["endian"]) <= spec["max"]
    cpu = _path(status, ["host", "cpu"])
    pc = _int(_path(status, ["host", "pc"]), 0, 65535, "observed source pc")
    mpr = _path(status, ["host", "cpu", "mpr"])
    physical = _path(status, ["host", "cpu", "instruction_physical"])
    data = _path(status, ["host", "cpu", "instruction_bytes"])
    if type(mpr) is not list or len(mpr) != 8 or type(physical) is not list or len(physical) != 7 or type(data) is not list or len(data) != 7:
        raise RouteError("incomplete observed source identity")
    for bank in mpr:
        _int(bank, 0, 255, "observed MPR")
    for offset, address in enumerate(physical):
        logical = (pc + offset) & 65535
        if _int(address, 0, 0x1fffff, "observed physical") != (mpr[logical >> 13] << 13) | (logical & 8191):
            raise RouteError("observed source translation inconsistent")
    if _int(cpu.get("physical_pc"), 0, 0x1fffff, "observed physical pc") != physical[0]:
        raise RouteError("observed physical PC inconsistent")
    for byte in data:
        if byte is not None:
            _int(byte, 0, 255, "observed source byte")
    size = len(bytes.fromhex(spec["bytes"]))
    return (pc == spec["pc"] and mpr == spec["mpr"] and physical[:size] == spec["physical"]
            and data[:size] == list(bytes.fromhex(spec["bytes"])))


def run_plan(client, plan, *, clock=time.monotonic):
    """Return a success/failure receipt, releasing only input acquired by this run.

    A settled paused host with zero combined masks is required. Observations
    bracket physical reads with equal guest status projections. Raw before/after
    replies are retained; only transport IDs and the exact SDL audio presentation
    subtree host.audio_output.host are excluded from quiescence comparison.
    The caller owns connection lifetime. Cleanup gets at most one extra second
    after the wall deadline so a held port can be released on the same socket.
    """
    started = clock()
    report = {"schema": 1, "ok": False, "advanced_frames": 0, "steps": [],
              "observations": [], "inputs": [], "cleanup": [],
              "quiescence_ignored_paths": [list(path) for path in QUIESCENCE_IGNORED_PATHS]}
    owned = None
    saved_timeout = getattr(client, "timeout", None)
    expected_buttons = [0] * 5
    deadline = started

    def invoke(operation, *args, cleanup=False, **kwargs):
        remaining = deadline - clock()
        if not cleanup and remaining <= 0:
            raise RouteError("route wall deadline reached")
        if saved_timeout is not None:
            client.timeout = min(saved_timeout, 1.0 if cleanup else remaining)
        return operation(*args, **kwargs)

    def status(observation=None, field="status"):
        value = copy.deepcopy(invoke(client.call, "status"))
        report["last_status"] = value
        if observation is not None:
            observation[field] = value
        if type(value) is not dict or value.get("paused") is not True or value.get("local_paused") is not False:
            raise RouteError("route requires settled network pause without local pause")
        _int(value.get("frame"), 0, (1 << 64) - 1, "observed frame")
        _int(value.get("ticks"), 0, (1 << 64) - 1, "observed ticks")
        buttons = _path(value, ["host", "buttons"])
        if type(buttons) is not list or len(buttons) != 5:
            raise RouteError("status requires five combined input masks")
        for mask in buttons:
            _int(mask, 0, 4095, "observed button mask")
        if buttons != expected_buttons:
            raise RouteError("unexpected combined input; local/script/network intent conflicts")
        return value

    def observe(predicate=None):
        observation = {"memory": []}
        report["observations"].append(observation)
        before = status(observation)
        for address, length in sorted(_memory_ranges(predicate) if predicate else ()):
            data = invoke(client.read_memory, address, length)
            if type(data) is not bytes or len(data) != length:
                raise RouteError("physical memory observation extent/type differs")
            observation["memory"].append({"address": address, "length": length, "data": data.hex()})
        after = status(observation, "status_after")
        if not _same_typed_value(_quiescence_projection(before), _quiescence_projection(after)):
            raise RouteError("host changed during paused observation")
        return observation

    def release(*, cleanup=False):
        nonlocal owned
        if owned is not None:
            port = owned
            result = invoke(client.call, "clear_input", port=port, cleanup=cleanup)
            expected_buttons[port] = 0
            owned = None
            report["cleanup"].append({"port": port, "accepted": True, "response": result})

    def hold(step):
        nonlocal owned
        # Claim the port before sending: a failed acknowledgement may still
        # follow an accepted request, so finally must attempt scoped release.
        owned = step["port"]
        result = invoke(client.call, "set_input", port=owned, mask=step["mask"])
        expected_buttons[owned] = step["mask"]
        report["inputs"].append({"port": owned, "mask": step["mask"], "accepted": True,
                                  "response": result, "guest_latch_sample_proven": False})

    def advance(frames, row):
        if report["advanced_frames"] + frames > validated["max_frames"]:
            raise RouteError("route frame limit would be exceeded")
        before = status()["frame"]
        # Retain any actual advance response even if a subsequent guard fails.
        result = copy.deepcopy(invoke(client.advance, frames))
        report["last_advance"] = result
        actual = _int(result.get("frame"), before, (1 << 64) - 1, "advanced frame") - before
        report["advanced_frames"] += actual
        row["advanced_frames"] += actual
        if actual != frames:
            raise RouteError("host frame advancement differs from requested bound")

    try:
        validated = validate_plan(plan)
        report["plan"] = validated
        deadline = started + validated["max_seconds"]
        predicates = [step["predicate"] for step in validated["steps"] if "predicate" in step]
        preflight_predicate = {"all": predicates} if predicates else None
        initial = observe(preflight_predicate)
        initial["phase"] = "preflight"
        if preflight_predicate:
            # Resolve every later path/type and read every later physical range
            # before acquiring any input. Predicate truth is step-specific.
            _evaluate(preflight_predicate, initial)
        for index, step in enumerate(validated["steps"]):
            row = {"index": index, "op": step["op"], "ok": False, "advanced_frames": 0}
            report["steps"].append(row)
            observation = initial if index == 0 else observe(step.get("predicate"))
            if step["op"] == "assert":
                if not _evaluate(step["predicate"], observation):
                    raise RouteError("assert predicate is false")
            elif step["op"] == "wait":
                matched = _evaluate(step["predicate"], observation)
                row["initially_satisfied"] = matched
                if not matched:
                    if report["advanced_frames"] >= validated["max_frames"]:
                        raise RouteError("route frame limit reached before input")
                    hold(step)
                    while not matched:
                        remaining = min(step["max_frames"] - row["advanced_frames"],
                                        validated["max_frames"] - report["advanced_frames"])
                        if remaining <= 0:
                            raise RouteError("wait frame limit reached with false predicate")
                        advance(min(step["poll_frames"], remaining), row)
                        observation = observe(step["predicate"])
                        matched = _evaluate(step["predicate"], observation)
                    release()
                    observe()
            else:
                if report["advanced_frames"] + step["frames"] > validated["max_frames"]:
                    raise RouteError("route frame limit would be exceeded before input")
                hold(step)
                advance(step["frames"], row)
                observe()
                release()
                observe()
            row["ok"] = True
        if clock() >= deadline:
            raise RouteError("route wall deadline reached")
        report["ok"] = True
    except (DevError, OSError, ValueError, TypeError, OverflowError, RecursionError) as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        try:
            release(cleanup=True)
        except (DevError, OSError, ValueError, TypeError) as error:
            report["ok"] = False
            report["cleanup"].append({"port": owned, "accepted": False, "error": str(error)})
            report.setdefault("error", {"type": type(error).__name__, "message": "input release failed: " + str(error)})
        if saved_timeout is not None:
            client.timeout = saved_timeout
        report["elapsed_seconds"] = max(0, clock() - started)
    return report


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RouteError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _constant(value):
    raise RouteError(f"nonfinite JSON number {value}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)
    # Reserve a new receipt BEFORE any host mutation. Even invalid JSON or a
    # connection failure gets a structured receipt; existing files stay intact.
    try:
        stream = args.receipt.open("x", encoding="utf-8", newline="\n")
    except OSError as error:
        print(f"development route: {error}", file=sys.stderr)
        return 1
    with stream:
        try:
            if args.plan.stat().st_size > 1_048_576:
                raise RouteError("plan exceeds 1 MiB")
            plan = validate_plan(json.loads(args.plan.read_text(encoding="utf-8"), object_pairs_hook=_object,
                                            parse_constant=_constant))
            with DevClient(args.port, timeout=args.timeout) as client:
                report = run_plan(client, plan)
        except (DevError, OSError, ValueError, RecursionError) as error:
            report = {"schema": 1, "ok": False, "advanced_frames": 0, "observations": [],
                      "inputs": [], "steps": [], "cleanup": [],
                      "quiescence_ignored_paths": [list(path) for path in QUIESCENCE_IGNORED_PATHS],
                      "error": {"type": type(error).__name__, "message": str(error)}}
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"ok": report["ok"], "receipt": str(args.receipt)}, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
