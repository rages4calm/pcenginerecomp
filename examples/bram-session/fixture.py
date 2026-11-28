"""Authored reset firmware that observes and updates isolated backup memory."""
import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('bram_assembler',Path(__file__).parents[1]/'live-overlays/fixture.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
FORMATTED=b'HUBM\x00\x88\x10\x80'+bytes(2040)


def program():
    a=base.Assembler(0xE200)
    a.emit('78 D8 D4 A9 FF 53 01 A9 F8 53 02 A9 F7 53 04 A2 FF 9A')
    a.emit('9C 00 20 9C 01 20 9C 02 20 A9 80 8D 07 18')
    # Observe every BRAM byte through actual guest reads, without a TCP peek.
    a.emit('73 00 40 00 28 00 08 A9 01 8D 00 20')
    a.label('gate');a.emit('AD 01 20 C9 01');a.branch(0xD0,'gate')
    a.emit('AD 10 40 49 5A 8D 10 40 AD FF 47 49 A5 8D FF 47')
    a.emit('73 00 40 00 30 00 08 AD 03 18 AD 00 40 8D 02 20')
    a.emit('A9 02 8D 00 20');a.label('done');a.emit('80 FE')
    return a.finish(),dict(a.labels)


def firmware():
    code,_=program();raw=bytearray(262144)
    if len(code)>8190-512:raise ValueError('Authored firmware exceeds reset bank')
    raw[512:512+len(code)]=code;raw[8190:8192]=b'\x00\xE2'
    return bytes(raw)


def expected_output(seed):
    if type(seed) is not bytes or len(seed)!=2048:raise ValueError('Expected exactly2048 authored bytes')
    result=bytearray(seed);result[16]^=0x5A;result[-1]^=0xA5
    return bytes(result)


def saved_pattern():
    return bytes((index*37+61)&255 for index in range(2048))
