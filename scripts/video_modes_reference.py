"""Finite digital-video checks using separately supplied MesenCE source.

This compiles the unchanged complete default-video-filter header with authored
dependency stubs, and four byte-identical VDC function definitions extracted
from the pinned source. It exercises the selected-word decoder and RGB filter,
not a full emulator, CPU, VRAM bus schedule, latch edges, or analog output.
GPL reference material and compiled adapters stay in a NEW private directory.
The MIT toolkit executable is separate and never links external code.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
MESEN_COMMIT = '4b8a196e299b3de297b204fd1208d2981562c89b'
MESEN_REPOSITORY = 'https://github.com/nesdev-org/MesenCE'
SOURCES = {
    'PceVdc.cpp': 'b19dbf873d5d4e2c3abdb013065f90e3b54c5dc76a05722dc14a9f02f3b4d17e',
    'PceDefaultVideoFilter.h': '7213bd146b2e04ad88724254f8593e79d075f5a77c0e99b44748086fd748f220',
}
FUNCTIONS = ('LoadBackgroundTilesWidth4', 'LoadBatEntry', 'ReadVram', 'GetTilePixelColor')
PALETTE_BYTES = 512*3
PATTERN_BYTES = 2*65536*8


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(source, name):
    """Retain the complete original definition bytes and its one-based span."""
    token = b'PceVdc::' + name.encode() + b'('
    offset = source.index(token)
    start = source.rfind(b'\n', 0, offset) + 1
    opening = source.index(b'{', offset)
    depth, end = 1, opening + 1
    while depth:
        if end >= len(source):
            raise ValueError('Unbalanced pinned reference definition')
        depth += (source[end] == 123) - (source[end] == 125)
        end += 1
    definition = source[start:end]
    return definition, dict(function=name, first_line=source[:start].count(b'\n')+1,
                           last_line=source[:end].count(b'\n')+1,
                           sha256=hashlib.sha256(definition).hexdigest())


# These are authored type/dependency substitutes, not emulator implementations.
# Uncalled framework methods only make the complete upstream filter header parse.
STUBS = r'''#pragma once
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <array>
#include <iostream>
#include <fstream>
struct FrameInfo {uint32_t Width=256, Height=242;};
struct HudScaleFactors {double X,Y;};
struct OverscanDimensions {uint32_t Top=0,Bottom=0,Left=0,Right=0;};
struct VideoConfig {double Hue=0,Saturation=0,Brightness=0,Contrast=0;};
struct PcEngineConfig {bool ForceFixedResolution=false; uint32_t Palette[512]={};};
struct Settings {VideoConfig video;PcEngineConfig pce;
 VideoConfig& GetVideoConfig(){return video;} PcEngineConfig& GetPcEngineConfig(){return pce;}};
enum class RomFormat {PceHes,Other};
enum class CpuType {Pce};enum class BreakSource {PceBreakOnInvalidVramAddress};
struct RomInfo {RomFormat Format=RomFormat::Other;};
struct Emulator {Settings settings;Settings* GetSettings(){return &settings;}
 RomInfo GetRomInfo(){return {};}
 void BreakIfDebugging(CpuType,BreakSource){throw std::runtime_error("Out-of-range reference VRAM");}};
namespace PceConstants {constexpr uint32_t MaxScreenWidth=1024,ScreenHeight=242,InternalResMultipler=4;
 inline uint32_t GetRowWidth(unsigned divider){return divider?1024/divider:1024;}
 inline uint32_t GetLeftOverscan(unsigned){return 0;}}
struct BaseVideoFilter {
 Emulator* _emu;uint16_t* _ppuOutputBuffer=nullptr;FrameInfo _frameInfo{},_baseFrameInfo{};
 explicit BaseVideoFilter(Emulator* e):_emu(e){} virtual ~BaseVideoFilter()=default;
 virtual FrameInfo GetFrameInfo(){return {};}
 virtual HudScaleFactors GetScaleFactor(){return {1,1};}
 virtual OverscanDimensions GetOverscan(){return {};}
 virtual void OnBeforeApplyFilter(){} virtual void ApplyFilter(uint16_t*){}
 uint32_t* GetOutputBuffer(){return nullptr;}
 void InitConversionMatrix(double,double){}
 void ApplyColorOptions(uint8_t&,uint8_t&,uint8_t&,double,double){}
};
'''

CONTEXT = r'''
struct PceVdc {
 struct {struct {uint16_t ColumnCount=32;bool CgMode=false;} HvLatch;} _state;
 struct {uint16_t TileAddr=0;uint8_t Palette=0;uint16_t TileData[2]={};} _tiles[128];
 uint16_t _loadBgLastCycle=0,_tileCount=0,_vramOpenBus=0;
 bool _allowVramAccess=false;
 std::array<uint16_t,32768> storage{};uint16_t* _vram=storage.data();Emulator* _emu;
 explicit PceVdc(Emulator* e):_emu(e){}
 void LoadBackgroundTilesWidth4(uint16_t,uint16_t,uint16_t,uint16_t);
 void LoadBatEntry(uint16_t,uint16_t,uint16_t);
 uint16_t ReadVram(uint16_t);
 uint8_t GetTilePixelColor(const uint16_t,const uint16_t,const uint8_t);
};
'''

MAIN = r'''
class ExposedFilter : public PceDefaultVideoFilter {
public:
 using PceDefaultVideoFilter::PceDefaultVideoFilter;
 uint32_t pixel(uint16_t value){return GetPixel(&value,0);}
};
int main(int argc,char** argv) {
 if(argc!=2)return 2;
 try {
  std::ofstream out(argv[1],std::ios::binary);if(!out)return 2;
  Emulator emu;
  for(unsigned i=0;i<512;++i) {
   unsigned r=((i>>3)&7)*255/7,g=((i>>6)&7)*255/7,b=(i&7)*255/7;
   emu.settings.pce.Palette[i]=(r<<16)|(g<<8)|b;
  }
  ExposedFilter filter(&emu);
  for(unsigned i=0;i<512;++i) {
   auto rgb=filter.pixel(static_cast<uint16_t>(i|512));
   out.put(static_cast<char>(rgb>>16));out.put(static_cast<char>(rgb>>8));out.put(static_cast<char>(rgb));
  }
  PceVdc vdc(&emu);vdc.storage[0]=0x7200;
  for(unsigned cg=0;cg<2;++cg)for(unsigned word=0;word<65536;++word) {
   vdc.storage[0x2000]=static_cast<uint16_t>(word);
   vdc.storage[0x2008]=static_cast<uint16_t>(word^65535);
   vdc._state.HvLatch.CgMode=cg!=0;vdc._tileCount=0;vdc._loadBgLastCycle=0;
   vdc.LoadBackgroundTilesWidth4(8,0,31,0);
   if(vdc._tileCount!=1||vdc._allowVramAccess||vdc._tiles[0].TileData[1])return 3;
   for(unsigned x=0;x<8;++x) {
    auto color=vdc.GetTilePixelColor(vdc._tiles[0].TileData[0],vdc._tiles[0].TileData[1],7-x);
    // At the reference boundary a zero low nibble is transparent; the toolkit
    // canonicalizes that palette index to zero before its VCE lookup.
    out.put(static_cast<char>(color?((vdc._tiles[0].Palette<<4)|color):0));
   }
  }
  if(!out)return 2;
  std::cout<<"{\"palette_colors\":512,\"selected_words\":131072,\"pattern_pixels\":1048576}\n";
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}
}
'''


def run(args):
    source, out, probe = args.mesen_source.resolve(), args.out.resolve(), args.probe.resolve()
    compiler_name = shutil.which(str(args.compiler))
    if not compiler_name or not probe.is_file() or out.exists():
        raise ValueError('Require compiler, existing toolkit probe, and a NEW output directory')
    if not out.is_relative_to(ROOT/'.local'):
        raise ValueError('Reference-generated source/binaries must stay private in .local')
    bindings = {str(source/name): digest for name, digest in SOURCES.items()}
    if any(not Path(path).is_file() or sha(Path(path)) != digest for path,digest in bindings.items()):
        raise ValueError('Mesen source bytes differ from the declared immutable pin')
    compiler = Path(compiler_name).resolve()
    bindings.update({str(compiler):sha(compiler),str(probe):sha(probe),str(Path(__file__).resolve()):sha(Path(__file__).resolve()),
                     str(ROOT/'tests/video_modes_oracle_probe.cpp'):sha(ROOT/'tests/video_modes_oracle_probe.cpp')})
    bindings.update({str(ROOT/name):sha(ROOT/name) for name in
                     ('runtime/src/video.cpp','runtime/src/scanline.cpp','runtime/include/pce/video.hpp',
                      'runtime/include/pce/scanline.hpp','runtime/include/pce/runtime.hpp')})
    out.mkdir(parents=True)
    result_path=out/'result.json'
    result_path.write_text('{"result":"incomplete"}\n')
    (out/'stubs').mkdir()
    for name in ('pch.h','PCE/PceConstants.h','Shared/Video/BaseVideoFilter.h','Shared/EmuSettings.h','Shared/Emulator.h'):
        path=out/'stubs'/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(STUBS if name=='pch.h' else '#pragma once\n#include "pch.h"\n')
    shutil.copyfile(source/'PceDefaultVideoFilter.h',out/'PceDefaultVideoFilter.h')
    definitions,spans=[],[]
    for name in FUNCTIONS:
        definition,span=extract((source/'PceVdc.cpp').read_bytes(),name)
        definitions.append(definition);spans.append(span)
    program=out/'reference.cpp'
    program.write_bytes(b'#include "PceDefaultVideoFilter.h"\n'+CONTEXT.encode()+b'\n'.join(definitions)+MAIN.encode())
    generated_bindings={str(path):sha(path) for path in [program,out/'PceDefaultVideoFilter.h',*sorted((out/'stubs').rglob('*.h'))]}
    external=out/'reference.exe'
    with (out/'compile.log').open('wb') as log:
        subprocess.run([str(compiler),'-std=c++20','-O2','-ffp-contract=off','-I',str(out/'stubs'),str(program),'-o',str(external)],
                       check=True,stdout=log,stderr=subprocess.STDOUT,timeout=60)
    metadata=[]
    for name,executable in (('mesen-functions',external),('toolkit',probe)):
        completed=subprocess.run([str(executable),str(out/(name+'.bin'))],check=True,capture_output=True,text=True,timeout=60)
        (out/(name+'.stdout')).write_text(completed.stdout)
        (out/(name+'.stderr')).write_text(completed.stderr)
        parsed=json.loads(completed.stdout)
        if parsed!={'palette_colors':512,'selected_words':131072,'pattern_pixels':1048576}:
            raise ValueError('Probe metadata/finite scope changed')
        metadata.append(parsed)
    expected=(out/'mesen-functions.bin').read_bytes();actual=(out/'toolkit.bin').read_bytes()
    if len(expected)!=PALETTE_BYTES+PATTERN_BYTES or len(actual)!=len(expected):
        raise ValueError('Video observation extent differs from authored finite scope')
    for color,value in ((0,0),(0x38,76),(0x1C0,149),(7,29),(0x1FF,255),
                        (0x1C7,178),(0x3F,105),(0x1F8,225)):
        if expected[color*3:color*3+3]!=bytes([value])*3:
            raise ValueError('External grayscale conversion disagrees with independent corner-color literal')
    if any(expected[i]!=expected[i+1] or expected[i]!=expected[i+2] for i in range(0,PALETTE_BYTES,3)):
        raise ValueError('External grayscale output has unequal channels')
    # An independent literal truth table checks all two-plane reference samples,
    # separate from the reference's selected-word/bit-manipulation methods.
    literal_checks=0
    for cg in range(2):
        for word in range(65536):
            selected=word if not cg else word^65535
            for x in range(8):
                low=bool(selected&(1<<(7-x)));high=bool(selected&(1<<(15-x)))
                color=((0,2),(1,3))[low][high]
                wanted=(112+color) if color else 0
                offset=PALETTE_BYTES+((cg*65536+word)*8+x)
                if expected[offset]!=wanted:raise ValueError('External word decoder disagrees with literal truth table')
                literal_checks+=1
    mismatch=next((i for i,(a,b) in enumerate(zip(actual,expected)) if a!=b),None)
    report=dict(schema=1,result='pass' if mismatch is None else 'failed-comparison',
                mesen_repository=MESEN_REPOSITORY,mesen_commit=MESEN_COMMIT,
                upstream_sources={name:f'{MESEN_REPOSITORY}/blob/{MESEN_COMMIT}/Core/PCE/{name}' for name in SOURCES},
                reference_compile_options=['-std=c++20','-O2','-ffp-contract=off'],
                source_bindings=bindings,extracted_functions=spans,
                generated_bindings=generated_bindings,
                observations=metadata[0],bytes=len(expected),literal_pattern_checks=literal_checks,
                literal_corner_colors=8,grayscale_equal_channel_checks=512,
                oracle_sha256=sha(external),adapter_sha256=sha(program),
                reference_output_sha256=sha(out/'mesen-functions.bin'),toolkit_output_sha256=sha(out/'toolkit.bin'),
                comparison_first_difference=mismatch,
                profile='MesenCE default digital grayscale applied to explicitly supplied standard RGB palette; VM3 selected CG word decoded into low two color bits; transparent zero canonicalized',
                scope='complete unchanged default filter header with authored dependency stubs; four byte-identical extracted VDC definitions with authored state context',
                not_checked=['full Mesen emulator','CPU tiers','VRAM fetch timing','MWR latch edges','CG latch behavior','analog color or colorburst','hardware','retail input','campaign'])
    report['preservation']={path:sha(Path(path))==digest for path,digest in bindings.items()}
    report['preservation'].update({path:sha(Path(path))==digest for path,digest in generated_bindings.items()})
    if not all(report['preservation'].values()):report['result']='failed-preservation'
    result_path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if report['result']!='pass':raise ValueError('External digital-video comparison failed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mesen-source',type=Path,required=True)
    parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--compiler',default='clang++')
    parser.add_argument('--out',type=Path,required=True)
    try:run(parser.parse_args())
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        print(error,file=sys.stderr);raise SystemExit(1)
