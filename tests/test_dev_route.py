"""Authored route predicates, guarded input ownership and finite stop controls."""
import copy
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts.dev_client import DevClient, DevError
from scripts.dev_route import RouteError, main, run_plan, validate_plan


def source():
    return {"pc": 8191, "mpr": [2, 3, 4, 5, 6, 7, 8, 9], "bytes": "a980",
            "physical": [24575, 24576]}


def status():
    origin = source()
    return {"id": 1, "ok": True, "frame": 10, "ticks": 100,
            "paused": True, "local_paused": False,
            "host": {"pc": origin["pc"], "native_steps": 0,
                     "buttons": [0] * 5, "flag": True,
                     "cpu": {"mpr": origin["mpr"], "physical_pc": 24575,
                             "instruction_physical": [24575] + list(range(24576, 24582)),
                             "instruction_bytes": [169, 128, 0, 0, 0, 0, 0]}}}


def equality(path, value):
    return {"status": {"path": path, "eq": value}}


def wait(predicate=None, **changes):
    return {"op": "wait", "predicate": predicate or equality(["frame"], 15),
            "poll_frames": 3, "max_frames": 5, "port": 2, "mask": 8, **changes}


def pulse(**changes):
    return {"op": "pulse", "port": 2, "mask": 8, "frames": 3, **changes}


def plan(*steps, **changes):
    return {"schema": 1, "max_frames": 100, "max_seconds": 30,
            "steps": list(steps) or [{"op": "assert", "predicate": equality(["frame"], 10)}], **changes}


class FakeClient:
    def __init__(self):
        self.timeout = 20
        self.state = status()
        self.calls = []
        self.memory = {100: b"\x12\x34\x56\x78"}
        self.advance_error = None
        self.after_advance = None
        self.after_memory = None
        self.release_error = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def call(self, command, **args):
        self.calls.append((command, args))
        if command == "status":
            return copy.deepcopy(self.state)
        if command == "set_input":
            self.state["host"]["buttons"][args["port"]] = args["mask"]
        elif command == "clear_input":
            if self.release_error:
                raise DevError("authored release failure")
            self.state["host"]["buttons"][args["port"]] = 0
        else:
            raise AssertionError(command)
        return {"id": len(self.calls), "ok": True}

    def advance(self, frames):
        self.calls.append(("advance", {"frames": frames}))
        if self.advance_error:
            raise self.advance_error
        self.state["frame"] += frames
        self.state["ticks"] += frames * 10
        self.state["host"]["native_steps"] += frames * 2
        if self.after_advance:
            self.after_advance(self)
        return copy.deepcopy(self.state)

    def read_memory(self, address, length):
        self.calls.append(("read_memory", {"address": address, "length": length}))
        result = self.memory[address][:length]
        if self.after_memory:
            self.after_memory(self)
        return result

    @property
    def mutations(self):
        return [(name, args) for name, args in self.calls if name in ("set_input", "clear_input", "advance")]


class RouteTests(unittest.TestCase):
    def test_full_plan_validated_before_any_contact(self):
        client = FakeClient()
        result = run_plan(client, plan(pulse(), {"op": "eval", "code": "arbitrary"}))
        self.assertFalse(result["ok"])
        self.assertEqual(client.calls, [])
        self.assertEqual(result["advanced_frames"], 0)

    def test_later_unknown_runtime_path_preflight_prevents_earlier_pulse(self):
        client = FakeClient()
        result = run_plan(client, plan(pulse(), {"op": "assert", "predicate": equality(["host", "missing"], 1)}))
        self.assertFalse(result["ok"])
        self.assertEqual(client.mutations, [])
        self.assertEqual(result["advanced_frames"], 0)

    def test_later_unreadable_memory_preflight_prevents_earlier_pulse(self):
        client = FakeClient()
        def read(address, length):
            raise DevError("authored inaccessible physical bank")
        client.read_memory = read
        result = run_plan(client, plan(pulse(), {"op": "assert", "predicate": {"memory": {"address": 200, "bytes": "00"}}}))
        self.assertFalse(result["ok"])
        self.assertEqual(client.mutations, [])
        self.assertEqual(result["advanced_frames"], 0)

    def test_validation_unknown_fields_and_types(self):
        invalid = [plan(schema=True), plan(max_frames=True), plan(max_seconds=float("inf")),
                   plan(max_seconds=0), plan(steps=[]), plan(extra=1),
                   plan(pulse(port=True)), plan(pulse(mask=4096)), plan(pulse(frames=601)),
                   plan(wait(poll_frames=0)), plan(wait(max_frames=0)),
                   plan({"op": "assert", "predicate": {"status": {"path": ["frame"], "eq": []}}}),
                   plan({"op": "assert", "predicate": {"memory": {"address": 100, "bytes": "00", "mask": "ffff"}}}),
                   plan({"op": "assert", "predicate": {"memory": {"address": 0x1fffff, "size": 2, "endian": "little", "min": 0, "max": 1}}}),
                   plan({"op": "assert", "predicate": {"memory": {"address": 100, "size": 3, "endian": "little", "min": 0, "max": 1}}}),
                   plan({"op": "assert", "predicate": {"status": {"path": ["frame"], "min": 2, "max": 1}}}),
                   plan({"op": "assert", "predicate": {"any": []}}),
                   plan({"op": "assert", "predicate": {"source": {**source(), "physical": [0, 1]}}}),
                   plan({"op": "assert", "predicate": {"source": {**source(), "mpr": [2]}}})]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises((RouteError, ValueError)):
                validate_plan(value)

    def test_finite_predicate_and_step_limits(self):
        leaf = equality(["frame"], 10)
        for predicate in ({"all": [leaf] * 257},):
            with self.assertRaises(RouteError):
                validate_plan(plan({"op": "assert", "predicate": predicate}))
        deep = leaf
        for _ in range(18):
            deep = {"all": [deep]}
        with self.assertRaises(RouteError):
            validate_plan(plan({"op": "assert", "predicate": deep}))
        with self.assertRaises(RouteError):
            validate_plan(plan(*([pulse()] * 257)))

    def test_validation_does_not_alias_callers_plan(self):
        original = plan()
        validated = validate_plan(original)
        validated["steps"][0]["predicate"]["status"]["path"].append("unknown")
        self.assertEqual(original["steps"][0]["predicate"]["status"]["path"], ["frame"])

    def test_initial_wait_goal_has_zero_new_work(self):
        client = FakeClient()
        result = run_plan(client, plan(wait(equality(["frame"], 10))))
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["steps"][0]["initially_satisfied"])
        self.assertEqual(result["advanced_frames"], 0)
        self.assertEqual(client.mutations, [])
        self.assertEqual(result["inputs"], [])

    def test_wait_last_poll_is_clamped_to_step_limit(self):
        client = FakeClient()
        result = run_plan(client, plan(wait()))
        self.assertTrue(result["ok"], result)
        self.assertEqual([args["frames"] for name, args in client.calls if name == "advance"], [3, 2])
        self.assertEqual(result["advanced_frames"], 5)
        self.assertEqual(client.state["host"]["buttons"], [0] * 5)
        self.assertEqual(result["inputs"][0]["mask"], 8)
        self.assertFalse(result["inputs"][0]["guest_latch_sample_proven"])
        self.assertEqual([args for name, args in client.calls if name == "clear_input"], [{"port": 2}])

    def test_false_wait_stops_exactly_at_step_cap_and_releases(self):
        client = FakeClient()
        result = run_plan(client, plan(wait(equality(["frame"], 16))))
        self.assertFalse(result["ok"])
        self.assertEqual(result["advanced_frames"], 5)
        self.assertEqual(client.state["frame"], 15)
        self.assertEqual(client.state["host"]["buttons"], [0] * 5)
        self.assertEqual(result["observations"][-1]["status"]["frame"], 15)

    def test_global_cap_clamps_wait_and_stops_later_steps(self):
        client = FakeClient()
        result = run_plan(client, plan(wait(), pulse(), max_frames=4))
        self.assertFalse(result["ok"])
        self.assertEqual(result["advanced_frames"], 4)
        self.assertEqual(len(result["steps"]), 1)
        self.assertEqual(client.state["host"]["buttons"], [0] * 5)

    def test_pulse_budget_failure_precedes_input(self):
        client = FakeClient()
        result = run_plan(client, plan(pulse(), max_frames=2))
        self.assertFalse(result["ok"])
        self.assertEqual(client.mutations, [])

    def test_successful_pulses_scope_each_release(self):
        client = FakeClient()
        result = run_plan(client, plan(pulse(port=1), pulse(port=4, mask=16)))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["advanced_frames"], 6)
        self.assertEqual([args for name, args in client.calls if name == "clear_input"], [{"port": 1}, {"port": 4}])
        self.assertEqual(client.timeout, 20)

    def test_failure_releases_owned_port_only(self):
        client = FakeClient()
        client.advance_error = DevError("authored stopped host")
        result = run_plan(client, plan(pulse(port=3)))
        self.assertFalse(result["ok"])
        self.assertEqual([args for name, args in client.calls if name == "clear_input"], [{"port": 3}])
        self.assertEqual(client.state["host"]["buttons"], [0] * 5)

    def test_failed_set_ack_still_attempts_scoped_release(self):
        client = FakeClient()
        original = client.call
        def call(command, **args):
            result = original(command, **args)
            if command == "set_input":
                raise DevError("authored lost acknowledgement")
            return result
        client.call = call
        result = run_plan(client, plan(pulse(port=3)))
        self.assertFalse(result["ok"])
        self.assertEqual(client.state["host"]["buttons"], [0] * 5)
        self.assertEqual(result["inputs"], [])

    def test_release_failure_is_structured(self):
        client = FakeClient()
        client.release_error = True
        result = run_plan(client, plan(pulse()))
        self.assertFalse(result["ok"])
        self.assertFalse(result["cleanup"][-1]["accepted"])
        self.assertEqual(result["cleanup"][-1]["port"], 2)

    def test_reject_running_local_pause_missing_flags_and_existing_input(self):
        for change in (lambda s: s.update(paused=False), lambda s: s.update(local_paused=True),
                       lambda s: s.pop("local_paused"), lambda s: s["host"]["buttons"].__setitem__(4, 1),
                       lambda s: s["host"]["buttons"].__setitem__(0, True)):
            client = FakeClient()
            change(client.state)
            result = run_plan(client, plan(pulse()))
            self.assertFalse(result["ok"])
            self.assertEqual(client.mutations, [])

    def test_unexpected_input_after_advance_is_not_masked(self):
        client = FakeClient()
        client.after_advance = lambda c: c.state["host"]["buttons"].__setitem__(1, 2)
        result = run_plan(client, plan(pulse()))
        self.assertFalse(result["ok"])
        self.assertEqual(result["advanced_frames"], 3)
        self.assertEqual(client.state["host"]["buttons"], [0, 2, 0, 0, 0])
        self.assertEqual(result["last_status"]["host"]["buttons"], [0, 2, 8, 0, 0])

    def test_actual_host_overshoot_recorded_and_stops(self):
        client = FakeClient()
        client.after_advance = lambda c: c.state.__setitem__("frame", c.state["frame"] + 1)
        result = run_plan(client, plan(pulse(), pulse()))
        self.assertFalse(result["ok"])
        self.assertEqual(result["advanced_frames"], 4)
        self.assertEqual(len(result["steps"]), 1)
        self.assertEqual(client.state["host"]["buttons"], [0] * 5)

    def test_wall_deadline_and_cleanup_timeout(self):
        client = FakeClient()
        now = [0.0]
        seen = []
        def after(c):
            now[0] = 31
        original = client.call
        def call(command, **args):
            seen.append((command, client.timeout))
            return original(command, **args)
        client.call = call
        client.after_advance = after
        result = run_plan(client, plan(pulse()), clock=lambda: now[0])
        self.assertFalse(result["ok"])
        self.assertEqual(result["advanced_frames"], 3)
        self.assertEqual(client.state["host"]["buttons"], [0] * 5)
        self.assertEqual([timeout for cmd, timeout in seen if cmd == "clear_input"], [1.0])
        self.assertEqual(client.timeout, 20)

    def test_memory_exact_mask_endian_and_full_source(self):
        predicate = {"all": [
            {"memory": {"address": 100, "bytes": "12345678"}},
            {"memory": {"address": 100, "bytes": "1030", "mask": "f0f0"}},
            {"memory": {"address": 100, "size": 1, "endian": "little", "min": 18, "max": 18}},
            {"memory": {"address": 100, "size": 2, "endian": "big", "min": 0x1234, "max": 0x1234}},
            {"memory": {"address": 100, "size": 4, "endian": "little", "min": 0x78563412, "max": 0x78563412}},
            {"source": source()}, {"status": {"path": ["host", "buttons", 2], "min": 0, "max": 0}},
            {"any": [equality(["frame"], 11), equality(["host", "flag"], True)]}]}
        client = FakeClient()
        result = run_plan(client, plan(wait(predicate)))
        self.assertTrue(result["ok"], result)
        self.assertEqual(client.mutations, [])
        # Identical physical ranges are read once even if used by several leaves.
        self.assertEqual(len([1 for cmd, _ in client.calls if cmd == "read_memory"]), 3)
        self.assertEqual(result["observations"][0]["memory"][-1]["data"], "12345678")

    def test_all_branches_checked_for_unknown_or_mistyped_status(self):
        for bad in (equality(["host", "unknown"], 0), equality(["host", "flag"], 1),
                    equality(["host", "buttons", 9], 0)):
            result = run_plan(FakeClient(), plan(wait({"any": [equality(["frame"], 10), bad]})))
            self.assertFalse(result["ok"])
            self.assertEqual(result["advanced_frames"], 0)

    def test_memory_changes_during_snapshot_rejected_without_advancement(self):
        client = FakeClient()
        client.after_memory = lambda c: c.state.__setitem__("ticks", c.state["ticks"] + 1)
        result = run_plan(client, plan(wait({"memory": {"address": 100, "bytes": "12"}})))
        self.assertFalse(result["ok"])
        self.assertEqual(client.mutations, [])
        self.assertEqual(result["observations"][0]["memory"][0]["data"], "12")

    def test_presentation_telemetry_changes_allowed_with_both_raw_replies(self):
        client = FakeClient()
        client.state["host"]["audio_output"] = {
            "pcm_hash": 123, "frames": 4, "processing": {"raw_pcm_hash": 456},
            "host": {"queued_frames": 100, "pauses": 0}}
        def change(c):
            c.state["host"]["audio_output"]["host"]["queued_frames"] = 0
            c.state["host"]["audio_output"]["host"]["pauses"] = 1
            c.state["id"] += 1
        client.after_memory = change
        result = run_plan(client, plan(wait({"memory": {"address": 100, "bytes": "12"}})))
        self.assertTrue(result["ok"], result)
        self.assertEqual(client.mutations, [])
        observed = result["observations"][0]
        self.assertEqual(observed["status"]["host"]["audio_output"]["host"], {"queued_frames": 100, "pauses": 0})
        self.assertEqual(observed["status_after"]["host"]["audio_output"]["host"], {"queued_frames": 0, "pauses": 1})
        self.assertEqual(observed["status"]["host"]["audio_output"]["pcm_hash"], 123)
        self.assertEqual(result["quiescence_ignored_paths"], [["id"], ["host", "audio_output", "host"]])

    def test_presentation_projection_preserves_guest_and_unknown_fields(self):
        changes = {
            "pcm_hash": lambda s: s["host"]["audio_output"].__setitem__("pcm_hash", 124),
            "raw_pcm_hash": lambda s: s["host"]["audio_output"]["processing"].__setitem__("raw_pcm_hash", 457),
            "queue": lambda s: s["host"]["audio_output"].__setitem__("pending_pcm_frames", 3),
            "device": lambda s: s["host"]["audio_output"].__setitem__("device_open", False),
            "device_type": lambda s: s["host"]["audio_output"].__setitem__("device_open", 1),
            "pcm_type": lambda s: s["host"]["audio_output"].__setitem__("pcm_hash", 123.0),
            "new_audio_field": lambda s: s["host"]["audio_output"].__setitem__("new_field", 1),
            "new_host_field": lambda s: s["host"].__setitem__("new_field", 1),
            "ticks": lambda s: s.__setitem__("ticks", s["ticks"] + 1),
            "frame": lambda s: s.__setitem__("frame", s["frame"] + 1),
            "cpu": lambda s: s["host"]["cpu"].__setitem__("a", 1),
            "source": lambda s: s["host"]["cpu"]["instruction_bytes"].__setitem__(0, 0),
            "input": lambda s: s["host"]["buttons"].__setitem__(0, 2),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                client = FakeClient()
                client.state["host"]["audio_output"] = {
                    "pcm_hash": 123, "pending_pcm_frames": 2, "device_open": True,
                    "processing": {"raw_pcm_hash": 456}, "host": {"pauses": 0}}
                before = copy.deepcopy(client.state)
                client.after_memory = lambda c: change(c.state)
                result = run_plan(client, plan(wait({"memory": {"address": 100, "bytes": "12"}})))
                self.assertFalse(result["ok"], result)
                self.assertEqual(client.mutations, [])
                self.assertEqual(result["observations"][0]["status"], before)
                self.assertEqual(result["observations"][0]["status_after"], client.state)

    def test_source_same_pc_with_changed_mpr_or_bytes_is_not_equal(self):
        for key in ("mpr", "bytes", "physical"):
            client = FakeClient()
            if key == "bytes":
                client.state["host"]["cpu"]["instruction_bytes"][1] = 0
            elif key == "mpr":
                cpu = client.state["host"]["cpu"]
                cpu["mpr"][0] = 1
                cpu["physical_pc"] = 16383
                cpu["instruction_physical"][0] = 16383
            else:
                client.state["host"]["cpu"]["instruction_physical"][0] = 0
            result = run_plan(client, plan({"op": "assert", "predicate": {"source": source()}}))
            self.assertFalse(result["ok"])
            self.assertEqual(client.mutations, [])

    def test_cli_exclusive_receipt_and_invalid_later_step(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route, receipt = root / "plan.json", root / "receipt.json"
            route.write_text(json.dumps(plan(pulse(), {"op": "unknown"})), encoding="utf-8")
            with patch("scripts.dev_route.DevClient") as factory, patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(main(["--port", "1", "--plan", str(route), "--receipt", str(receipt)]), 1)
                factory.assert_not_called()
            payload = receipt.read_bytes()
            self.assertFalse(json.loads(payload)["ok"])
            with patch("scripts.dev_route.DevClient") as factory, patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(main(["--port", "1", "--plan", str(route), "--receipt", str(receipt)]), 1)
                factory.assert_not_called()
            self.assertEqual(receipt.read_bytes(), payload)

    def test_cli_duplicate_field_rejected_with_failure_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route, receipt = root / "plan.json", root / "receipt.json"
            route.write_text('{"schema":1,"schema":1}', encoding="utf-8")
            with patch("scripts.dev_route.DevClient") as factory, patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(main(["--port", "1", "--plan", str(route), "--receipt", str(receipt)]), 1)
                factory.assert_not_called()
            self.assertIn("duplicate", json.loads(receipt.read_text())["error"]["message"])

    def test_cli_success_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route, receipt = root / "plan.json", root / "receipt.json"
            route.write_text(json.dumps(plan(pulse())), encoding="utf-8")
            client = FakeClient()
            with patch("scripts.dev_route.DevClient", return_value=client), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(main(["--port", "1", "--plan", str(route), "--receipt", str(receipt)]), 0)
            result = json.loads(receipt.read_text())
            self.assertTrue(result["ok"])
            self.assertEqual(result["advanced_frames"], 3)

    def test_persistent_actual_tcp_client(self):
        # An authored wire peer checks actual request serialization and one
        # connection lifetime, independently from the FakeClient API tests.
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(3)
        fake, errors = FakeClient(), []
        def serve():
            try:
                with listener.accept()[0] as connection:
                    connection.settimeout(3)
                    with connection.makefile("rwb") as stream:
                        for line in stream:
                            request = json.loads(line)
                            command = request.pop("cmd")
                            identity = request.pop("id")
                            if command == "step_frames":
                                response = {"target_frame": fake.advance(request["frames"])["frame"]}
                            else:
                                response = fake.call(command, **request)
                            stream.write(json.dumps({**response, "id": identity, "ok": True}).encode() + b"\n")
                            stream.flush()
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            with DevClient(listener.getsockname()[1], timeout=2) as client:
                result = run_plan(client, plan(wait()))
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["advanced_frames"], 5)
            self.assertEqual(fake.state["host"]["buttons"], [0] * 5)
        finally:
            listener.close()
            thread.join(4)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
