"""Authored ROM-vector discovery -> official native consumer -> literal execution proof."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
M0=(0,)*8
M1=(0,248,0,0,0,0,0,0)
CODE_RANGES=((0x100,9),(0x120,8),(0x140,5))
VECTOR_RANGES=((0x1FF,2),(0x300,2))
PLAN=((0xE100,M0,'A9 F8'),(0xE102,M0,'53 02'),(0xE104,M1,'A2 02'),
      (0xE106,M1,'7C FD E1'),(0xE120,M1,'A9 2A'),(0xE122,M1,'8D 00 20'),
      (0xE125,M1,'6C 00 E3'),(0xE140,M1,'8E 01 20'),(0xE143,M1,'80 FE'))


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(value,indent=2,allow_nan=False)+'\n')


def card_bytes():
    raw=bytearray([0xEA]*8192)
    for pc,_,data in PLAN:
        data=bytes.fromhex(data);raw[pc&8191:(pc&8191)+len(data)]=data
    raw[0x1FF:0x201]=bytes.fromhex('20 E1')
    raw[0x300:0x302]=bytes.fromhex('40 E1')
    raw[0x1FFE:0x2000]=bytes.fromhex('00 E1')
    return bytes(raw)


def entry(pc,mpr,data):
    return dict(pc=pc,mpr=list(mpr),selector=0,rom_offsets=list(range(pc&8191,(pc&8191)+len(bytes.fromhex(data)))))


def identity():
    from pcerecomp.project import source_identity
    return source_identity(ROOT)


def inputs(out):
    creation=json.loads((out/'creation.json').read_text(encoding='utf-8'))
    if creation['tool']!=identity():raise ValueError('SDK changed; create a new fixture, do not repin old proof')
    for name,expected in creation['originals'].items():
        if digest(out/name)!=expected:raise ValueError('Original input changed: '+name)
    return creation


def create(output):
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'card.pce').write_bytes(card_bytes())
    write(out/'seeds.json',dict(format='pce-declared-roots-1',schema=1,kind='declared',execution_evidence=False,
        image=dict(sha256=digest(out/'card.pce'),profile='base',header='none',encoding='linear'),
        roots=[entry(*PLAN[0])]))
    receipt=dict(tool=identity(),originals={name:digest(out/name) for name in ('card.pce','seeds.json')},
                 compiled=False,executed=False)
    write(out/'creation.json',receipt);return receipt


def prepare(output):
    from pcerecomp.discovery import discover_roots
    from pcerecomp.prepare import prepare_project,_toml
    out=Path(output).resolve();inputs(out)
    found=discover_roots(out/'seeds.json',out/'card.pce',out/'discovery',rom_ranges=CODE_RANGES,
                         rom_vector_ranges=VECTOR_RANGES,instruction_limit=32,context_limit=4)
    key=lambda v:(v['pc'],tuple(v['mpr']),v['selector'],tuple(v['rom_offsets']))
    if {key(v) for v in found.declarations.roots}!={key(entry(*v)) for v in PLAN}:
        raise ValueError('Candidate entries differ from independent literal plan')
    if found.report['summary']['resolved_vectors']!=2 or found.report['unresolved']:
        raise ValueError('Unexpected vector derivation frontier')
    recipe=dict(schema=1,format='pce-consumer-prepare-1',name='authored-rom-vectors',
        module=dict(kind='declared',path='discovery/roots.json',partition_layout='stable'),
        boot=dict(mode='hucard-reset',profile='base',header='none',encoding='linear'),cartridge=dict(path='card.pce'),
        runtime=dict(tier='native',video='snapshot',audio='off',cd_unknown_status='fault',joypad=2,region='usa',multitap='off'),
        limits=dict(steps=9,ticks=10000,wall_seconds=10))
    with (out/'prepare.toml').open('x',encoding='utf-8',newline='\n') as stream:stream.write(_toml(recipe))
    result=prepare_project(out/'prepare.toml',out/'consumer');found.revalidate();inputs(out)
    write(out/'prepared.json',result);return result


def process(out,name,command):
    result=subprocess.run([str(v) for v in command],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,timeout=180)
    for suffix,data in (('stdout',result.stdout),('stderr',result.stderr)):
        with (out/(name+'.'+suffix)).open('xb') as stream:stream.write(data)
    write(out/(name+'-process.json'),dict(argv=list(map(str,command)),exit_code=result.returncode,
        stdout_sha256=digest(out/(name+'.stdout')),stderr_sha256=digest(out/(name+'.stderr'))))
    if result.returncode:raise ValueError('Process refused; outputs retained: '+name)
    return result


def check_capture(path,mode):
    from pcerecomp.capture import load_capture
    report,sha=load_capture(path)
    negative=mode in ('vector-change','source-change');reference=mode=='reference'
    expected={}
    for pc,mpr,data in PLAN[:4] if negative else PLAN:
        raw=tuple(bytes.fromhex(data))
        expected[(pc,mpr,tuple(range(pc&8191,(pc&8191)+len(raw))),raw)]=(0,1) if reference else (1,0)
    actual={(v['pc'],tuple(v['mpr']),tuple(v['physical']),tuple(v['data'])):
            (v['native_hits'],v['interpreted_hits']) for v in report['observations']}
    if not report['complete'] or actual!=expected or report['retired_instructions']!=(4 if negative else 9):
        raise ValueError('Complete encoded capture identity/hit/tier plan differs')
    return dict(sha256=sha,identities=len(actual),retired=report['retired_instructions'])


def qualify(output,generator=None,cmake_args=()):
    from pcerecomp.discovery import load_discovery
    from pcerecomp.project import build,run,verify
    out=Path(output).resolve();creation=inputs(out);found=load_discovery(out/'discovery',out/'card.pce')
    descriptor=out/'consumer/project.toml';checked=verify(descriptor)
    built=build(descriptor,out/'consumer-build',generator=generator,cmake_args=list(cmake_args))
    official=run(descriptor,out/'consumer-build',out/'official.json',code_capture=out/'official-capture.json',capture_limit=32)
    state=official['result']
    expected=dict(pc=0xE143,a=42,x=2,y=0,sp=0,p=4,mpr=list(M1),clock_divisor=12,
                  cycles=39,ticks=468,native_steps=9,interpreter_steps=0,guard_misses=0)
    if not official['qualified'] or any(type(state.get(k)) is not type(v) or state[k]!=v for k,v in expected.items()):
        raise ValueError('Official native consumer literal endpoint differs')
    capture=check_capture(out/'official-capture.json','native')
    build_dir=out/'consumer-build/build'
    archives=[p for p in build_dir.rglob('*') if p.name in ('libpce-runtime.a','pce-runtime.lib')]
    if len(archives)!=1:raise ValueError('Expected exact official runtime archive')
    archive=archives[0];options={}
    for line in (build_dir/'CMakeCache.txt').read_text(encoding='utf-8').splitlines():
        if '=' in line and ':' in line.split('=',1)[0]:
            key,value=line.split('=',1);options[key.split(':',1)[0]]=value
    probe=out/'probe';probe.mkdir(exist_ok=False);module=out/'consumer/module';cmake=shutil.which('cmake')
    if not cmake:raise ValueError('CMake required')
    source=Path(__file__).with_name('probe.cpp')
    bound={str(p):digest(p) for p in (archive,source,out/'card.pce',out/'seeds.json')}
    cmake_text=f'''cmake_minimum_required(VERSION 3.20)
project(RomVectorProbe LANGUAGES CXX)
add_library(pce-runtime STATIC IMPORTED GLOBAL)
set_target_properties(pce-runtime PROPERTIES IMPORTED_LOCATION "{archive.as_posix()}"
 INTERFACE_INCLUDE_DIRECTORIES "{(ROOT/'runtime/include').as_posix()}" INTERFACE_COMPILE_FEATURES cxx_std_20)
include("{(ROOT/'cmake/PCEConsumer.cmake').as_posix()}")
pce_add_native_module(native_objects MODULE "{(module/'module.cpp').as_posix()}" MANIFEST "{(module/'module.json').as_posix()}")
add_executable(vector-probe "{source.as_posix()}")
target_link_libraries(vector-probe PRIVATE pce-runtime ${{native_objects}} ${{CMAKE_DL_LIBS}})
if(WIN32)
 target_link_libraries(vector-probe PRIVATE ws2_32)
endif()
'''
    with (probe/'CMakeLists.txt').open('x',encoding='utf-8',newline='\n') as stream:stream.write(cmake_text)
    process(probe,'configure',[cmake,'-S',probe,'-B',probe/'build','-G',options['CMAKE_GENERATOR'],
        '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+options['CMAKE_CXX_COMPILER'],
        '-DCMAKE_MAKE_PROGRAM='+options['CMAKE_MAKE_PROGRAM']])
    process(probe,'build',[cmake,'--build',probe/'build','--config','Release','--parallel','2'])
    binary=probe/'build'/('vector-probe.exe' if os.name=='nt' else 'vector-probe')
    if not binary.is_file():binary=binary.parent/'Release'/binary.name
    results={}
    for mode in ('native','reference','vector-change','source-change'):
        output=probe/(mode+'-capture.json')
        result=process(probe,mode,[binary,out/'card.pce',mode,output])
        results[mode]=dict(state=json.loads(result.stdout),capture=check_capture(output,mode))
    if any(digest(p)!=v for p,v in bound.items()):raise ValueError('Bound probe inputs changed')
    found.revalidate();inputs(out)
    if verify(descriptor)['tool_identity']!=checked['tool_identity']:raise ValueError('SDK changed during execution')
    receipt=dict(passed=True,tool=creation['tool'],discovery_sha256=found.sha256,
        official_binary_sha256=built['binary_sha256'],probe_binary_sha256=digest(binary),
        official_capture=capture,official_run_sha256=digest(out/'official.json'),
        build_receipt_sha256=digest(out/'consumer-build/build-receipt.json'),probe_bindings=bound,results=results,
        scope='9 actual native and 9 reference retirements, independent literal clocks/full8192 WRAM. Two distinct 4-native negatives: dynamic changed vector target and target source guard. Not hardware/game evidence.')
    write(out/'qualified.json',receipt);return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    for name in ('create','prepare','qualify'):
        command=commands.add_parser(name);command.add_argument('output',type=Path)
        if name=='qualify':
            command.add_argument('--generator');command.add_argument('--cmake-arg',action='append',default=[])
    args=parser.parse_args()
    result=create(args.output) if args.command=='create' else prepare(args.output) if args.command=='prepare' else qualify(args.output,args.generator,args.cmake_arg)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
