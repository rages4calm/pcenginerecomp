"""Two-bit fetch/latch checks with four unchanged extracted MesenCE functions.

Authored framework state only. This is not a full emulator or fetch-clock oracle.
External implementation bodies and generated executables stay private.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts import video_modes_reference as source

CASES=4*65536
METADATA=dict(cases=CASES,pixels=CASES*8,latches=CASES)
MAIN=r'''
int main(int argc,char** argv){if(argc!=2)return 2;
 try{std::ofstream out(argv[1],std::ios::binary);if(!out)return 2;
  Emulator emu;PceVdc vdc(&emu);
  for(unsigned high=0;high<2;++high)for(unsigned cg=0;cg<2;++cg)for(unsigned word=0;word<65536;++word){
   vdc.storage[0]=static_cast<uint16_t>(high?0x7800:0x7200);
   vdc.storage[0x2000]=static_cast<uint16_t>(word);vdc.storage[0x2008]=static_cast<uint16_t>(word^65535);
   vdc._vramOpenBus=static_cast<uint16_t>(word^0xA55A);
   vdc._state.HvLatch.CgMode=cg!=0;vdc._tileCount=0;vdc._loadBgLastCycle=0;
   vdc.LoadBackgroundTilesWidth4(8,0,31,0);
   if(vdc._tileCount!=1||vdc._allowVramAccess||vdc._tiles[0].TileData[1])return 3;
   for(unsigned x=0;x<8;++x){auto color=vdc.GetTilePixelColor(vdc._tiles[0].TileData[0],0,7-x);
    out.put(static_cast<char>(color?((vdc._tiles[0].Palette<<4)|color):0));}
   out.put(static_cast<char>(vdc._vramOpenBus));out.put(static_cast<char>(vdc._vramOpenBus>>8));
  }
  if(!out||emu.invalid_vram_reads!=131072)return 4;
  std::cout<<"{\"cases\":262144,\"pixels\":2097152,\"latches\":262144}\n";
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}}
'''

def literal_record(high,cg,word):
    value=0x7800 if high else word^(65535 if cg else 0)
    pixels=[]
    for x in range(8):
        bit=1<<(7-x)
        color=(1 if value&bit else 0)+(2 if value&(bit<<8) else 0)
        pixels.append(112+color if color else 0)
    return bytes(pixels)+value.to_bytes(2,'little')

def validate(raw):
    if len(raw)!=CASES*10:raise ValueError('Two-bit observation size differs')
    offset=0
    for high in range(2):
        for cg in range(2):
            for word in range(65536):
                if raw[offset:offset+10]!=literal_record(high,cg,word):
                    raise ValueError(f'Two-bit literal differs at high={high},cg={cg},word={word}')
                offset+=10
    return CASES*9 # Eight pixel values plus one complete 16-bit latch per case.

def run(args):
    external=args.mesen_source.resolve();probe=args.probe.resolve();out=args.out.resolve()
    compiler=shutil.which(str(args.compiler))
    if not compiler or not probe.is_file() or out.exists() or not out.is_relative_to(ROOT/'.local'):
        raise ValueError('Require compiler, existing toolkit probe and NEW private output')
    original=external/'PceVdc.cpp'
    if source.sha(original)!=source.SOURCES['PceVdc.cpp']:raise ValueError('Pinned Mesen source hash differs')
    authored=[Path(__file__),ROOT/'scripts/video_modes_reference.py',ROOT/'tests/vram_latch_modes_probe.cpp']
    bound={str(p):source.sha(p) for p in [original,probe,Path(compiler),*authored]}
    out.mkdir(parents=True)
    report=dict(schema=1,result='incomplete',mesen_commit=source.MESEN_COMMIT,bindings=bound,
        scope='Four unchanged extracted functions with authored framework state; two-bit CG selection, bit-11 undriven patterns, pixels and retained bus, not full emulator/timing/native CPU')
    try:
        # The diagnostic hook is inert in a non-debugging emulator. Count it;
        # do not replace ReadVram or any other extracted operation body.
        hook='void BreakIfDebugging(CpuType,BreakSource){throw std::runtime_error("Out-of-range reference VRAM");}'
        replacement='unsigned invalid_vram_reads=0; void BreakIfDebugging(CpuType,BreakSource){++invalid_vram_reads;}'
        if source.STUBS.count(hook)!=1:raise ValueError('Authored diagnostic-hook context changed')
        stubs=source.STUBS.replace(hook,replacement)
        definitions=[];spans=[]
        for name in source.FUNCTIONS:
            body,span=source.extract(original.read_bytes(),name);definitions.append(body);spans.append(span)
        program=out/'reference.cpp'
        program.write_bytes(stubs.encode()+source.CONTEXT.encode()+b'\n'.join(definitions)+MAIN.encode())
        report['extracted_functions']=spans;report['authored_hook']='Counts debugger notification without altering the returned VRAM value'
        exe=out/'reference.exe'
        with (out/'compile.log').open('wb') as log:
            subprocess.run([compiler,'-std=c++20','-O2',str(program),'-o',str(exe)],check=True,stdout=log,stderr=subprocess.STDOUT,timeout=60)
        checks={}
        for name,binary in (('mesen-functions',exe),('toolkit',probe)):
            target=out/(name+'.bin')
            completed=subprocess.run([str(binary),str(target)],capture_output=True,text=True,check=True,timeout=60)
            (out/(name+'.stdout')).write_text(completed.stdout);(out/(name+'.stderr')).write_text(completed.stderr)
            if json.loads(completed.stdout)!=METADATA:raise ValueError('Finite scope metadata differs')
            checks[name]=validate(target.read_bytes());bound[str(target)]=source.sha(target)
        if (out/'mesen-functions.bin').read_bytes()!=(out/'toolkit.bin').read_bytes():raise ValueError('Two-bit reference differs')
        bound[str(program)]=source.sha(program);bound[str(exe)]=source.sha(exe)
        report.update(result='pass',observations=METADATA,bytes=CASES*10,literal_values=checks)
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:
        report['preservation']={p:source.sha(Path(p))==digest for p,digest in bound.items()}
        if not all(report['preservation'].values()):report['result']='failed-preservation'
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('bindings','preservation')},indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mesen-source',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--compiler',default='clang++');parser.add_argument('--out',type=Path,required=True)
    try:run(parser.parse_args())
    except (ValueError,OSError,subprocess.SubprocessError) as error:print(error,file=sys.stderr);raise SystemExit(1)
