"""Authored paused-status vectors, including independent whole-queue drains."""
import copy
import math
import unittest

from scripts.dev_observation import (
    LEGACY_FRESH_MUTED_GEAR, ObservationError, validate_paused_observation,
)


def authored_status(*, generated=1000, submitted=991, wav_limit=None):
    """Mathematical diagnostic fixture, never a game capture or wire receipt."""
    return {
        "id": 1, "ok": True, "paused": True, "local_paused": False,
        "frame": 3, "ticks": 1464,
        "host": {
            "pc": 0xE000,
            "cpu": {
                "a": 61, "x": 0, "y": 0, "sp": 255, "p": 4,
                "clock_divisor": 3,
                "mpr": [255, 248, 128, 129, 130, 131, 132, 0],
                "instruction_physical": list(range(7)),
                "instruction_bytes": [0xAD, 0, 0x18, 0x29, 0x40, 0xD0, 0xF9],
                "instruction_generations": [0] * 7,
            },
            "native_steps": 400, "interpreter_steps": 0,
            "buttons": [0] * 5,
            "debug_memory": {"write_enabled": False, "write_requests": 0,
                             "bytes_changed": 0},
            "interrupts": {"mask": 6, "timer_pending": False},
            "audio_output": {
                "enabled": True, "sample_rate": 44100, "channels": 2,
                "frames": generated, "psg_nonzero": 0, "adpcm_nonzero": 0,
                "cdda_nonzero": 0, "mixed_nonzero": 0, "peak": 0,
                "pcm_hash": 0x123456789ABCDEF0, "discarded_frames": 0,
                "wav_frames": 0 if wav_limit is None else min(submitted, wav_limit),
                "wav_truncated": wav_limit is not None and submitted > wav_limit,
                "timing": "gear-v1", "device_open": True,
                "fast_forward_muted": True,
                "host": {
                    "submitted_frames": submitted, "dropped_frames": submitted,
                    "clears": 1, "pauses": 1, "queued_frames": 0,
                    "peak_queue_frames": 0,
                },
            },
        },
        "future": {"counter": 1, "flag": False, "items": [0, "a", None]},
    }


def after_drain(before, frames, *, wav_limit=None):
    after = copy.deepcopy(before)
    after["id"] += 1
    audio = after["host"]["audio_output"]
    for key in ("submitted_frames", "dropped_frames"):
        audio["host"][key] += frames
    if wav_limit is not None:
        audio["wav_frames"] = min(audio["host"]["submitted_frames"], wav_limit)
        audio["wav_truncated"] = audio["host"]["submitted_frames"] > wav_limit
    return after


class PausedObservationTests(unittest.TestCase):
    def legacy(self, before, after, **options):
        return validate_paused_observation(before, after,
                                           profile=LEGACY_FRESH_MUTED_GEAR, **options)

    def test_default_is_exact_except_transport_id(self):
        before = authored_status()
        after = copy.deepcopy(before)
        after["id"] = 700
        proof = validate_paused_observation(before, after)
        self.assertEqual(proof["profile"], "strict")
        self.assertEqual(proof["transport_ids"], {"before": 1, "after": 700})
        self.assertEqual(proof["changed_paths"], [])
        self.assertIsNone(proof["presentation"])

    def test_legacy_is_never_inferred_from_an_abi_field(self):
        before = authored_status()
        before["host"]["runtime_abi"] = 18
        after = after_drain(before, 9)
        with self.assertRaises(ObservationError):
            validate_paused_observation(before, after)
        self.assertEqual(self.legacy(before, after)["presentation"]["drained_frames"], 9)

    def test_nine_frame_drain_has_exact_independent_witness(self):
        before = authored_status()
        after = after_drain(before, 9)
        proof = self.legacy(before, after)
        self.assertEqual(proof["presentation"], {
            "pending_before": 9, "pending_after": 0,
            "drained_frames": 9, "wav_limit": None,
        })
        self.assertEqual(proof["changed_paths"], [
            ["host", "audio_output", "host", "submitted_frames"],
            ["host", "audio_output", "host", "dropped_frames"],
        ])

    def test_zero_and_capacity_boundaries(self):
        for generated, submitted, drain in ((0, 0, 0), (1000, 991, 0),
                                            (8192, 0, 8192), (8192, 0, 0)):
            with self.subTest(generated=generated, submitted=submitted, drain=drain):
                before = authored_status(generated=generated, submitted=submitted)
                proof = self.legacy(before, after_drain(before, drain))
                self.assertEqual(proof["presentation"]["pending_after"],
                                 generated - submitted - drain)

    def test_partial_negative_and_over_drains_are_refused(self):
        before = authored_status()
        for drain in (-1, 1, 8, 10):
            with self.subTest(drain=drain), self.assertRaises(ObservationError):
                self.legacy(before, after_drain(before, drain))

    def test_asymmetric_drop_is_refused(self):
        before = authored_status()
        after = after_drain(before, 9)
        after["host"]["audio_output"]["host"]["dropped_frames"] -= 1
        with self.assertRaises(ObservationError):
            self.legacy(before, after)

    def test_every_other_sdl_counter_is_strict(self):
        before = authored_status()
        for key in ("clears", "pauses", "queued_frames", "peak_queue_frames"):
            after = after_drain(before, 9)
            after["host"]["audio_output"]["host"][key] += 1
            with self.subTest(key=key), self.assertRaises(ObservationError):
                self.legacy(before, after)

    def test_muted_open_and_initialized_stream_are_required(self):
        for key in ("enabled", "device_open", "fast_forward_muted"):
            before = authored_status()
            before["host"]["audio_output"][key] = False
            with self.subTest(key=key), self.assertRaises(ObservationError):
                self.legacy(before, copy.deepcopy(before))
        for key in ("clears", "pauses"):
            before = authored_status()
            before["host"]["audio_output"]["host"][key] = 0
            with self.subTest(key=key), self.assertRaises(ObservationError):
                self.legacy(before, copy.deepcopy(before))

    def test_source_and_synthesis_fields_stay_strict(self):
        before = authored_status()
        paths = [
            ("ticks",), ("frame",), ("host", "native_steps"),
            ("host", "interpreter_steps"), ("host", "cpu", "a"),
            ("host", "cpu", "mpr", 7),
            ("host", "cpu", "instruction_physical", 0),
            ("host", "cpu", "instruction_bytes", 0),
            ("host", "cpu", "instruction_generations", 0),
            ("host", "audio_output", "frames"),
            ("host", "audio_output", "pcm_hash"),
            ("host", "audio_output", "psg_nonzero"),
            ("host", "audio_output", "discarded_frames"),
            ("host", "debug_memory", "bytes_changed"),
            ("host", "buttons", 0),
        ]
        for path in paths:
            after = after_drain(before, 9)
            parent = after
            for key in path[:-1]:
                parent = parent[key]
            parent[path[-1]] += 1
            with self.subTest(path=path), self.assertRaises(ObservationError):
                self.legacy(before, after)

    def test_unknown_fields_are_compared_with_their_types(self):
        before = authored_status()
        for replacement in (2, True, 1.0):
            after = after_drain(before, 9)
            after["future"]["counter"] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(ObservationError):
                self.legacy(before, after)
        after = after_drain(before, 9)
        after["host"]["interrupts"]["new_device"] = False
        with self.assertRaises(ObservationError):
            self.legacy(before, after)

    def test_unknown_or_missing_audio_fields_are_refused(self):
        for location in ("audio", "host"):
            for add in (True, False):
                before = authored_status()
                value = before["host"]["audio_output"]
                if location == "host":
                    value = value["host"]
                if add:
                    value["future"] = 0
                else:
                    del value[next(iter(value))]
                with self.subTest(location=location, add=add), self.assertRaises(ObservationError):
                    self.legacy(before, copy.deepcopy(before))

    def test_boolean_and_float_counters_are_refused(self):
        for key in ("frames", "pcm_hash", "sample_rate", "wav_frames"):
            for replacement in (True, 1.0):
                before = authored_status()
                before["host"]["audio_output"][key] = replacement
                with self.subTest(key=key, replacement=replacement), self.assertRaises(ObservationError):
                    self.legacy(before, copy.deepcopy(before))
        for replacement in (True, 991.0, -1, 1 << 64):
            before = authored_status()
            before["host"]["audio_output"]["host"]["submitted_frames"] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(ObservationError):
                self.legacy(before, copy.deepcopy(before))

    def test_checkpoint_and_imported_counter_profiles_are_refused(self):
        for resumed in (False, True):
            before = authored_status()
            before["host"]["checkpoint"] = {"resumed": resumed}
            with self.subTest(resumed=resumed), self.assertRaises(ObservationError):
                self.legacy(before, copy.deepcopy(before))
        before = authored_status()
        before["checkpoint"] = {"origin": 0}
        with self.assertRaises(ObservationError):
            self.legacy(before, copy.deepcopy(before))
        for generated, submitted in ((9000, 0), (1000, 1001)):
            before = authored_status(generated=generated, submitted=submitted)
            with self.subTest(generated=generated), self.assertRaises(ObservationError):
                self.legacy(before, copy.deepcopy(before))

    def test_no_wav_output_requires_zero_false_markers(self):
        before = authored_status()
        for key, value in (("wav_frames", 1), ("wav_truncated", True),
                           ("wav_truncated", 0)):
            after = after_drain(before, 9)
            after["host"]["audio_output"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ObservationError):
                self.legacy(before, after)

    def test_bounded_wav_crossing_and_exact_limit_relations(self):
        # 991 submitted ->1000, with independent crossing/below/above-cap vectors.
        for cap, expected_before, expected_after, truncated in (
                (995, 991, 995, True), (1000, 991, 1000, False),
                (2000, 991, 1000, False), (500, 500, 500, True)):
            before = authored_status(wav_limit=cap)
            after = after_drain(before, 9, wav_limit=cap)
            self.assertEqual(before["host"]["audio_output"]["wav_frames"], expected_before)
            self.assertEqual(after["host"]["audio_output"]["wav_frames"], expected_after)
            self.assertIs(after["host"]["audio_output"]["wav_truncated"], truncated)
            proof = self.legacy(before, after, wav_limit=cap)
            self.assertEqual(proof["presentation"]["drained_frames"], 9)

    def test_wrong_wav_minimum_or_truncation_is_refused(self):
        before = authored_status(wav_limit=995)
        for field, value in (("wav_frames", 994), ("wav_truncated", False)):
            after = after_drain(before, 9, wav_limit=995)
            after["host"]["audio_output"][field] = value
            with self.subTest(field=field), self.assertRaises(ObservationError):
                self.legacy(before, after, wav_limit=995)

    def test_profile_and_wav_options_require_exact_declared_values(self):
        before = authored_status()
        for profile in (None, True, "legacy", 18):
            with self.subTest(profile=profile), self.assertRaises(ObservationError):
                validate_paused_observation(before, before, profile=profile)
        for cap in (0, -1, True, 1.0, 44100 * 120 + 1):
            with self.subTest(cap=cap), self.assertRaises(ObservationError):
                self.legacy(before, before, wav_limit=cap)
        with self.assertRaises(ObservationError):
            validate_paused_observation(before, before, wav_limit=10)

    def test_paused_scope_and_required_status_fields(self):
        for key, value in (("ok", False), ("ok", 1), ("ok", None),
                           ("paused", False), ("paused", 1),
                           ("local_paused", True), ("local_paused", 0),
                           ("id", True), ("id", 0), ("id", 1 << 53),
                           ("ticks", True), ("frame", -1), ("host", [])):
            before = authored_status()
            before[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ObservationError):
                validate_paused_observation(before, copy.deepcopy(before))
        for key in ("id", "ok", "paused", "local_paused", "frame", "ticks", "host"):
            before = authored_status()
            del before[key]
            with self.subTest(key=key), self.assertRaises(ObservationError):
                validate_paused_observation(before, copy.deepcopy(before))

    def test_plain_finite_json_and_acyclic_values_only(self):
        for value in (math.nan, math.inf, -math.inf, b"bytes", (1, 2), {1: "key"}):
            before = authored_status()
            before["future"] = value
            with self.subTest(value=repr(value)), self.assertRaises(ObservationError):
                validate_paused_observation(before, copy.deepcopy(before))
        before = authored_status()
        before["future"] = before
        with self.assertRaises(ObservationError):
            validate_paused_observation(before, before)

    def test_arguments_are_not_mutated_and_proofs_do_not_alias_them(self):
        before = authored_status(wav_limit=995)
        after = after_drain(before, 9, wav_limit=995)
        originals = copy.deepcopy((before, after))
        proof = self.legacy(before, after, wav_limit=995)
        proof["changed_paths"][0].append("changed")
        self.assertEqual((before, after), originals)
        with self.assertRaises(ObservationError):
            validate_paused_observation(before, after)
        self.assertEqual((before, after), originals)


if __name__ == "__main__":
    unittest.main()
