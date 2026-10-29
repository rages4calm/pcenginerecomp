"""Typed relations between two paused development-server status replies.

The default permits only a transport ID change. The legacy profile describes
one explicitly selected source contract: a fresh, unthrottled, muted, raw
44.1 kHz Gear-timing host from ABI 18, whose pump may drain already generated
PCM after replying to TCP. It is never inferred from an ABI number or status.
The caller must independently bind the executable, source and startup recipe.
Selecting a profile is a declaration, not authentication of those bindings.

This module compares reported fields. It does not prove omitted RAM, audio
queue contents, hardware behavior or that two remote requests occurred. Keep
raw replies and readbacks durably before invoking this validator. The default
route runner's existing projection is a separate interface and is unchanged.
"""
from __future__ import annotations

import copy
import math

STRICT = "strict"
LEGACY_FRESH_MUTED_GEAR = "abi18-fresh-muted-gear-v1"
MAX_COUNTER = (1 << 64) - 1
MAX_REQUEST_ID = (1 << 53) - 1
PCM_CAPACITY = 8192
MAX_WAV_FRAMES = 44100 * 120

_AUDIO_FIELDS = frozenset({
    "enabled", "sample_rate", "channels", "frames", "psg_nonzero",
    "adpcm_nonzero", "cdda_nonzero", "mixed_nonzero", "peak", "pcm_hash",
    "discarded_frames", "wav_frames", "wav_truncated", "timing",
    "device_open", "fast_forward_muted", "host",
})
_HOST_FIELDS = frozenset({
    "submitted_frames", "dropped_frames", "clears", "pauses",
    "queued_frames", "peak_queue_frames",
})
_OUTPUT_PATHS = (
    ("host", "audio_output", "host", "submitted_frames"),
    ("host", "audio_output", "host", "dropped_frames"),
    ("host", "audio_output", "wav_frames"),
    ("host", "audio_output", "wav_truncated"),
)


class ObservationError(ValueError):
    """The declared paused-observation relation was not established."""


def _require(value, message):
    if not value:
        raise ObservationError(message)


def _integer(value, minimum, maximum, label):
    _require(type(value) is int and minimum <= value <= maximum,
             label + ": exact bounded integer required")
    return value


def _json_value(value, active):
    """Reject non-JSON objects, cycles and nonfinite values before comparison."""
    kind = type(value)
    if kind in (type(None), bool, int, str):
        return
    if kind is float:
        _require(math.isfinite(value), "nonfinite status value")
        return
    _require(kind in (dict, list), "status must contain plain JSON values")
    identity = id(value)
    _require(identity not in active, "cyclic status value")
    active.add(identity)
    try:
        if kind is dict:
            _require(all(type(key) is str for key in value),
                     "status object keys must be strings")
            children = value.values()
        else:
            children = value
        for child in children:
            _json_value(child, active)
    finally:
        active.remove(identity)


def _difference(left, right, path=()):
    if type(left) is not type(right):
        return path
    if type(left) is dict:
        if left.keys() != right.keys():
            return path
        for key in left:
            mismatch = _difference(left[key], right[key], path + (key,))
            if mismatch is not None:
                return mismatch
        return None
    if type(left) is list:
        if len(left) != len(right):
            return path
        for index, (a, b) in enumerate(zip(left, right)):
            mismatch = _difference(a, b, path + (index,))
            if mismatch is not None:
                return mismatch
        return None
    return None if left == right else path


def _at(value, path):
    for key in path:
        value = value[key]
    return value


def _status(value):
    _require(type(value) is dict, "status must be an object")
    _json_value(value, set())
    _integer(value.get("id"), 1, MAX_REQUEST_ID, "status.id")
    _require(value.get("ok") is True, "status requires a successful boolean acknowledgement")
    _require(value.get("paused") is True and value.get("local_paused") is False,
             "observation requires a network pause without a local pause")
    _integer(value.get("frame"), 0, MAX_COUNTER, "status.frame")
    _integer(value.get("ticks"), 0, MAX_COUNTER, "status.ticks")
    _require(type(value.get("host")) is dict, "status.host must be an object")


def _legacy_audio(status, wav_limit):
    _require("checkpoint" not in status and "checkpoint" not in status["host"],
             "legacy fresh profile cannot validate checkpoint/import counters")
    audio = status["host"].get("audio_output")
    _require(type(audio) is dict and audio.keys() == _AUDIO_FIELDS,
             "legacy profile requires exact raw 44100 Gear audio fields")
    _require(audio["enabled"] is True and audio["device_open"] is True
             and audio["fast_forward_muted"] is True,
             "legacy profile requires enabled open muted audio")
    _require(audio["timing"] == "gear-v1", "legacy profile requires Gear timing")
    _require(type(audio["wav_truncated"]) is bool,
             "audio.wav_truncated requires a boolean")
    for key in _AUDIO_FIELDS - {
            "enabled", "device_open", "fast_forward_muted", "timing",
            "wav_truncated", "host"}:
        _integer(audio[key], 0, MAX_COUNTER, "audio." + key)
    _require(audio["sample_rate"] == 44100 and audio["channels"] == 2,
             "legacy profile requires raw 44100 Hz stereo")
    _require(audio["peak"] <= 32768 and audio["discarded_frames"] == 0,
             "invalid peak or discarded guest PCM")
    for key in ("psg_nonzero", "adpcm_nonzero", "cdda_nonzero", "mixed_nonzero"):
        _require(audio[key] <= audio["frames"], key + " exceeds generated PCM")
    host = audio["host"]
    _require(type(host) is dict and host.keys() == _HOST_FIELDS,
             "legacy profile requires exact SDL presentation fields")
    for key in _HOST_FIELDS:
        _integer(host[key], 0, MAX_COUNTER, "audio.host." + key)
    _require(host["submitted_frames"] == host["dropped_frames"],
             "muted submitted/dropped counters differ")
    _require(host["queued_frames"] == host["peak_queue_frames"] == 0,
             "muted presentation must retain an empty SDL queue")
    _require(host["clears"] >= 1 and host["pauses"] >= 1,
             "muted stream was not paused and cleared")
    pending = audio["frames"] - host["submitted_frames"]
    _require(0 <= pending <= PCM_CAPACITY,
             "fresh pending PCM exceeds capacity or uses imported counters")
    expected_wav = 0 if wav_limit is None else min(host["submitted_frames"], wav_limit)
    expected_truncated = wav_limit is not None and host["submitted_frames"] > wav_limit
    _require(audio["wav_frames"] == expected_wav
             and audio["wav_truncated"] is expected_truncated,
             "WAV output markers disagree with declared fresh capture bound")
    return audio, pending


def validate_paused_observation(before, after, *, profile=STRICT, wav_limit=None):
    """Validate typed equality with an explicitly selected presentation policy.

    ``strict`` removes only top-level transport IDs. The legacy profile permits
    equal submitted/dropped increases of either zero or the entire initially
    pending PCM queue. Its single-threaded pump drains that whole queue without
    yielding to another TCP request. Paused synthesis must stay fixed.

    ``wav_limit=None`` declares no WAV output (zero/false markers). A positive
    limit up to 120 seconds declares a fresh bounded writer; its counters must
    follow min(submitted, limit) and submitted > limit exactly. These markers
    describe host output, not newly synthesized guest PCM. No restored-counter
    allowance exists. All other fields, including unknown future fields, must
    match in both value and type. Full status schema/source validation remains
    the caller's responsibility.
    """
    _require(type(profile) is str and profile in (STRICT, LEGACY_FRESH_MUTED_GEAR),
             "explicit supported observation profile required")
    _require(profile != STRICT or wav_limit is None,
             "strict profile accepts no WAV allowance")
    if wav_limit is not None:
        _integer(wav_limit, 1, MAX_WAV_FRAMES, "wav_limit")
    try:
        _status(before)
        _status(after)
        left = copy.deepcopy(before)
        right = copy.deepcopy(after)
        del left["id"], right["id"]
        proof = {
            "schema": 1, "profile": profile,
            "transport_ids": {"before": before["id"], "after": after["id"]},
            "reported_guest_fields_unchanged": True,
            "changed_paths": [], "presentation": None,
        }
        if profile == LEGACY_FRESH_MUTED_GEAR:
            a, pending_before = _legacy_audio(before, wav_limit)
            b, pending_after = _legacy_audio(after, wav_limit)
            _require(a["frames"] == b["frames"], "paused synthesis frames changed")
            delta = b["host"]["submitted_frames"] - a["host"]["submitted_frames"]
            dropped = b["host"]["dropped_frames"] - a["host"]["dropped_frames"]
            _require(delta == dropped and delta in (0, pending_before),
                     "presentation must drain zero or the entire pending PCM queue")
            _require(pending_after == pending_before - delta,
                     "pending PCM continuation differs")
            for path in _OUTPUT_PATHS:
                if _at(before, path) != _at(after, path):
                    proof["changed_paths"].append(list(path))
                for value in (left, right):
                    parent = _at(value, path[:-1])
                    del parent[path[-1]]
            proof["presentation"] = {
                "pending_before": pending_before, "pending_after": pending_after,
                "drained_frames": delta, "wav_limit": wav_limit,
            }
        mismatch = _difference(left, right)
        _require(mismatch is None,
                 "paused observation changed reported field " + repr(mismatch))
        return proof
    except RecursionError as error:
        raise ObservationError("status nesting exceeds supported recursion") from error
