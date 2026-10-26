"""Authored indirect-load/store sites for exhaustive hardware decode tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
MPR=(0,0xF8,0,0,0,0xFF,0xFF,0)
CODE=bytes.fromhex('B2 10 92 10 80 FE')
def firmware():
    rom=bytearray([0xEA]*262144);rom[:len(CODE)]=CODE;rom[8190:8192]=bytes.fromhex('00 E0');return bytes(rom)
def generate(out):
    from pcerecomp.analysis import Snapshot,analyze
    from pcerecomp.emitter import emit
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    graph=analyze(Snapshot(MPR,dict(enumerate(CODE)),(0xE000,0xE002),'authored-cd-decode-v1'))
    if graph['unresolved']:raise ValueError('Authored decode sites must close')
    with TemporaryDirectory(prefix='cd-decode-module-',dir=out)as stage:
        emit(graph,Path(stage))
        for path in Path(stage).iterdir():path.replace(out/path.name)
    (out/'authored.pce').write_bytes(firmware())
    header=['#pragma once','#include <array>','#include <algorithm>','#include <cstdint>','#include <vector>',
        'inline constexpr std::array<std::uint8_t,8> cd_decode_mpr{'+','.join(map(str,MPR))+'};',
        'inline constexpr std::uint16_t cd_decode_read_pc=0xE000,cd_decode_write_pc=0xE002;',
        'inline std::vector<std::uint8_t> cd_decode_rom(){std::vector<std::uint8_t> rom(262144,0xEA);const std::uint8_t code[]{'+','.join(map(str,CODE))+'};std::copy(std::begin(code),std::end(code),rom.begin());rom[8190]=0;rom[8191]=0xE0;return rom;}']
    (out/'cd_decode_fixture.hpp').write_text('\n'.join(header)+'\n',encoding='utf-8')
if __name__=='__main__':generate(Path(sys.argv[1]))
