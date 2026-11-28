"""Authored CD overlays with a balanced call and explicit writable data."""
import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('ram_cd_base_fixture',Path(__file__).parents[1]/'live-overlays/fixture.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
MPR=base.MPR
firmware=base.firmware


def sector(phase):
    # JSR $4018; original conditional body; padding; PHA/STZ $4030/PLA/RTS.
    # $4030 is mutable data, never an executable candidate or a constant fact.
    code=bytes.fromhex('20 18 40')+base.sector(phase)[:20]+b'\xEA'+bytes.fromhex('48 9C 30 40 68 60')
    return code+bytes(2048-len(code))


def disc():return bytes(2048)+sector(1)+sector(2)+bytes(2048*47)


def expected_cd(phase):return sector(phase)+bytes(65536-2048)


def expected_wram(phase,variant,*,released=True,finished=False):
    ram=bytearray(base.expected_wram(phase,variant,released=released,finished=finished))
    ram[0x1FD]=phase if released else phase-1
    if finished:ram[0x1FE:0x200]=bytes.fromhex('02 40')
    return bytes(ram)
