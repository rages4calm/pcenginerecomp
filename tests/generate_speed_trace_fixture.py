"""Authored mixed-speed firmware and independent instruction/device literals.

Every setup operation is guest code. The timer stays masked throughout. The
literal model describes this finite fixture, not an alternate CPU emulator.
"""
from pathlib import Path
import hashlib,json,sys,tempfile
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))

PRIMER=[('sei',),('lda',0),('tam',0xFD),('lda',0xF8),('tam',2),
        ('lda',0),('store',0x2000),('tii',),('ldx',255),('txs',),
        ('ldx',0),('ldy',0),('lda',4),('pha',),('plp',),('lda',255),
        ('tam',4),('lda',7),('store',0x5402),('lda',0)]
MEASURED=[('store',0x4C01),('store',0x4C00),('lda',1),('store',0x4C01),
          ('speed',12),('nop',),('speed',3),('nop',),('speed',3),('nop',),
          ('speed',12),('nop',)]+[('nop',)]*130+[
          ('load',0x4C00),('and',127),('store',0x20F0),
          ('load',0x5403),('and',7),('store',0x20F1),
          ('load',0x5402),('and',7),('store',0x20F2),
          ('lda',0),('store',0x5403),('load',0x5403),('and',7),('store',0x20F3),
          ('store',0x4C01),('speed',3),('speed',3),('speed',12),('speed',12)]
ENC={'sei':(0x78,), 'lda':(0xA9,), 'ldx':(0xA2,), 'ldy':(0xA0,),
     'tam':(0x53,), 'txs':(0x9A,), 'pha':(0x48,), 'plp':(0x28,),
     'store':(0x8D,), 'load':(0xAD,), 'and':(0x29,), 'nop':(0xEA,)}
def encode(op):
    name=op[0]
    if name=='tii':return bytes.fromhex('73 00 20 01 20 FF 1F')
    if name=='speed':return bytes((0x54 if op[1]==12 else 0xD4,))
    prefix=bytes(ENC[name])
    if len(op)==1:return prefix
    return prefix+int(op[1]).to_bytes(2 if name in ('store','load')else 1,'little')
PRIMER_STEPS=len(PRIMER)
STEPS=len(MEASURED)
MARKER=0xE000+sum(map(lambda op:len(encode(op)),PRIMER))
def firmware():
    rom=bytearray([0xEA]*262144);code=b''.join(map(encode,PRIMER+MEASURED))+bytes.fromhex('80 FE')
    rom[:len(code)]=code;rom[0x1FFE:0x2000]=bytes.fromhex('00 E0')
    return bytes(rom)

def expected_rows(profile):
    assert profile in ('runtime','gear')
    pc=MARKER;a=x=y=0;p=6;sp=255;divisor=12;ticks=0
    latch=7;enabled=False;reload=counter=0;deadline=None;pending=False;mask=7;frozen_phase=0
    ram=[0,0,0,0];rows=[]
    def sync():
        nonlocal counter,pending,deadline
        while enabled and ticks>=deadline:
            if counter==0:counter=reload;pending=True
            else:counter-=1
            deadline+=3072
    for op in MEASURED:
        name=op[0];cycles=2
        if name in ('lda','load','and'):
            if name=='lda':a=op[1]
            elif name=='and':a &=op[1]
            else:
                cycles=5
                if op[1]==0x4C00:a=(latch&128)|(127 if counter==0 and enabled and deadline-ticks<=15 else counter);latch=a
                elif op[1]==0x5403:a=(latch&248)|(4 if pending else 0);latch=a
                elif op[1]==0x5402:a=(latch&248)|mask;latch=a
                else:raise ValueError(op)
            p=(p&~130)|(a&128)|(2 if a==0 else 0)
        elif name=='store':
            cycles=5;address=op[1]
            if 0x20F0<=address<=0x20F3:ram[address-0x20F0]=a
            else:
                latch=a
                if address==0x4C00:reload=a&127
                elif address==0x4C01:
                    new=bool(a&1)
                    if new!=enabled:
                        enabled=new
                        frozen_phase=3072
                        if new:counter=reload;deadline=ticks+3072
                        else:deadline=None
                elif address==0x5403:pending=False
                else:raise ValueError(op)
        elif name=='speed':
            target=op[1];ticks+=(2*divisor+target)if profile=='runtime'else 3*target
            divisor=target;cycles=0
        elif name!='nop':raise ValueError(op)
        ticks+=cycles*divisor;sync();pc+=len(encode(op))
        rows.append([pc,a,x,y,sp,p,divisor,ticks,0,248,255,0,0,0,0,0,255,
                     int(enabled),reload,counter,int(pending),mask,deadline-ticks if enabled else frozen_phase,*ram])
    return rows

def generate(out,*,emit_module=True):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);raw=firmware();digest=hashlib.sha256(raw).hexdigest()
    (out/'authored.pce').write_bytes(raw)
    (out/'snapshot.toml').write_text('schema = 1\nmpr = [0,0,0,0,0,0,0,0]\nentry_points = [57344]\n[[segments]]\nphysical = 0\nfile = "authored.pce"\nsha256 = "'+digest+'"\n',encoding='utf-8')
    if emit_module:
        from pcerecomp.analysis import Snapshot,analyze
        from pcerecomp.emitter import emit
        graph=analyze(Snapshot.load(out/'snapshot.toml'),follow_mappings=True)
        if graph['unresolved']:raise ValueError('Authored linear mapping graph must close')
        (out/'analysis.json').write_text(json.dumps(graph,indent=2)+'\n',encoding='utf-8')
        # Build-system regeneration replaces only our newly generated module
        # files. Emit in a fresh owned directory so stale outputs cannot be
        # mistaken for successful emission or violate the emitter's guard.
        with tempfile.TemporaryDirectory(prefix='speed-module-',dir=out) as stage:
            emit(graph,Path(stage))
            for path in Path(stage).iterdir():path.replace(out/path.name)
    code=b''.join(map(encode,PRIMER+MEASURED))+bytes.fromhex('80 FE')
    header=['#pragma once','#include <array>','#include <cstdint>','#include <vector>','#include <algorithm>',f'inline constexpr unsigned speed_primer_steps={PRIMER_STEPS},speed_trace_steps={STEPS},speed_marker={MARKER};',
            'inline std::vector<std::uint8_t> speed_rom(){std::vector<std::uint8_t> r(262144,0xEA);const std::uint8_t code[]{'+','.join(map(str,code))+'};std::copy(std::begin(code),std::end(code),r.begin());r[8190]=0;r[8191]=0xE0;return r;}']
    for profile in ('runtime','gear'):
        rows=expected_rows(profile);header +=[f'inline constexpr std::array<std::array<std::uint64_t,27>,{STEPS}> speed_expected_{profile}'+'{{']
        header += ['{{'+','.join(map(str,row))+'}},' for row in rows];header+=['}};']
    (out/'speed_trace_fixture.hpp').write_text('\n'.join(header)+'\n',encoding='utf-8')
    (out/'fixture.json').write_text(json.dumps(dict(schema=1,firmware_sha256=digest,primer_steps=PRIMER_STEPS,steps=STEPS,marker=MARKER,profile='software-primer-mixed-speed-masked-timer-v1',clock_basis='Raw clocks retained. Finite literals use elapsed master ticks from actual post-primer initial record, explicitly declared.',initialization='Guest SEI, MPR setup, full WRAM clear via TII, explicit registers/SP/P, real IRQ mask write; not hardware reset certification.',runtime_rows=expected_rows('runtime'),gear_rows=expected_rows('gear')),indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':generate(Path(sys.argv[1]))
