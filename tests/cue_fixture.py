"""Small authored BIN/CUE images with independently declared disc geometry.

No input is derived from software or firmware. Expected disc mappings are
literal case definitions, not output from either production CUE parser.
"""
import hashlib
from pathlib import Path
import struct


def data_sector(seed, frame):
    return bytes((seed * 23 + frame * 29 + i * 17 + (i >> 8) * 7) & 255
                 for i in range(2048))


def audio_sector(seed, frame):
    anchors = (-32768, 32767, -1, 1, -12345, 23456, 0, 16384)
    return [anchors[(i * 3 + seed + frame) % 8] if i % 19 else
            ((seed * 1231 + frame * 997 + i * 37) % 65536) - 32768
            for i in range(1176)]


def raw_sector(seed, frame):
    return b'\0' + b'\xff' * 10 + b'\0\0\0\0\1' + data_sector(seed, frame) + bytes(288)


def definitions():
    # Map entries: (disc LBA, kind, seed, file frame); 's' is a stored AUDIO
    # pregap. Gate exclusions are separately literal, rather than inferred.
    return [
        dict(id='cooked-single', cue='FILE "data.bin" BINARY\n'
             ' TRACK 01 MODE1/2048\n  INDEX 01 00:00:00\n',
             files=[('data.bin', [('d', 1, f) for f in range(6)])],
             tracks=[[0, 4]], leadout=6,
             mapping=[(f, 'd', 1, f) for f in range(6)], playable=[]),
        dict(id='raw-single', cue='REM authored raw MODE1, no ECC claim\n'
             'FILE "raw.bin" BINARY\n TRACK 01 MODE1/2352\n INDEX 01 00:00:00\n',
             files=[('raw.bin', [('r', 2, f) for f in range(8)])],
             tracks=[[0, 4]], leadout=8,
             mapping=[(f, 'd', 2, f) for f in range(8)], playable=[]),
        dict(id='single-mixed-stored', cue='FILE "mixed.bin" BINARY\n'
             ' TRACK 01 MODE1/2352\n  INDEX 01 00:00:00\n'
             ' TRACK 02 AUDIO\n  INDEX 00 00:00:02\n  INDEX 01 00:00:04\n'
             ' TRACK 03 AUDIO\n  INDEX 00 00:00:07\n  INDEX 01 00:00:08\n'
             ' TRACK 04 MODE1/2352\n  INDEX 01 00:00:10\n',
             files=[('mixed.bin', [('r' if f < 2 or f >= 10 else 'a', 3, f)
                                   for f in range(12)])],
             tracks=[[0, 4], [4, 0], [8, 0], [10, 4]], leadout=12,
             mapping=[(f, 'd' if f < 2 or f >= 10 else 's' if f in (2, 3, 7) else 'a', 3, f)
                      for f in range(12)], playable=list(range(4, 10))),
        dict(id='multi-virtual', cue='FILE "cooked.bin" BINARY\n'
             ' TRACK 01 MODE1/2048\n  INDEX 01 00:00:00\n'
             'FILE "audio.bin" BINARY\n TRACK 02 AUDIO\n'
             ' PREGAP 00:00:02\n INDEX 01 00:00:00\n',
             files=[('cooked.bin', [('d', 4, f) for f in range(6)]),
                    ('audio.bin', [('a', 5, f) for f in range(4)])],
             tracks=[[0, 4], [8, 0]], leadout=12,
             mapping=[(f, 'd', 4, f) for f in range(6)] +
                     [(8 + f, 'a', 5, f) for f in range(4)], playable=list(range(8, 12))),
        dict(id='multi-stored', cue='FILE "first.bin" BINARY\n'
             ' TRACK 01 MODE1/2352\n INDEX 01 00:00:00\n'
             'FILE "second.bin" BINARY\n TRACK 02 AUDIO\n'
             ' INDEX 00 00:00:00\n INDEX 01 00:00:02\n',
             files=[('first.bin', [('r', 6, f) for f in range(2)]),
                    ('second.bin', [('a', 7, f) for f in range(6)])],
             tracks=[[0, 4], [4, 0]], leadout=8,
             mapping=[(f, 'd', 6, f) for f in range(2)] +
                     [(2 + f, 's' if f < 2 else 'a', 7, f) for f in range(6)],
             playable=list(range(4, 8))),
        dict(id='audio-first-paths', cue='TITLE "Authored paths and audio"\n'
             'FILE "tracks/audio source.bin" BINARY\n TRACK 01 AUDIO\n'
             ' INDEX 01 00:00:00\n TRACK 02 AUDIO\n INDEX 00 00:00:03\n INDEX 01 00:00:04\n'
             'FILE "tracks/data source.bin" BINARY\n TRACK 03 MODE1/2048\n INDEX 01 00:00:00\n',
             files=[('tracks/audio source.bin', [('a', 8, f) for f in range(6)]),
                    ('tracks/data source.bin', [('d', 9, f) for f in range(3)])],
             tracks=[[0, 0], [4, 0], [6, 4]], leadout=9,
             mapping=[(f, 's' if f == 3 else 'a', 8, f) for f in range(6)] +
                     [(6 + f, 'd', 9, f) for f in range(3)], playable=list(range(6))),
    ]


def write_case(root, case):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    cue = root / 'authored.cue'
    cue.write_bytes(case['cue'].encode('utf-8'))
    for name, frames in case['files']:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = b''
        for kind, seed, frame in frames:
            payload += (data_sector(seed, frame) if kind == 'd' else raw_sector(seed, frame)
                        if kind == 'r' else struct.pack('<1176h', *audio_sector(seed, frame)))
        path.write_bytes(payload)
    return cue


def expected(case):
    by_lba = {lba: (kind, seed, frame) for lba, kind, seed, frame in case['mapping']}
    observations = []
    for lba in range(case['leadout'] + 1):
        observations.append(dict(op='p', lba=lba, playable=lba in case['playable']))
        item = by_lba.get(lba)
        if item:
            kind, seed, frame = item
            if kind == 'd':
                observations.append(dict(op='d', lba=lba, bytes=data_sector(seed, frame).hex()))
            else:
                observations.append(dict(op='a', lba=lba, samples=audio_sector(seed, frame)))
    return dict(leadout=case['leadout'], tracks=case['tracks'], observations=observations)


def composite_identity(cue, case):
    """Independent encoding from declared files; never imports production parser."""
    cue = Path(cue)
    raw = cue.read_bytes()
    text = f'PCE-CUE-1\ncue\t{len(raw)}\t{hashlib.sha256(raw).hexdigest()}\n'
    for name, _ in case['files']:
        raw = (cue.parent / name).read_bytes()
        text += f'file\t{name}\t{len(raw)}\t{hashlib.sha256(raw).hexdigest()}\n'
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def write_plan(path, result):
    rows = result['observations']
    Path(path).write_text(str(len(rows)) + '\n' + ''.join(f"{r['op']} {r['lba']}\n" for r in rows),
                          encoding='ascii')
