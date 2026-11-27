"""Authored process/telemetry fixtures; these tests never create a GPU device."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gpu_probe", ROOT/"scripts/gpu_probe.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def events(*rows, truncated=False):
    return {"available": True, "data": {"logs": [
        {"log": "System", "scanned": len(rows), "truncated": truncated, "events": list(rows)},
        {"log": "Application", "scanned": 0, "truncated": False, "events": []}]}}


def system(*games):
    return {"available": True, "data": {"gpus": [{"Name": "authored adapter", "DriverVersion": "test"}],
                                        "games": [{"ProcessName": name, "Id": 123} for name in games]}}


RESET = {"log": "System", "record_id": 42, "provider": "Display", "id": 4101,
         "level": "Warning", "time": "2026-11-27T00:00:01Z", "message": "authored driver reset"}


class FakeProcess:
    pid = 12345

    def __init__(self, code=0, hung=False):
        self.code, self.hung, self.killed = code, hung, False

    def poll(self):
        return None if self.hung and not self.killed else self.code

    def wait(self, timeout):
        if self.poll() is None:
            raise subprocess.TimeoutExpired("authored probe", timeout)
        return self.code

    def kill(self):
        self.killed = True
        self.code = -9


class GpuProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.executable = self.root/"pce-display-probe.exe"
        self.executable.write_bytes(b"authored executable identity, never executed")
        (self.root/"SDL3.dll").write_bytes(b"authored DLL identity")
        self.output = self.root/"probe"
        self.child = FakeProcess()
        self.commands = []
        self.produce_frame = True
        self.bad_frame = False

    def spawn(self, command, **kwargs):
        self.commands.append((command, kwargs))
        if self.produce_frame:
            Path(command[-1]).write_bytes(b"malformed" if self.bad_frame else b"P6\n1 1\n255\n\x01\x02\x03")
        kwargs["stdout"].write(b"authored stdout\n")
        kwargs["stderr"].write(b"authored stderr\n")
        return self.child

    def execute(self, *, snapshots=None, systems=None, **kwargs):
        with patch.object(probe, "system_snapshot", side_effect=systems or [system(), system()]), \
             patch.object(probe, "event_snapshot", side_effect=snapshots or [events(), events()]), \
             patch.object(probe.subprocess, "Popen", side_effect=self.spawn), \
             patch.object(probe.time, "sleep"):
            return probe.run_probe(self.executable, self.output, **kwargs)

    def test_software_default_records_bytes_and_unavailable_telemetry_separately(self):
        missing = {"available": False, "reason": "authored unavailable telemetry"}
        result = self.execute(snapshots=[missing, missing], systems=[missing, missing])
        self.assertTrue(result["passed"])
        self.assertFalse(result["physical_gpu_requested"])
        self.assertFalse(result["preflight_telemetry_available"])
        self.assertFalse(result["post_telemetry_available"])
        command, options = self.commands[0]
        self.assertEqual(command[1:5], ["--backend", "software", "--shader", "off"])
        self.assertEqual(options["env"]["SDL_VIDEODRIVER"], "dummy")
        self.assertEqual(options["env"]["SDL_RENDER_DRIVER"], "software")
        self.assertEqual(result["frame"]["width"], 1)
        self.assertEqual(result["frame"]["sha256"], probe._hash(self.output/"frame.ppm"))
        self.assertEqual(result["dlls"], [{"name": "SDL3.dll", "sha256": probe._hash(self.root/"SDL3.dll")}])
        self.assertEqual(json.loads((self.output/"receipt.json").read_bytes()), result)
        self.assertEqual((self.output/"stderr.log").read_bytes(), b"authored stderr\n")
        journal = [json.loads(line) for line in (self.output/"lifecycle.jsonl").read_text().splitlines()]
        self.assertEqual([row["event"] for row in journal], ["preflight", "launch-intent", "started", "exited", "finished"])
        self.assertTrue(journal[-1]["process_closed"])

    def test_hardware_requires_opt_in_and_cannot_fall_back(self):
        with self.assertRaisesRegex(ValueError, "allow-hardware"):
            self.execute(backend="vulkan", shader="crt")
        self.assertFalse(self.output.exists())
        self.assertEqual(self.commands, [])
        result = self.execute(backend="direct3d12", shader="sharp", allow_hardware=True)
        self.assertTrue(result["passed"])
        self.assertTrue(result["physical_gpu_requested"])
        self.assertEqual(self.commands[0][1]["env"]["SDL_GPU_DRIVER"], "direct3d12")
        self.assertEqual(self.commands[0][0][2], "direct3d12")

    def test_wow_skips_hardware_without_starting_or_touching_game(self):
        result = self.execute(backend="vulkan", shader="crt", allow_hardware=True, systems=[system("WoW")], snapshots=[events()])
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(self.commands, [])
        self.assertTrue(result["process_closed"])
        self.assertIn("World of Warcraft", result["reason"])

    def test_unknown_and_truncated_preflight_are_not_clean_hardware_checks(self):
        result = self.execute(backend="vulkan", allow_hardware=True,
                              snapshots=[{"available": False, "reason": "access denied"}], systems=[system()])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.commands, [])
        self.output = self.root/"truncated"
        result = self.execute(backend="direct3d12", allow_hardware=True,
                              snapshots=[events(truncated=True)], systems=[system()])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.commands, [])

    def test_new_reset_fails_even_after_successful_probe(self):
        result = self.execute(backend="direct3d12", allow_hardware=True, snapshots=[events(), events(RESET)])
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "graphics-event")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["graphics_events"], [RESET])
        self.assertEqual(json.loads((self.output/"events-after.json").read_bytes()), events(RESET))

    def test_post_telemetry_loss_prevents_hardware_success(self):
        result = self.execute(backend="vulkan", allow_hardware=True,
                              snapshots=[events(), {"available": False, "reason": "query timed out"}])
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "telemetry-lost")

    def test_failed_child_exit_and_missing_or_malformed_frame_never_pass(self):
        self.child.code = 7
        result = self.execute()
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["status"], "probe-failed")
        self.output = self.root/"missing"
        self.child.code = 0
        self.produce_frame = False
        result = self.execute()
        self.assertEqual(result["status"], "probe-failed")
        self.output = self.root/"malformed"
        self.produce_frame, self.bad_frame = True, True
        result = self.execute()
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["process_closed"])

    def test_timeout_kills_only_owned_probe_and_seals_receipt(self):
        self.child.hung = True
        tick = iter(range(100))
        with patch.object(probe.time, "monotonic", side_effect=lambda: next(tick)*0.5):
            result = self.execute(timeout=1)
        self.assertTrue(self.child.killed)
        self.assertEqual(result["status"], "timeout")
        self.assertFalse(result["passed"])
        self.assertTrue(result["process_closed"])
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(json.loads((self.output/"receipt.json").read_bytes()), result)

    def test_events_during_owned_process_stop_it_without_retry(self):
        self.child.hung = True
        tick = iter(range(100))
        with patch.object(probe.time, "monotonic", side_effect=lambda: next(tick)*0.25):
            result = self.execute(backend="vulkan", allow_hardware=True, timeout=15,
                                  snapshots=[events(), events(RESET), events(RESET)])
        self.assertTrue(self.child.killed)
        self.assertEqual(result["status"], "graphics-event")
        self.assertEqual(len(self.commands), 1)
        self.assertTrue((self.output/"events-during-00.json").is_file())

    def test_start_failure_retains_preflight_and_error(self):
        with patch.object(probe, "system_snapshot", return_value=system()), \
             patch.object(probe, "event_snapshot", return_value=events()), \
             patch.object(probe.subprocess, "Popen", side_effect=OSError("authored launch refusal")):
            result = probe.run_probe(self.executable, self.output)
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["process_closed"])
        self.assertIn("authored launch refusal", result["reason"])
        self.assertTrue((self.output/"system-before.json").is_file())
        intent = json.loads((self.output/"launch.json").read_bytes())
        self.assertFalse(intent["passed"])
        self.assertEqual(intent["status"], "launch-intent")
        self.assertEqual(intent["executable"]["sha256"], probe._hash(self.executable))

    def test_empty_or_partial_telemetry_graph_is_not_complete(self):
        self.assertFalse(probe._complete_events({"available": True, "data": {"logs": []}}))
        self.assertFalse(probe._complete_events({"available": True, "data": {"logs": events()["data"]["logs"][:1]}}))
        self.assertTrue(probe._complete_events(events()))

    def test_isolated_desktop_wrapper_closes_exact_owned_adapter(self):
        self.child.desktop_name = "PceProbe_authored"
        self.child.closed = False
        self.child.close = lambda: setattr(self.child, "closed", True)
        fake_module = types.ModuleType("hidden_desktop")
        fake_module.IsolatedProcess = self.spawn
        fake_os = types.SimpleNamespace(name="nt", environ=os.environ, fsync=os.fsync)
        with patch.dict(sys.modules, {"hidden_desktop": fake_module}), patch.object(probe, "os", fake_os):
            result = self.execute(isolated_desktop=True)
        self.assertTrue(result["passed"])
        self.assertTrue(result["isolated_desktop"])
        self.assertEqual(result["desktop_name"], "PceProbe_authored")
        self.assertTrue(result["desktop_closed"])
        self.assertTrue(self.child.closed)

    def test_isolated_desktop_close_failure_is_not_a_pass(self):
        self.child.desktop_name = "PceProbe_authored"
        def fail():
            raise OSError("authored desktop close failure")
        self.child.close = fail
        fake_module = types.ModuleType("hidden_desktop")
        fake_module.IsolatedProcess = self.spawn
        fake_os = types.SimpleNamespace(name="nt", environ=os.environ, fsync=os.fsync)
        with patch.dict(sys.modules, {"hidden_desktop": fake_module}), patch.object(probe, "os", fake_os):
            result = self.execute(isolated_desktop=True)
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "cleanup-failed")
        self.assertTrue(result["process_closed"])
        self.assertFalse(result["desktop_closed"])

    def test_output_and_argument_bounds(self):
        for timeout in (0, 16, float("nan"), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.execute(timeout=timeout)
        with self.assertRaisesRegex(ValueError, "Software SDL"):
            self.execute(shader="crt")
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertEqual(self.commands, [])

    def test_error_classifier_preserves_scope(self):
        ordinary = {**RESET, "provider": "Application Error", "log": "Application", "message": "unrelated app crash"}
        self.assertEqual(probe.graphics_faults(events(ordinary)), [])
        wer = {**ordinary, "provider": "Windows Error Reporting", "message": "LiveKernelEvent 141"}
        self.assertEqual(probe.graphics_faults(events(wer)), [wer])
        self.assertEqual(probe.graphics_faults({"available": False, "reason": "no access"}), [])


if __name__ == "__main__":
    unittest.main()
