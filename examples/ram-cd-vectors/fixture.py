"""Authored resident/CD code with indexed and non-indexed pointer words."""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('vector_resident_base',Path(__file__).parents[1]/'resident-far-calls/fixture.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
MPR=base.MPR

def resident():
    raw=bytearray(base.resident())
    raw[32:64]=bytes(32)
    # Real saved-return thunk -> $6020, known X=2 -> $6028 -> $602C.
    # Pointer bytes at $6032/$6034 are explicit authenticated data.
    raw[32:37]=bytes.fromhex('A2 02 7C 30 60')
    raw[40:43]=bytes.fromhex('6C 34 60')
    raw[44:48]=bytes.fromhex('62 82 C2 60')
    raw[50:54]=bytes.fromhex('28 60 2C 60')
    return bytes(raw)

def firmware():
    raw,labels=base.firmware();raw=bytearray(raw);raw[0x780:0x7C0]=resident()
    return bytes(raw),labels

def sector(phase):return base.sector(phase)
def disc():return bytes(2048)+sector(1)+sector(2)+bytes(2048*47)
def expected_wram(*args,**kwargs):return base.expected_wram(*args,**kwargs)
def expected_cd(phase):
    raw=bytearray(sector(phase)+bytes(65536-2048));raw[0x4000:0x4040]=resident();return bytes(raw)
