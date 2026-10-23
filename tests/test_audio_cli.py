"""Authored guest programs and actual exclusive, bounded PCM WAV capture."""
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parent.parent
NAME = "pce-headless.exe" if os.name == "nt" else "pce-headless"
BINARY = Path(os.environ.get("PCE_TEST_HEADLESS", ROOT / "build" / NAME)).resolve()
DESKTOP = Path(os.environ.get("PCE_TEST_DESKTOP", "disabled")).resolve()
MPRS = "255,248,128,129,130,131,132,0"


def dda_program():
    # One centered-DAC channel, maximum amplitude, left only. The setup
    # finishes before the first 44.1 kHz edge; BRA thereafter holds the DDA.
    program = bytearray()
    for port, value in ((0, 0), (1, 255), (4, 223), (5, 240), (6, 31)):
        program.extend((0xA9, value, 0x8D, port, 8))
    return bytes(program) + bytes((0x80, 0xFE))


@unittest.skipUnless(BINARY.is_file(), "Build pce-headless for audio CLI checks")
class AudioCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / "authored.bin"
        self.image.write_bytes(bytes((0x80, 0xFE)))

    def invoke(self, options=(), *, program=None, steps=5000, ticks=1000000):
        if program is not None:
            self.image.write_bytes(program)
        before = self.image.read_bytes()
        result = subprocess.run([str(BINARY), str(self.image), "0x100000", "0x4000",
                                 MPRS, str(steps), str(ticks), "hybrid", *map(str, options)],
                                capture_output=True, text=True, timeout=8, cwd=self.root)
        self.assertEqual(self.image.read_bytes(), before, "audio capture modified its program input")
        return result

    def state(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def refusal(self, options):
        result = self.invoke(options)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr)
        return result

    def pcm(self, path):
        raw = path.read_bytes()
        self.assertEqual(raw[:4], b"RIFF")
        self.assertEqual(raw[8:12], b"WAVE")
        self.assertEqual(struct.unpack_from("<I", raw, 4)[0], len(raw) - 8)
        with wave.open(str(path), "rb") as stream:
            self.assertEqual((stream.getnchannels(), stream.getsampwidth(), stream.getframerate(),
                              stream.getcomptype()), (2, 2, 44100, "NONE"))
            frames = stream.getnframes()
            data = stream.readframes(frames + 1)
            self.assertEqual(len(data), frames * 4)
            self.assertEqual(stream.readframes(1), b"")
        return frames, list(struct.iter_unpack("<hh", data))

    def test_headless_default_and_explicit_off_preserve_legacy_report(self):
        default = self.state(self.invoke())
        off = self.state(self.invoke(("--audio-output", "off")))
        self.assertEqual(default, off)
        self.assertNotIn("audio_output", default)
        self.assertEqual(list(self.root.iterdir()), [self.image])

    def test_audio_on_conserves_exposed_cpu_device_state_and_retired_work(self):
        off = self.state(self.invoke(("--audio-output", "off")))
        on = self.state(self.invoke(("--audio-output", "on")))
        audio = on.pop("audio_output")
        self.assertEqual(on, off)
        self.assertTrue(audio["enabled"])
        self.assertEqual((audio["sample_rate"], audio["channels"]), (44100, 2))
        self.assertGreater(audio["frames"], 0)
        self.assertEqual((audio["mixed_nonzero"], audio["discarded_frames"], audio["wav_frames"]), (0, 0, 0))
        self.assertFalse(audio["wav_truncated"])
        self.assertEqual(on["native_steps"] + on["interpreter_steps"], 5000)
        self.assertEqual(list(self.root.iterdir()), [self.image])

    def test_capture_implicitly_enables_audio_and_writes_valid_silent_pcm(self):
        output = self.root / "diagnostic output.wav"
        state = self.state(self.invoke(("--audio-out", output)))
        frames, samples = self.pcm(output)
        self.assertGreater(frames, 0)
        self.assertTrue(all(sample == (0, 0) for sample in samples))
        self.assertEqual((state["audio_output"]["frames"], state["audio_output"]["wav_frames"]), (frames, frames))
        self.assertFalse(state["audio_output"]["wav_truncated"])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["authored.bin", "diagnostic output.wav"])

    def test_actual_guest_psg_writes_produce_literal_left_only_pcm(self):
        output = self.root / "dda.wav"
        state = self.state(self.invoke(("--audio-output", "on", "--audio-out", output), program=dda_program()))
        frames, samples = self.pcm(output)
        self.assertGreater(frames, 10)
        self.assertEqual(set(samples), {(1761, 0)})
        self.assertEqual(state["audio_output"]["psg_nonzero"], frames)
        self.assertEqual(state["audio_output"]["mixed_nonzero"], frames)
        self.assertEqual(state["audio_output"]["peak"], 1761)
        self.assertEqual(state["vdc"]["psg_writes"], 5)

    def test_quota_truncates_capture_without_shortening_guest_execution(self):
        program = dda_program()
        full = self.state(self.invoke(("--audio-output", "on"), program=program))
        output = self.root / "bounded.wav"
        bounded = self.state(self.invoke(("--audio-out", output, "--audio-frames", "3"), program=program))
        self.assertEqual(self.pcm(output), (3, [(1761, 0)] * 3))
        audio = bounded.pop("audio_output")
        complete = full.pop("audio_output")
        self.assertEqual(bounded, full)
        self.assertEqual(audio["frames"], complete["frames"])
        self.assertEqual(audio["pcm_hash"], complete["pcm_hash"])
        self.assertEqual(audio["wav_frames"], 3)
        self.assertTrue(audio["wav_truncated"])
        self.assertEqual(output.stat().st_size, 56)

    def test_capture_frame_limit_endpoints_do_not_preallocate_maximum(self):
        for limit in (1, 5292000):
            with self.subTest(limit=limit):
                output = self.root / f"limit-{limit}.wav"
                state = self.state(self.invoke(("--audio-out", output, "--audio-frames", str(limit))))
                generated = state["audio_output"]["frames"]
                frames, _ = self.pcm(output)
                self.assertEqual(frames, min(limit, generated))
                self.assertEqual(state["audio_output"]["wav_truncated"], generated > limit)
                self.assertLess(output.stat().st_size, 1024)

    def test_capture_before_first_sample_has_valid_empty_wav(self):
        output = self.root / "empty.wav"
        state = self.state(self.invoke(("--audio-out", output), program=b"\xEA", steps=1))
        self.assertEqual(self.pcm(output), (0, []))
        self.assertEqual(output.stat().st_size, 44)
        self.assertEqual(state["audio_output"]["frames"], 0)
        self.assertFalse(state["audio_output"]["wav_truncated"])

    def test_existing_output_and_program_input_are_preserved(self):
        output = self.root / "existing.wav"
        marker = b"owner file must remain intact"
        output.write_bytes(marker)
        self.refusal(("--audio-out", output))
        self.assertEqual(output.read_bytes(), marker)
        self.refusal(("--audio-out", self.image))
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["authored.bin", "existing.wav"])

    def test_aliases_to_other_outputs_are_refused_before_creation(self):
        nested = self.root / "nested"
        nested.mkdir()
        for flag in ("--frame-out", "--code-capture"):
            with self.subTest(flag=flag):
                output = self.root / "aliased.out"
                self.refusal((flag, output, "--audio-out", nested / ".." / "aliased.out"))
                self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == "nt", "Windows output path comparison")
    def test_case_variant_nonexistent_outputs_are_recognized_as_aliases(self):
        frame = self.root / "OUT.WAV"
        audio = self.root / "out.wav"
        self.assertFalse(frame.exists())
        self.assertFalse(audio.exists())
        result = self.refusal(("--frame-out", frame, "--audio-out", audio))
        self.assertIn("aliases another input or output", result.stderr)
        self.assertFalse(frame.exists())
        self.assertFalse(audio.exists())

    def test_symlink_outputs_existing_and_dangling_are_refused(self):
        target = self.root / "target.wav"
        marker = b"authored preexisting target"
        target.write_bytes(marker)
        for name, destination in (("linked.wav", target), ("dangling.wav", self.root / "absent.wav")):
            link = self.root / name
            try:
                link.symlink_to(destination)
            except OSError:
                self.skipTest("Symlink creation unavailable")
            self.refusal(("--audio-out", link))
            self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_bytes(), marker)
        self.assertFalse((self.root / "absent.wav").exists())

    def test_malformed_limits_disabled_capture_and_missing_values_refused(self):
        output = self.root / "invalid.wav"
        cases = [("--audio-output", value) for value in ("true", "ON", "1", "")]
        cases += [("--audio-out", output, "--audio-frames", value)
                  for value in ("0", "5292001", "-1", "1.5", "x", "18446744073709551616")]
        cases += [("--audio-frames", "1"), ("--audio-output", "off", "--audio-out", output),
                  ("--audio-output",), ("--audio-out",), ("--audio-frames",)]
        for options in cases:
            with self.subTest(options=options):
                self.refusal(options)
                self.assertFalse(output.exists())

    def test_duplicate_audio_flags_refused_before_creating_output(self):
        output = self.root / "duplicate.wav"
        for options in (("--audio-output", "on", "--audio-output", "on"),
                        ("--audio-out", output, "--audio-out", output),
                        ("--audio-out", output, "--audio-frames", "1", "--audio-frames", "1")):
            with self.subTest(options=options):
                self.refusal(options)
                self.assertFalse(output.exists())

    def test_missing_capture_parent_fails_explicitly(self):
        output = self.root / "missing" / "capture.wav"
        self.refusal(("--audio-out", output))
        self.assertFalse(output.exists())

    def test_tick_deadline_remains_authority_with_audio_enabled(self):
        state = self.state(self.invoke(("--audio-output", "on"), steps=1000000, ticks=10000))
        self.assertEqual(state["stop"], "budget")
        self.assertLess(state["native_steps"] + state["interpreter_steps"], 1000000)
        self.assertGreaterEqual(state["ticks"], 10000)
        # Guest-clock profile publishes on floor(n*master_clock/44100).
        expected = ((state["ticks"] + 1) * 44100 - 1) // 21477273
        self.assertEqual(state["audio_output"]["frames"], expected)

    def all_options(self, desktop=False):
        # Deliberate invalid mode is checked after the entire option parser,
        # before any media load/window/device creation. Thus all argument slots
        # are exercised without making a fake BIOS/disc or installing codecs.
        options = [("--bios", "unused.pce"), ("--bram", "unused.bram"),
                   ("--toc", "unused.toc"), ("--disc", "unused.iso"),
                   ("--libchdr", "unused.dll"), ("--joypad", "2"),
                   ("--joypad-region", "usa"), ("--multitap", "off"),
                   ("--buttons", "0"), ("--frame-out", "frame.ppm"),
                   ("--input-script", "unused.input"), ("--cd-unknown-status", "fault"),
                   ("--video-output", "continuous"), ("--dev-port", "0"),
                   ("--dev-start-paused", "off"), ("--dev-memory-write", "off"),
                   ("--wall-seconds", "1"), ("--code-capture", "code.json"),
                   ("--capture-limit", "1"), ("--audio-output", "bad-mode"),
                   ("--audio-out", "audio.wav"), ("--audio-frames", "1")]
        if desktop:
            options += [("--window-scale", "1"), ("--unthrottled", "on"),
                        ("--hidden", "on"), ("--window-capture", "desktop.ppm")]
        paths = {"--bios", "--bram", "--toc", "--disc", "--libchdr", "--frame-out",
                 "--input-script", "--code-capture", "--audio-out", "--window-capture"}
        return [item for flag, value in options
                for item in (flag, str(self.root / value) if flag in paths else value)]

    def test_all_headless_option_slots_reach_semantic_validation(self):
        options = self.all_options()
        self.assertEqual(len(options), 44)
        result = self.refusal(options)
        self.assertIn("--audio-output requires on or off", result.stderr)
        self.assertEqual(list(self.root.iterdir()), [self.image])

    @unittest.skipUnless(DESKTOP.is_file(), "Build desktop runner for all 26 option pairs")
    def test_all_desktop_option_slots_fit_argc_sixty(self):
        command = [str(DESKTOP), str(self.image), "0x100000", "0x4000", MPRS,
                   "1", "10000", "hybrid", *self.all_options(desktop=True)]
        self.assertEqual(len(command), 60)
        # Desktop mode is invalid before host initialization; this never opens
        # a window or a playback device even when run on a real workstation.
        result = subprocess.run(command, capture_output=True, text=True, timeout=8, cwd=self.root)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("--audio-output requires on or off", result.stderr)
        self.assertNotIn("usage:", result.stderr)
        self.assertEqual(list(self.root.iterdir()), [self.image])

    @unittest.skipUnless(DESKTOP.is_file(), "Build desktop runner for fast-forward audio policy")
    def test_unthrottled_desktop_mutes_playback_but_retains_guest_pcm_and_wav(self):
        program = dda_program()
        self.image.write_bytes(program)
        output = self.root / "fast-forward.wav"
        env = os.environ.copy()
        env.update(SDL_VIDEODRIVER="dummy", SDL_RENDER_DRIVER="software", SDL_AUDIODRIVER="dummy")
        command = [str(DESKTOP), str(self.image), "0x100000", "0x4000", MPRS,
                   "5000", "1000000", "hybrid", "--unthrottled", "on", "--hidden", "on",
                   "--window-scale", "1", "--audio-output", "on", "--audio-out", str(output)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=8,
                                cwd=self.root, env=env)
        state = self.state(result)
        self.assertEqual(self.image.read_bytes(), program)
        frames, samples = self.pcm(output)
        self.assertGreater(frames, 10)
        self.assertEqual(set(samples), {(1761, 0)})
        audio = state["audio_output"]
        self.assertTrue(audio["fast_forward_muted"])
        self.assertTrue(audio["device_open"])
        self.assertEqual((audio["frames"], audio["wav_frames"], audio["psg_nonzero"],
                          audio["mixed_nonzero"]), (frames, frames, frames, frames))
        self.assertFalse(audio["wav_truncated"])
        host = audio["host"]
        self.assertGreater(host["submitted_frames"], 0)
        self.assertEqual(host["submitted_frames"], frames)
        self.assertEqual(host["dropped_frames"], host["submitted_frames"])
        self.assertEqual((host["queued_frames"], host["peak_queue_frames"]), (0, 0))
        self.assertGreaterEqual(host["pauses"], 1)


if __name__ == "__main__":
    unittest.main()
