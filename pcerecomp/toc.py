"""Bounded, metadata-only CD table-of-contents export.

INDEX 01 and leadout use disc LBAs, excluding the 150-frame lead-in. CHD
storage padding never contributes to these coordinates. This descriptor
contains no sectors and does not make a runtime sector provider available.
"""

from dataclasses import dataclass
from pathlib import Path
import re

from .media import Chd, IsoReader, MediaError, sha256
from .cue import Cue


MAX_DESCRIPTOR_BYTES = 8192
MAX_LEADOUT_LBA = 449849  # +150 fits the absolute BCD limit 99:59:74.


@dataclass(frozen=True)
class TocTrack:
    number: int
    index1_lba: int
    type: int  # 0 audio, 4 data; sector formats are not decoded by this module.


@dataclass(frozen=True)
class Toc:
    image_sha256: str
    leadout_lba: int
    tracks: tuple[TocTrack, ...]

    def __post_init__(self):
        if not isinstance(self.image_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.image_sha256):
            raise MediaError("TOC image SHA256 must be 64 lowercase hex digits")
        if type(self.leadout_lba) is not int or not 0 < self.leadout_lba <= MAX_LEADOUT_LBA:
            raise MediaError("TOC leadout exceeds the supported absolute BCD range")
        if not 1 <= len(self.tracks) <= 99:
            raise MediaError("TOC requires between 1 and 99 tracks")
        previous = -1
        for number, track in enumerate(self.tracks, 1):
            if type(track.number) is not int or track.number != number:
                raise MediaError("TOC tracks must be numbered consecutively from 1")
            if type(track.type) is not int or track.type not in (0, 4):
                raise MediaError("TOC track type must be 0 (audio) or 4 (data)")
            if type(track.index1_lba) is not int or not previous < track.index1_lba < self.leadout_lba:
                raise MediaError("TOC INDEX 01 LBAs must increase and precede leadout")
            previous = track.index1_lba

    def text(self) -> str:
        result = (f"PCE_TOC 1\nimage_sha256 {self.image_sha256}\n"
                  f"leadout_lba {self.leadout_lba}\n")
        result += "".join(f"track {t.number} {t.index1_lba} {t.type}\n" for t in self.tracks)
        if len(result.encode("ascii")) > MAX_DESCRIPTOR_BYTES:
            raise MediaError("TOC descriptor exceeds 8 KiB")
        return result

    @classmethod
    def from_image(cls, path: Path):
        path = Path(path)
        if path.suffix.lower() == ".chd":
            disc = Chd(path)
            tracks = []
            for track in disc.tracks:
                if track.type == "AUDIO":
                    kind = 0
                elif track.type in ("MODE1", "MODE1_RAW"):
                    kind = 4
                else:
                    raise MediaError(f"Unsupported TOC track type: {track.type}")
                tracks.append(TocTrack(track.number, track.disc_start, kind))
            last = disc.tracks[-1]
            # Match Geargrafx's CHD TOC: inter-track postgaps affect following
            # INDEX 01s, but trailing POSTGAP is outside its reported leadout.
            # This is an explicit reference choice, not console qualification.
            leadout = last.disc_start + last.data_frames
        elif path.suffix.lower() == ".iso":
            IsoReader(path)  # Validate complete 2048-byte cooked sectors.
            leadout = path.stat().st_size // 2048
            tracks = [TocTrack(1, 0, 4)]
        elif path.suffix.lower() == ".cue":
            disc = Cue(path)
            tracks = tuple(TocTrack(track.number, track.disc_start, 0 if track.type == "AUDIO" else 4)
                           for track in disc.tracks)
            return cls(disc.image_sha256(), disc.leadout_lba, tracks)
        else:
            raise MediaError("TOC export accepts CHD, supported BIN/CUE or single-track 2048-byte ISO")
        # Validate metadata before hashing a potentially large original image.
        candidate = cls("0" * 64, leadout, tuple(tracks))
        return cls(sha256(path), candidate.leadout_lba, candidate.tracks)
