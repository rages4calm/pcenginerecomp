"""Authored firmware copies a resident thunk before loading alternative CD code."""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('resident_base_fixture',Path(__file__).parents[1]/'live-overlays/fixture.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
MPR=base.MPR

def resident():
    # Preserve the actual popped caller word, then synthesize RTS -> $6020.
    thunk=bytes.fromhex('68 AA 68 A8 98 48 8A 48 A9 60 48 A9 1F 48 60')
    return thunk+bytes(32-len(thunk))+bytes.fromhex('62 82 C2 60')+bytes(28)

def firmware():
    raw,labels=base.firmware();raw=bytearray(raw)
    # Original authored startup, source ROM $E780 -> CD RAM bank $82/$6000.
    code=bytes.fromhex('D4 A2 FF 9A A9 FF 53 01 A9 F8 53 02 A9 82 53 08 73 80 E7 00 60 40 00 4C 00 E2')
    raw[0x700:0x700+len(code)]=code;raw[0x780:0x7C0]=resident();raw[8190:8192]=bytes.fromhex('00 E7')
    return bytes(raw),labels

def sector(phase):
    # Change MPR3 from executable code in MPR2, then call the resident source.
    code=bytes.fromhex('A9 82 53 08 20 00 60')+base.sector(phase)[:20]
    return code+bytes(2048-len(code))

def disc():return bytes(2048)+sector(1)+sector(2)+bytes(2048*47)

def expected_cd(phase):
    raw=bytearray(sector(phase)+bytes(65536-2048));raw[0x4000:0x4040]=resident();return bytes(raw)

def expected_wram(phase,variant,*,released=True,finished=False):
    raw=bytearray(base.expected_wram(phase,variant,released=released,finished=finished))
    if released or phase==2:raw[0x1FC:0x1FE]=bytes.fromhex('1F 60')
    else:raw[0x1FD]=0xFF
    if finished:raw[0x1FE:0x200]=bytes.fromhex('06 40')
    return bytes(raw)
