"""Bounded read-only BIN/CUE subset with complete-image identity.

Disc LBAs exclude the lead-in. INDEX offsets are frames within each FILE;
PREGAP/POSTGAP insert virtual frames, whereas INDEX 00 describes stored bytes.
Unsupported layouts fail rather than guessing a sector coordinate.
"""

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import re
import struct

from .media import MediaError, sha256


MAX_CUE_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024 * 1024
MAX_LEADOUT = 449849
_MODES = {"MODE1/2048": ("MODE1", 2048), "MODE1/2352": ("MODE1_RAW", 2352),
          "AUDIO": ("AUDIO", 2352)}
_TEXT = {"TITLE", "PERFORMER", "SONGWRITER", "CATALOG", "ISRC"}
_ASCII_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_DEVICES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10))}


def _stamp(path):
    if not path.is_file():
        raise MediaError("CUE inputs must be regular files")
    stat = path.stat()
    if not 0 < stat.st_size <= MAX_IMAGE_BYTES:
        raise MediaError("CUE input size is empty or exceeds 8 GiB")
    return stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino


def _time(text):
    match = re.fullmatch(r"([0-9]{2}):([0-9]{2}):([0-9]{2})", text)
    if not match:
        raise MediaError("CUE time requires MM:SS:FF")
    minutes, seconds, frames = map(int, match.groups())
    if seconds >= 60 or frames >= 75:
        raise MediaError("CUE time exceeds MSF range")
    return (minutes * 60 + seconds) * 75 + frames


def _name(text):
    name = text.replace("\\", "/")
    parts = name.split("/")
    if (not name or any(not p or p in (".", "..") for p in parts)
            or any(ord(c) < 32 or ord(c) == 127 or c in '<>:"|?*' for c in name)
            or any(p.endswith((".", " ")) or p.split(".", 1)[0].translate(_ASCII_UPPER) in _DEVICES for p in parts)):
        raise MediaError("CUE FILE requires a portable relative path without parent traversal")
    return name


def _tokens(line):
    """CUE quotes group a filename; backslashes are path separators, not escapes."""
    result = []
    while line:
        line = line.lstrip(" \t")
        if not line:
            break
        if line[0] == '"':
            end = line.find('"', 1)
            if end < 0 or (end + 1 < len(line) and line[end + 1] not in " \t"):
                raise MediaError("Malformed CUE quoted field")
            result.append(line[1:end])
            line = line[end + 1:]
        else:
            match = re.match(r"[^ \t]+", line)
            token = match.group()
            if '"' in token:
                raise MediaError("Malformed CUE quoted field")
            result.append(token)
            line = line[len(token):]
    return result


@dataclass(frozen=True)
class CueTrack:
    number: int
    type: str
    file: str
    file_index1: int
    sector_bytes: int
    frames: int
    pregap: int
    stored_pregap: bool
    disc_start: int
    postgap: int = 0

    @property
    def data_frames(self):
        return self.frames - (self.pregap if self.stored_pregap else 0)

    @property
    def index1_frame(self):
        return self.file_index1

class Cue:
    def __init__(self, path: Path):
        source = Path(path).absolute()
        self.declared_path = source
        self.path = source.resolve()
        self.directory = source.parent.resolve()
        if not self.path.is_relative_to(self.directory):
            raise MediaError("CUE descriptor target escapes its declared directory")
        initial = _stamp(self.path)
        if initial[0] > MAX_CUE_BYTES:
            raise MediaError("CUE descriptor exceeds 1 MiB")
        self._stamps = {self.path: initial}
        self._links = {source: self.path}
        raw = self.path.read_bytes()
        if len(raw) != initial[0]:
            raise MediaError("CUE descriptor changed during read")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise MediaError("CUE descriptor must be UTF-8") from error
        if any((ord(c) < 32 and c not in "\t\r\n") or ord(c) == 127 for c in text):
            raise MediaError("CUE descriptor contains control characters")
        self.referenced_files = {}
        parsed_files = []
        parsed_tracks = []
        canonical = set()
        names = set()
        current_file = current_track = None
        total = 0
        for line in text.split("\n"):
            line = line.removesuffix("\r")
            if "\r" in line:
                raise MediaError("CUE descriptor contains an embedded carriage return")
            # REM owns the rest of its line, including arbitrary quotation marks.
            first = re.match(r"[^ \t]+", line.lstrip(" \t"))
            if first is None or first.group().translate(_ASCII_UPPER) == "REM":
                continue
            if line.lstrip(" \t").startswith('"'):
                raise MediaError("CUE commands must be unquoted ASCII keywords")
            fields = _tokens(line)
            command = fields[0].translate(_ASCII_UPPER)
            if command in _TEXT:
                if len(fields) < 2:
                    raise MediaError("CUE text metadata requires a value")
                continue
            if command == "FILE":
                if len(fields) != 3 or fields[2].translate(_ASCII_UPPER) != "BINARY":
                    raise MediaError("CUE FILE supports BINARY only")
                if len(parsed_files) == 99:
                    raise MediaError("CUE exceeds 99 FILEs")
                name = _name(fields[1])
                target = (self.directory / name).resolve()
                if not target.is_relative_to(self.directory) or target == self.path:
                    raise MediaError("CUE FILE escapes its descriptor directory or aliases the descriptor")
                folded = name.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))
                if folded in names or target in canonical:
                    raise MediaError("Duplicate CUE FILE reference")
                names.add(folded)
                canonical.add(target)
                stamp = _stamp(target)
                total += stamp[0]
                if total > MAX_IMAGE_BYTES:
                    raise MediaError("CUE referenced files exceed 8 GiB")
                self._stamps[target] = stamp
                self._links[self.directory / name] = target
                self.referenced_files[name] = target
                current_file = {"name": name, "size": stamp[0], "tracks": [], "width": None}
                parsed_files.append(current_file)
                current_track = None
            elif command == "TRACK":
                if (current_file is None or len(fields) != 3 or not re.fullmatch(r"[0-9]{1,2}", fields[1])
                        or int(fields[1]) != len(parsed_tracks) + 1 or len(parsed_tracks) == 99
                        or fields[2].translate(_ASCII_UPPER) not in _MODES):
                    raise MediaError("CUE requires sequential supported TRACKs 01..99 after FILE")
                kind, width = _MODES[fields[2].translate(_ASCII_UPPER)]
                if current_file["width"] not in (None, width):
                    raise MediaError("Mixed sector widths within one CUE FILE are unsupported")
                current_file["width"] = width
                current_track = {"number": len(parsed_tracks) + 1, "type": kind,
                                 "file": current_file["name"], "width": width, "indices": {},
                                 "pregap": None, "postgap": None}
                current_file["tracks"].append(current_track)
                parsed_tracks.append(current_track)
            elif command == "INDEX":
                if (current_track is None or len(fields) != 3 or not re.fullmatch(r"[0-9]{1,2}", fields[1])
                        or int(fields[1]) not in (0, 1) or current_track["postgap"] is not None):
                    raise MediaError("CUE supports INDEX 00/01 within TRACK only")
                index = int(fields[1])
                indices = current_track["indices"]
                if index in indices or (index == 0 and 1 in indices):
                    raise MediaError("Duplicate or out-of-order CUE INDEX")
                indices[index] = _time(fields[2])
            elif command == "PREGAP":
                if (current_track is None or len(fields) != 2 or current_track["pregap"] is not None
                        or current_track["indices"] or current_track["postgap"] is not None):
                    raise MediaError("CUE PREGAP must occur once before INDEX")
                current_track["pregap"] = _time(fields[1])
            elif command == "POSTGAP":
                if (current_track is None or len(fields) != 2 or current_track["postgap"] is not None
                        or 1 not in current_track["indices"]):
                    raise MediaError("CUE POSTGAP must occur once after INDEX 01")
                current_track["postgap"] = _time(fields[1])
            else:
                raise MediaError(f"Unsupported CUE command: {command}")
        if not parsed_tracks:
            raise MediaError("CUE requires at least one supported track")
        self.tracks = []
        cursor = 0
        for file in parsed_files:
            if not file["tracks"] or file["size"] % file["width"]:
                raise MediaError("CUE FILE requires complete sectors and at least one TRACK")
            file_frames = file["size"] // file["width"]
            for position, track in enumerate(file["tracks"]):
                indices = track["indices"]
                if 1 not in indices:
                    raise MediaError("CUE TRACK requires INDEX 01")
                start = indices.get(0, indices[1])
                if (position == 0 and start != 0) or start > indices[1]:
                    raise MediaError("CUE FILE must begin at frame zero and INDEX 00 cannot follow INDEX 01")
                if position + 1 < len(file["tracks"]):
                    next_indices = file["tracks"][position + 1]["indices"]
                    if 1 not in next_indices:
                        raise MediaError("CUE TRACK requires INDEX 01")
                    end = next_indices.get(0, next_indices[1])
                else:
                    end = file_frames
                if not 0 <= start <= indices[1] < end <= file_frames:
                    raise MediaError("CUE INDEX ranges overlap, exceed the file, or consume a track")
                stored = indices[1] - start
                virtual = track["pregap"] or 0
                if stored and virtual:
                    raise MediaError("Combined virtual and stored CUE pregap is unsupported")
                if track["number"] == 1 and (indices[1] or virtual):
                    raise MediaError("First CUE track requires INDEX 01 zero and no pregap")
                pregap = stored or virtual
                disc_start = cursor + pregap
                payload = end - indices[1]
                self.tracks.append(CueTrack(track["number"], track["type"], track["file"],
                    indices[1], track["width"], payload + stored, pregap, bool(stored), disc_start,
                    track["postgap"] or 0))
                cursor = disc_start + payload + (track["postgap"] or 0)
                if cursor > MAX_LEADOUT:
                    raise MediaError("CUE leadout exceeds the supported BCD range")
        self.leadout_lba = cursor
        self.check_unchanged()

    def check_unchanged(self):
        for source, expected in self._links.items():
            if source.resolve() != expected:
                raise MediaError("CUE input target changed after identity verification")
        for path, initial in self._stamps.items():
            if _stamp(path) != initial:
                raise MediaError("CUE input changed after identity verification")

    def image_sha256(self):
        self.check_unchanged()
        lines = ["PCE-CUE-1\n", f"cue\t{self._stamps[self.path][0]}\t{sha256(self.path)}\n"]
        for name, path in self.referenced_files.items():
            lines.append(f"file\t{name}\t{self._stamps[path][0]}\t{sha256(path)}\n")
        self.check_unchanged()
        return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()

    def report(self, hash_file=False):
        self.check_unchanged()
        result = {"format": "bin-cue", "file_bytes": self._stamps[self.path][0],
                  "leadout_lba": self.leadout_lba,
                  "integrity": "bounded layout; raw headers checked on read; EDC/ECC not certified",
                  "tracks": [asdict(t) | {"index1_frame": t.index1_frame, "data_frames": t.data_frames}
                             for t in self.tracks],
                  "files": [{"name": name, "bytes": self._stamps[path][0]}
                            for name, path in self.referenced_files.items()]}
        if hash_file:
            result["file_sha256"] = sha256(self.path)
            result["image_sha256"] = self.image_sha256()
            for entry, path in zip(result["files"], self.referenced_files.values()):
                entry["sha256"] = sha256(path)
        self.check_unchanged()
        return result

    def _frame(self, track, frame):
        self.check_unchanged()
        with self.referenced_files[track.file].open("rb") as stream:
            stream.seek(frame * track.sector_bytes)
            raw = stream.read(track.sector_bytes)
        if len(raw) != track.sector_bytes:
            raise MediaError("Short CUE sector read")
        self.check_unchanged()
        return raw

    def sector(self, track: CueTrack, relative_sector: int):
        self.check_unchanged()
        if track not in self.tracks or type(relative_sector) is not int or not 0 <= relative_sector < track.data_frames:
            raise MediaError("Sector outside CUE track INDEX 01 payload")
        if track.type == "AUDIO":
            raise MediaError("CUE audio cannot be read as MODE1 data")
        raw = self._frame(track, track.file_index1 + relative_sector)
        if track.type == "MODE1_RAW":
            if raw[:12] != b"\x00" + b"\xff" * 10 + b"\x00" or raw[15] != 1:
                raise MediaError("Invalid CUE MODE1 raw sector header")
            return raw[16:2064]
        return raw

    def read(self, lba: int):
        self.check_unchanged()
        if type(lba) is int:
            for track in self.tracks:
                if track.disc_start <= lba < track.disc_start + track.data_frames:
                    return self.sector(track, lba - track.disc_start)
        raise MediaError("CUE data LBA falls in a gap or outside disc")

    lba = read

    def read_audio(self, lba: int):
        self.check_unchanged()
        if type(lba) is int:
            for track in self.tracks:
                begin = track.disc_start - (track.pregap if track.stored_pregap else 0)
                if track.type == "AUDIO" and begin <= lba < track.disc_start + track.data_frames:
                    return struct.unpack("<1176h", self._frame(track, track.file_index1 + lba - track.disc_start))
        raise MediaError("CUE audio LBA is data, a virtual gap, or outside disc")

    def audio_playable(self, lba: int):
        self.check_unchanged()
        if type(lba) is not int:
            return False
        for index, track in enumerate(self.tracks):
            if track.disc_start <= lba < track.disc_start + track.data_frames:
                return track.type == "AUDIO"
            if track.stored_pregap and track.disc_start - track.pregap <= lba < track.disc_start:
                return track.type == "AUDIO" and index > 0 and self.tracks[index - 1].type == "AUDIO"
        return False
