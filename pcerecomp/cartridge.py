"""Explicit, read-only base HuCard input conversion and selected bank map.

The 512 KiB layout is the Gear/Mesen compatibility map; physical boards are
not inferred from a ROM checksum. Cartridge RAM and enhanced mappers need
separate profiles. Nothing here executes a game or supplies firmware.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path

MAX_ROM_BYTES = 1024 * 1024
HEADERS = ('none', 'copier512')
ENCODINGS = ('linear', 'bit-reversed')
_REVERSE = bytes(sum(((value >> bit) & 1) << (7-bit) for bit in range(8))
                 for value in range(256))


def bank_map(size):
    if type(size) is not int or not 8192 <= size <= MAX_ROM_BYTES or size % 8192:
        raise ValueError('HuCard ROM requires 8 KiB aligned bytes in 8 KiB..1 MiB')
    count = size // 8192
    if count == 48:
        return tuple((bank & 31) if bank < 64 else 32+(bank & 15) for bank in range(128))
    if count in (64, 96):
        upper = 32 if count == 64 else 64
        return tuple((bank & 63) if bank < 64 else upper+(bank & 31) for bank in range(128))
    return tuple(bank % count for bank in range(128))


def decode(raw, header='none', encoding='linear'):
    if header not in HEADERS or encoding not in ENCODINGS:
        raise ValueError('HuCard requires explicit none/copier512 header and linear/bit-reversed encoding')
    if not isinstance(raw, bytes):
        raise ValueError('HuCard decoder requires raw bytes')
    rom = raw[512:] if header == 'copier512' else raw
    bank_map(len(rom))  # Bounds/alignment before conversion; no padding.
    return rom.translate(_REVERSE) if encoding == 'bit-reversed' else rom


def _stamp(path):
    if not path.is_file():
        raise ValueError('HuCard input must be a regular file')
    stat = path.stat()
    if not 8192 <= stat.st_size <= MAX_ROM_BYTES+512:
        raise ValueError('HuCard input exceeds the supported ROM/header size')
    return stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino


@dataclass(frozen=True)
class Cartridge:
    path: Path
    header: str = 'none'
    encoding: str = 'linear'

    def __post_init__(self):
        path = Path(self.path).resolve()
        initial = _stamp(path)
        raw = path.read_bytes()
        if len(raw) != initial[0] or _stamp(path) != initial:
            raise ValueError('HuCard input changed during read')
        rom = decode(raw, self.header, self.encoding)
        object.__setattr__(self, 'path', path)
        object.__setattr__(self, '_initial', initial)
        object.__setattr__(self, 'rom', rom)
        object.__setattr__(self, 'raw_sha256', hashlib.sha256(raw).hexdigest())
        object.__setattr__(self, 'decoded_sha256', hashlib.sha256(rom).hexdigest())
        object.__setattr__(self, 'banks', bank_map(len(rom)))
        object.__setattr__(self, 'reset_pc', int.from_bytes(rom[8190:8192], 'little'))

    def check_unchanged(self):
        if _stamp(self.path) != self._initial:
            raise ValueError('HuCard input changed after identity verification')

    def mapped_rom(self):
        self.check_unchanged()
        return b''.join(self.rom[bank*8192:(bank+1)*8192] for bank in self.banks)

    def report(self):
        self.check_unchanged()
        return dict(format='hucard-base', profile='base', header=self.header,
                    encoding=self.encoding, file_bytes=self._initial[0], rom_bytes=len(self.rom),
                    file_sha256=self.raw_sha256, decoded_rom_sha256=self.decoded_sha256,
                    mapper='gear-mesen-base-compat-v1', bank_map=list(self.banks),
                    vector_physical=8190, reset_pc=self.reset_pc,
                    scope='Explicit input conversion and mapping; no execution or hardware-board detection')
