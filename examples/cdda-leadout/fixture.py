"""Authored firmware and 25-track media for last-track CD audio commands."""
import importlib.util
import json
from pathlib import Path
import struct

from pcerecomp.toc import Toc

spec=importlib.util.spec_from_file_location('leadout_assembler',Path(__file__).parents[1]/'live-overlays/fixture.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)


def program():
    a=base.Assembler(0xE200)
    a.emit('78 D8 D4 A9 FF 53 01 A9 F8 53 02 A2 FF 9A')
    # The host seeds only physical WRAM $1F0002 before execution. Guest startup
    # owns its marker/gate/status cells and never overwrites that selected mode.
    a.emit('9C 00 20 9C 01 20 9C 10 20 9C 11 20')
    for index,value in enumerate((0xD8,0,0x25,0,0,0,0,0,0,0x80)):
        a.emit(f'A9 {value:02X} 8D {0x40+index:02X} 20')
    a.jump(0x20,'send');a.jump(0x20,'drain')
    a.emit('A9 D9 8D 40 20 AD 02 20 8D 41 20 A9 26 8D 42 20')
    a.jump(0x20,'send');a.emit('A9 01 8D 00 20')
    a.label('gate');a.emit('AD 01 20 C9 01');a.branch(0xD0,'gate')
    a.jump(0x20,'drain');a.emit('A9 02 8D 00 20');a.label('done');a.emit('80 FE')
    a.label('send');a.emit('9C 00 18 A2 00')
    a.label('command');a.emit('AD 00 18 C9 D0');a.branch(0xD0,'command')
    a.emit('BD 40 20 8D 01 18 A9 80 8D 02 18 9C 02 18 E8 E0 0A')
    a.branch(0xD0,'command');a.emit('60')
    a.label('drain');a.label('status');a.emit('AD 00 18 C9 D8');a.branch(0xD0,'status')
    a.emit('AD 01 18 8D 10 20 A9 80 8D 02 18 9C 02 18')
    a.label('message');a.emit('AD 00 18 C9 F8');a.branch(0xD0,'message')
    a.emit('AD 01 18 8D 11 20 A9 80 8D 02 18 9C 02 18')
    a.label('free');a.emit('AD 00 18');a.branch(0xD0,'free');a.emit('60')
    return a.finish(),dict(a.labels)


def firmware():
    code,_=program();raw=bytearray(262144)
    if len(code)>8190-512:raise ValueError('Authored firmware exceeds its source bank')
    raw[512:512+len(code)]=code;raw[8190:8192]=bytes.fromhex('00 E2')
    return bytes(raw)


def audio_bytes(track):
    if type(track) is not int or not 2<=track<=25:raise ValueError('Authored audio track must be 2..25')
    raw=bytearray()
    for frame in range(1176):
        sample=track*200+frame+1
        raw.extend(struct.pack('<hh',sample,-sample))
    return bytes(raw)


def _write(path,raw):
    with path.open('xb') as stream:stream.write(raw)


def create_media(out):
    """Write new immutable fixture files into the caller's existing directory."""
    out=Path(out).resolve(strict=True)
    if not out.is_dir():raise ValueError('Fixture output must be an existing directory')
    bios=out/'firmware.pce';disc=out/'disc.cue';toc=out/'disc.toc'
    _write(bios,firmware());_write(out/'data.bin',bytes(4*2048))
    cue=['FILE "data.bin" BINARY',' TRACK 01 MODE1/2048',' INDEX 01 00:00:00']
    for track in range(2,26):
        name=f'audio-{track:02d}.bin';_write(out/name,audio_bytes(track))
        cue.extend((f'FILE "{name}" BINARY',f' TRACK {track:02d} AUDIO',' INDEX 01 00:00:00'))
    _write(disc,('\n'.join(cue)+'\n').encode('ascii'))
    geometry=Toc.from_image(disc);_write(toc,geometry.text().encode('ascii'))
    _,labels=program()
    info=dict(track_count=25,last_track_lba=50,leadout_lba=52,labels=labels,
        scope='Authored 4-sector data track and 24 two-sector stereo PCM tracks; no proprietary media')
    _write(out/'fixture.json',(json.dumps(info,indent=2)+'\n').encode('utf-8'))
    return dict(bios=bios,disc=disc,toc=toc,**info)
