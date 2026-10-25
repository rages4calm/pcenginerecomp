"""Explicit, read-only HuCard input conversion and selected board maps.

The 512 KiB layout is the Gear/Mesen compatibility map; physical boards are
not inferred from a ROM checksum. Enhanced boards are selected by name, never
by checksum, title or size heuristics. Nothing here executes a game or supplies
firmware; mapped source snapshots cannot reconstruct a running mapper.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path

MAX_ROM_BYTES = 0x280000
PROFILES = ('base', 'sf2', 'populous')
HEADERS = ('none', 'copier512')
ENCODINGS = ('linear', 'bit-reversed')
_REVERSE = bytes(sum(((value >> bit) & 1) << (7-bit) for bit in range(8))
                 for value in range(256))


def bank_map(size, profile='base', selector=0):
    """Initial ROM file banks; None marks RAM, never executable ROM padding.

    SF2 exposes its fixed first 512 KiB and one of four following 512 KiB
    windows. Selector is the four-bit address latch; data writes do not choose
    it. File-bank indices can exceed the guest's eight-bit physical bank.
    """
    if type(profile) is not str or profile not in PROFILES:
        raise ValueError('HuCard requires an explicit base, sf2 or populous profile')
    if type(selector) is not int or not 0 <= selector <= 15 or (profile != 'sf2' and selector):
        raise ValueError('Only SF2 has a four-bit mapper selector')
    if profile == 'sf2':
        if type(size) is not int or size != 0x280000:
            raise ValueError('SF2 HuCard requires exactly 2.5 MiB of decoded ROM')
        return tuple(bank if bank < 64 else bank+(selector % 4)*64 for bank in range(128))
    if profile == 'populous' and (type(size) is not int or size != 0x80000):
        raise ValueError('Populous HuCard requires exactly 512 KiB of decoded ROM')
    if type(size) is not int or not 8192 <= size <= 0x100000 or size % 8192:
        raise ValueError('Base HuCard ROM requires 8 KiB aligned bytes in 8 KiB..1 MiB')
    count = size // 8192
    if count == 48:
        return tuple((bank & 31) if bank < 64 else 32+(bank & 15) for bank in range(128))
    if count in (64, 96):
        upper = 32 if count == 64 else 64
        return tuple(None if profile == 'populous' and 64 <= bank < 96 else
                     (bank & 63) if bank < 64 else upper+(bank & 31) for bank in range(128))
    return tuple(bank % count for bank in range(128))


def decode(raw, header='none', encoding='linear', profile='base'):
    if header not in HEADERS or encoding not in ENCODINGS:
        raise ValueError('HuCard requires explicit none/copier512 header and linear/bit-reversed encoding')
    if not isinstance(raw, bytes):
        raise ValueError('HuCard decoder requires raw bytes')
    rom = raw[512:] if header == 'copier512' else raw
    bank_map(len(rom), profile)  # Bounds/alignment before conversion; no padding.
    return rom.translate(_REVERSE) if encoding == 'bit-reversed' else rom


def _stamp(path, profile):
    if type(profile) is not str or profile not in PROFILES:
        raise ValueError('HuCard requires an explicit base, sf2 or populous profile')
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
    profile: str = 'base'

    def __post_init__(self):
        path = Path(self.path).resolve()
        initial = _stamp(path, self.profile)
        raw = path.read_bytes()
        if len(raw) != initial[0] or _stamp(path, self.profile) != initial:
            raise ValueError('HuCard input changed during read')
        rom = decode(raw, self.header, self.encoding, self.profile)
        object.__setattr__(self, 'path', path)
        object.__setattr__(self, '_initial', initial)
        object.__setattr__(self, 'rom', rom)
        object.__setattr__(self, 'raw_sha256', hashlib.sha256(raw).hexdigest())
        object.__setattr__(self, 'decoded_sha256', hashlib.sha256(rom).hexdigest())
        object.__setattr__(self, 'banks', bank_map(len(rom), self.profile))
        object.__setattr__(self, 'reset_pc', int.from_bytes(rom[8190:8192], 'little'))

    def check_unchanged(self):
        if _stamp(self.path, self.profile) != self._initial:
            raise ValueError('HuCard input changed after identity verification')

    def mapped_rom(self):
        self.check_unchanged()
        return b''.join(bytes(8192) if bank is None else self.rom[bank*8192:(bank+1)*8192]
                        for bank in self.banks)

    def rom_ranges(self):
        """Driven initial ROM ranges only; exclude the Populous RAM aperture."""
        return ((0, 0x80000), (0xC0000, 0x40000)) if self.profile == 'populous' else ((0, 0x100000),)

    def report(self):
        self.check_unchanged()
        result = dict(format='hucard-'+self.profile, profile=self.profile, header=self.header,
                    encoding=self.encoding, file_bytes=self._initial[0], rom_bytes=len(self.rom),
                    file_sha256=self.raw_sha256, decoded_rom_sha256=self.decoded_sha256,
                    mapper={'base': 'gear-mesen-base-compat-v1', 'sf2': 'sf2-window-v1',
                            'populous': 'populous-ram-v1'}[self.profile], bank_map=list(self.banks),
                    vector_physical=8190, reset_pc=self.reset_pc,
                    scope='Explicit input conversion and mapping; no execution or hardware-board detection')
        if self.profile == 'sf2':
            result.update(mapper_latch=0, switched_window=[0x80000, 0x80000])
        elif self.profile == 'populous':
            result.update(cartridge_ram_bytes=32768, ram_aperture=[0x80000, 0x40000],
                          ram_persistence=False)
        return result
