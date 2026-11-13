"""Authored unknown-X discovery, pinned native consumer and all-byte matrix."""
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
TARGETS=(0xE040,0x50E0,0xE050,0x40E0)
CODE_RANGES=((0,7),(0x40,10),(0x50,10),(0xE0,10),(0x10E0,10))
VECTOR_RANGES=((0x100,257),)

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(value,indent=2,allow_nan=False)+'\n')
def identity():
    from pcerecomp.project import source_identity
    return source_identity(ROOT)
def plan():
    rows=[(0xE000,M0,'A9 F8'),(0xE002,M0,'53 02'),(0xE004,M1,'7C 00 E1')]
    for lane,pc in enumerate(TARGETS):
        rows.extend(((pc,M1,f'A9 {16+lane:02X}'),(pc+2,M1,'8D 00 20'),
                     (pc+5,M1,'8E 01 20'),(pc+8,M1,'80 FE')))
    return rows
def card_bytes():
    raw=bytearray([0xEA]*8192)
    for pc,_,code in plan():
        data=bytes.fromhex(code);raw[pc&8191:(pc&8191)+len(data)]=data
    raw[0x100:0x201]=(bytes([0x40,0xE0,0x50,0xE0])*65)[:257]
    raw[0x1FFE:0x2000]=bytes.fromhex('00 E0')
    return bytes(raw)
def inputs(out):
    record=json.loads((out/'creation.json').read_text(encoding='utf-8'))
    if record['tool']!=identity():raise ValueError('SDK changed; create a new fixture, do not repin old proof')
    if any(digest(out/p)!=v for p,v in record['originals'].items()):raise ValueError('Authored inputs changed')
    return record
def create(output):
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'card.pce').write_bytes(card_bytes())
    write(out/'seeds.json',dict(format='pce-declared-roots-1',schema=1,kind='declared',execution_evidence=False,
        image=dict(sha256=digest(out/'card.pce'),profile='base',header='none',encoding='linear'),
        roots=[dict(pc=0xE000,mpr=list(M0),selector=0,rom_offsets=[0,1])]))
    record=dict(tool=identity(),originals={p:digest(out/p) for p in ('card.pce','seeds.json')},compiled=False,executed=False)
    write(out/'creation.json',record);return record
def prepare(output):
    from pcerecomp.discovery import discover_roots
    from pcerecomp.prepare import prepare_project,_toml
    out=Path(output).resolve();inputs(out)
    found=discover_roots(out/'seeds.json',out/'card.pce',out/'discovery',rom_ranges=CODE_RANGES,
        rom_vector_ranges=VECTOR_RANGES,rom_table_limit=1,instruction_limit=64,context_limit=4)
    expected={(pc,mpr,tuple(range(pc&8191,(pc&8191)+len(bytes.fromhex(code))))) for pc,mpr,code in plan()}
    actual={(r['pc'],tuple(r['mpr']),tuple(r['rom_offsets'])) for r in found.declarations.roots}
    if actual!=expected or found.report['unresolved'] or found.report['summary']['resolved_vector_entries']!=256:
        raise ValueError('Discovery differs from independent literal four-lane plan')
    recipe=dict(schema=1,format='pce-consumer-prepare-1',name='authored-rom-tables',
        module=dict(kind='discovery',path='discovery/discovery.json',partition_layout='shared',partition_size=1024),
        boot=dict(mode='hucard-reset',profile='base',header='none',encoding='linear'),cartridge=dict(path='card.pce'),
        runtime=dict(tier='native',video='snapshot',audio='off',cd_unknown_status='fault',joypad=2,region='usa',multitap='off'),
        limits=dict(steps=7,ticks=10000,wall_seconds=10))
    with (out/'prepare.toml').open('x',encoding='utf-8',newline='\n') as stream:stream.write(_toml(recipe))
    result=prepare_project(out/'prepare.toml',out/'consumer');found.revalidate();inputs(out)
    write(out/'prepared.json',result);return result
def process(out,name,command,*,timeout=180):
    argv=list(map(str,command));timed_out=False
    try:
        result=subprocess.run(argv,capture_output=True,timeout=timeout)
        stdout,stderr,code=result.stdout,result.stderr,result.returncode
    except subprocess.TimeoutExpired as error:
        stdout,stderr,code=error.stdout or b'',error.stderr or b'',None
        timed_out=True
    for suffix,data in (('stdout',stdout),('stderr',stderr)):
        with (out/(name+'.'+suffix)).open('xb') as stream:stream.write(data)
    write(out/(name+'-process.json'),dict(argv=argv,exit_code=code,timed_out=timed_out,
        stdout_sha256=digest(out/(name+'.stdout')),stderr_sha256=digest(out/(name+'.stderr'))))
    if timed_out:raise ValueError(name+' timed out; partial output retained')
    if code:raise ValueError(name+' refused: '+stderr.decode(errors='replace'))
    return result
def check_capture(path,mode):
    from pcerecomp.capture import load_capture
    report,sha=load_capture(path);reference=mode=='reference';negative=mode.endswith('change');cold=mode=='cold'
    expected={}
    for i,(pc,mpr,code) in enumerate(plan()[:3] if negative else plan()[:7] if cold else plan()):
        raw=tuple(bytes.fromhex(code));hits=1 if negative or cold else 256 if i<3 else 64
        expected[(pc,mpr,tuple(range(pc&8191,(pc&8191)+len(raw))),raw)]=(0,hits) if reference else (hits,0)
    actual={(r['pc'],tuple(r['mpr']),tuple(r['physical']),tuple(r['data'])):(r['native_hits'],r['interpreted_hits']) for r in report['observations']}
    if not report['complete'] or actual!=expected or report['retired_instructions']!=(3 if negative else 7 if cold else 1792):
        raise ValueError('Complete source identity/hit/tier relation differs: '+mode)
    return dict(sha256=sha,identities=len(actual),retired=report['retired_instructions'])
def qualify(output,generator=None,cmake_args=()):
    from pcerecomp.discovery import load_discovery
    from pcerecomp.project import build,run,verify
    out=Path(output).resolve();created=inputs(out);graph=load_discovery(out/'discovery',out/'card.pce')
    descriptor=out/'consumer/project.toml';checked=verify(descriptor)
    built=build(descriptor,out/'consumer-build',generator=generator,cmake_args=list(cmake_args))
    official=run(descriptor,out/'consumer-build',out/'official.json',code_capture=out/'official-capture.json',capture_limit=32)
    state=official['result'];expected=dict(pc=0xE048,a=16,x=0,y=0,sp=0,p=4,mpr=list(M1),clock_divisor=12,
        cycles=30,ticks=360,native_steps=7,interpreter_steps=0,guard_misses=0)
    if not official['qualified'] or any(type(state.get(k)) is not type(v) or state[k]!=v for k,v in expected.items()):
        raise ValueError('Official cold native literal endpoint differs')
    official_capture=check_capture(out/'official-capture.json','cold')
    build_dir=out/'consumer-build/build';archives=[p for p in build_dir.rglob('*') if p.name in ('libpce-runtime.a','pce-runtime.lib')]
    if len(archives)!=1:raise ValueError('Expected exact official runtime archive')
    options={}
    for line in (build_dir/'CMakeCache.txt').read_text().splitlines():
        if '=' in line and ':' in line.split('=',1)[0]:
            key,value=line.split('=',1);options[key.split(':',1)[0]]=value
    probe=out/'probe';probe.mkdir(exist_ok=False);module=out/'consumer/module';source=Path(__file__).with_name('probe.cpp')
    bound={str(p):digest(p) for p in (archives[0],source,out/'card.pce',out/'seeds.json')}
    cmake_text=f'''cmake_minimum_required(VERSION 3.20)
project(RomTableProbe LANGUAGES CXX)
add_library(pce-runtime STATIC IMPORTED GLOBAL)
set_target_properties(pce-runtime PROPERTIES IMPORTED_LOCATION "{archives[0].as_posix()}"
 INTERFACE_INCLUDE_DIRECTORIES "{(ROOT/'runtime/include').as_posix()}" INTERFACE_COMPILE_FEATURES cxx_std_20)
include("{(ROOT/'cmake/PCEConsumer.cmake').as_posix()}")
pce_add_native_module(native_objects MODULE "{(module/'module.cpp').as_posix()}" MANIFEST "{(module/'module.json').as_posix()}")
add_executable(table-probe "{source.as_posix()}")
target_link_libraries(table-probe PRIVATE pce-runtime ${{native_objects}} ${{CMAKE_DL_LIBS}})
if(WIN32)
 target_link_libraries(table-probe PRIVATE ws2_32)
endif()
'''
    (probe/'CMakeLists.txt').write_text(cmake_text,encoding='utf-8')
    cmake=shutil.which('cmake')
    if not cmake:raise ValueError('CMake required')
    process(probe,'configure',[cmake,'-S',probe,'-B',probe/'build','-G',options['CMAKE_GENERATOR'],
        '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+options['CMAKE_CXX_COMPILER'],
        '-DCMAKE_MAKE_PROGRAM='+options['CMAKE_MAKE_PROGRAM']])
    process(probe,'build',[cmake,'--build',probe/'build','--config','Release','--parallel','2'])
    binary=probe/'build'/('table-probe.exe' if os.name=='nt' else 'table-probe')
    if not binary.is_file():binary=binary.parent/'Release'/binary.name
    results={}
    for mode in ('native','reference','vector-change','source-change'):
        capture=probe/(mode+'-capture.json');done=process(probe,mode,[binary,out/'card.pce',mode,capture])
        results[mode]=dict(state=json.loads(done.stdout),capture=check_capture(capture,mode))
    if any(digest(p)!=v for p,v in bound.items()):raise ValueError('Bound probe inputs changed')
    graph.revalidate();inputs(out)
    if verify(descriptor)['tool_identity']!=checked['tool_identity']:raise ValueError('SDK changed during qualification')
    record=dict(passed=True,tool=created['tool'],discovery_sha256=graph.sha256,declared=19,
        official_cold_native=7,official_capture=official_capture,matrix=results,
        scope='Authored independent X-preset/reset matrix, not one continuous guest route. Cold executes 7 sites; matrix reaches all 19. Literal CPU/clocks/full WRAM and actual dynamic pointer/source negatives. No retail or independent external-reference claim.')
    write(out/'qualification.json',record);return record
def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('create','prepare','qualify'))
    parser.add_argument('output',type=Path);parser.add_argument('--generator');parser.add_argument('--cmake-arg',action='append',default=[])
    args=parser.parse_args(argv)
    try:
        value=create(args.output) if args.command=='create' else prepare(args.output) if args.command=='prepare' else qualify(args.output,args.generator,args.cmake_arg)
        print(json.dumps(value,indent=2));return 0
    except (ValueError,OSError,subprocess.SubprocessError) as error:print(str(error),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
