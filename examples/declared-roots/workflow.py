"""Authored static declarations alongside real observed history; never fake hits."""
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
MPR=[0,248,0,0,0,0,0,0]
PROGRAM=bytes.fromhex('A9 F8 53 02 D4 A2 FF 9A AD 00 20 F0 FB 20 40 E0 80 F6')
ROUTINE=bytes.fromhex('A9 2A 8D 01 20 9C 00 20 60')
ENTRIES=((13,3),(16,2),(64,2),(66,3),(69,3),(72,1))


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as f: f.write(json.dumps(value,indent=2)+'\n')
def card_bytes():
    image=bytearray([0xEA]*8192);image[:len(PROGRAM)]=PROGRAM;image[64:73]=ROUTINE;image[-2:]=b'\x00\xe0';return bytes(image)
def roots(image):
    return dict(format='pce-declared-roots-1',schema=1,kind='declared',execution_evidence=False,
        image=dict(sha256=digest(image),profile='base',header='none',encoding='linear'),
        roots=[dict(pc=0xE000+p,mpr=list(MPR),selector=0,rom_offsets=list(range(p,p+n))) for p,n in ENTRIES])
def check_prefix(value,native=False):
    expected=dict(pc=0xE00B,a=0,x=255,y=0,sp=255,p=6,mpr=MPR,cycles=442,ticks=1407,
        native_steps=100 if native else 0,interpreter_steps=0 if native else 100)
    if any(type(value.get(k)) is not type(v) or value[k]!=v for k,v in expected.items()):
        raise ValueError('Literal authored prefix endpoint differs')
    if native and value['guard_misses']!=0: raise ValueError('Unexpected native guard misses')
def process(out,name,argv,*,timeout=90):
    command=[str(x) for x in argv]
    try:
        result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    except subprocess.TimeoutExpired as error:
        (out/(name+'.stdout')).write_bytes(error.stdout or b'')
        (out/(name+'.stderr')).write_bytes(error.stderr or b'')
        write(out/(name+'-process.json'),dict(argv=command,exit_code=None,timed_out=True,
            stdout_sha256=digest(out/(name+'.stdout')),stderr_sha256=digest(out/(name+'.stderr'))))
        raise ValueError('Process timed out; partial output retained: '+name) from error
    (out/(name+'.stdout')).write_bytes(result.stdout);(out/(name+'.stderr')).write_bytes(result.stderr)
    write(out/(name+'-process.json'),dict(argv=[str(x) for x in argv],exit_code=result.returncode,
        stdout_sha256=digest(out/(name+'.stdout')),stderr_sha256=digest(out/(name+'.stderr'))))
    if result.returncode:
        raise ValueError('Process refused; original output retained: '+name+'; '+result.stderr.decode('utf-8',errors='replace')[:500])
    return result

def capture(out,runner):
    from pcerecomp.capture import load_capture
    from pcerecomp.project import source_identity
    out,runner=Path(out).resolve(),Path(runner).resolve()
    if out.exists() or not runner.is_file(): raise ValueError('Choose new output and built runner')
    before=source_identity(ROOT);out.mkdir(parents=True)
    image=out/'authored-card.pce';image.write_bytes(card_bytes()); raw=out/'observed.json'
    argv=[runner,'--hucard-reset','base',image,100,100000,'hybrid','--audio-output','off',
        '--code-capture',raw,'--capture-limit',64]
    result=process(out,'capture',argv); state=json.loads(result.stdout);check_prefix(state)
    observed,sha=load_capture(raw)
    if not observed['complete'] or len(observed['observations'])!=7 or observed['retired_instructions']!=100:
        raise ValueError('Original observed prefix differs')
    if any(row['pc'] in {0xE000+p for p,n in ENTRIES} for row in observed['observations']):
        raise ValueError('Declared-only root unexpectedly executed in discovery')
    write(out/'roots.json',roots(image))
    if before!=source_identity(ROOT) or image.read_bytes()!=card_bytes(): raise ValueError('Capture inputs changed')
    receipt=dict(schema=1,kind='authored-declared-root-discovery',tool=before,
        runner_sha256=digest(runner),image_sha256=digest(image),observed_sha256=sha,
        helper_sha256=digest(Path(__file__)),
        artifacts={name:digest(out/name) for name in ('authored-card.pce','observed.json','roots.json',
            'capture.stdout','capture.stderr','capture-process.json')},
        actual_work=dict(interpreted=100,native=0),observed_identities=7,declared_roots=6,
        declared_roots_executed=0,scope='Real observed prefix plus separate never-executed declarations')
    write(out/'capture-receipt.json',receipt);return receipt

def prepare(out):
    from pcerecomp.capture import load_capture
    from pcerecomp.history import compose_history
    from pcerecomp.prepare import prepare_project,_toml
    from pcerecomp.project import source_identity
    out=Path(out).resolve();before=json.loads((out/'capture-receipt.json').read_text())
    if source_identity(ROOT)!=before['tool'] or digest(out/'authored-card.pce')!=before['image_sha256']:
        raise ValueError('Capture producer/image changed; prepare a fresh candidate')
    expected_artifacts={'authored-card.pce','observed.json','roots.json','capture.stdout','capture.stderr','capture-process.json'}
    if (set(before['artifacts'])!=expected_artifacts or digest(Path(__file__))!=before['helper_sha256']
            or any(digest(out/name)!=sha for name,sha in before['artifacts'].items())):
        raise ValueError('Original discovery artifacts or helper changed before preparation')
    observed,observed_sha=load_capture(out/'observed.json')
    check_prefix(json.loads((out/'capture.stdout').read_bytes()))
    if (observed_sha!=before['observed_sha256'] or not observed['complete']
            or observed['retired_instructions']!=100 or len(observed['observations'])!=7):
        raise ValueError('Original observed discovery window differs')
    history=compose_history([out/'observed.json'],out/'history',capacity=64)
    spec=dict(schema=1,format='pce-consumer-prepare-1',name='authored-declared-roots',
        module=dict(kind='declared',path='roots.json',history_path='history/history.json',partition_layout='stable'),
        boot=dict(mode='hucard-reset',profile='base',header='none',encoding='linear'),
        cartridge=dict(path='authored-card.pce'),
        runtime=dict(tier='native',video='snapshot',cd_unknown_status='fault',joypad=2,region='usa',multitap='off',audio='off'),
        limits=dict(steps=100,ticks=100000,wall_seconds=10))
    with (out/'prepare.toml').open('x',encoding='utf-8',newline='\n') as f:f.write(_toml(spec))
    receipt=prepare_project(out/'prepare.toml',out/'consumer')
    write(out/'prepare-summary.json',receipt);return receipt

def qualify(out,generator=None,cmake_args=()):
    from pcerecomp.project import build,run,verify
    from pcerecomp.capture import load_capture
    out=Path(out).resolve();descriptor=out/'consumer/project.toml'
    checked=verify(descriptor);built=build(descriptor,out/'consumer-build',generator=generator,cmake_args=list(cmake_args))
    actual=run(descriptor,out/'consumer-build',out/'official-run.json',code_capture=out/'native-prefix.json',capture_limit=64)
    if not actual['qualified']:raise ValueError('Official native prefix did not qualify')
    check_prefix(actual['result'],True)
    capture,_=load_capture(out/'native-prefix.json')
    if len(capture['observations'])!=7 or any(row['pc'] in {0xE000+p for p,n in ENTRIES} for row in capture['observations']):
        raise ValueError('Unexecuted declaration mislabeled as observed prefix')
    receipt=dict(schema=1,kind='authored-declared-root-official-prefix',execution_evidence=True,
        tool=checked['tool_identity'],build_receipt_sha256=digest(out/'consumer-build/build-receipt.json'),
        run_receipt_sha256=digest(out/'official-run.json'),actual_work=actual['work'],
        declared_roots_executed=0,scope='Compiled declarations remain unexecuted in the real native-only prefix')
    write(out/'prefix-qualification.json',receipt);return receipt

def probe(out):
    from pcerecomp.project import verify
    from pcerecomp.capture import load_capture
    out=Path(out).resolve();checked=verify(out/'consumer/project.toml')
    build=out/'consumer-build/build'; archives=[p for p in build.rglob('*') if p.name in ('libpce-runtime.a','pce-runtime.lib')]
    if len(archives)!=1:raise ValueError('Expected one exact official runtime archive')
    cache={}
    for line in (build/'CMakeCache.txt').read_text(encoding='utf-8').splitlines():
        if '=' in line and ':' in line.split('=',1)[0]:
            key,value=line.split('=',1);cache[key.split(':',1)[0]]=value
    root=out/'probe';root.mkdir(exist_ok=False);module=out/'consumer/module';archive=archives[0]
    text=f'''cmake_minimum_required(VERSION 3.20)
project(DeclaredRootProbe LANGUAGES CXX)
add_library(pce-runtime STATIC IMPORTED GLOBAL)
set_target_properties(pce-runtime PROPERTIES IMPORTED_LOCATION "{archive.as_posix()}"
 INTERFACE_INCLUDE_DIRECTORIES "{(ROOT/'runtime/include').as_posix()}" INTERFACE_COMPILE_FEATURES cxx_std_20)
include("{(ROOT/'cmake/PCEConsumer.cmake').as_posix()}")
pce_add_native_module(native_objects MODULE "{(module/'module.cpp').as_posix()}" MANIFEST "{(module/'module.json').as_posix()}")
add_executable(declared-probe "{Path(__file__).with_name('probe.cpp').as_posix()}")
target_link_libraries(declared-probe PRIVATE pce-runtime ${{native_objects}} ${{CMAKE_DL_LIBS}})
if(WIN32)
 target_link_libraries(declared-probe PRIVATE ws2_32)
endif()
'''
    (root/'CMakeLists.txt').write_text(text,encoding='utf-8',newline='\n')
    pins={str(p):digest(p) for p in (archive,Path(__file__).with_name('probe.cpp'),out/'authored-card.pce')}
    cmake=shutil.which('cmake')
    if not cmake:raise ValueError('CMake required')
    process(root,'configure',[cmake,'-S',root,'-B',root/'build','-G',cache['CMAKE_GENERATOR'],
        '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+cache['CMAKE_CXX_COMPILER'],
        '-DCMAKE_MAKE_PROGRAM='+cache['CMAKE_MAKE_PROGRAM']])
    process(root,'build',[cmake,'--build',root/'build','--config','Release','--parallel','2'])
    binary=root/'build'/('declared-probe.exe' if os.name=='nt' else 'declared-probe')
    if not binary.is_file():binary=binary.parent/'Release'/binary.name
    results={}
    for mode in ('normal','guard'):
        result=process(root,mode,[binary,out/'authored-card.pce',mode,root/(mode+'-capture.json')])
        results[mode]=json.loads(result.stdout)
        actual,_=load_capture(root/(mode+'-capture.json'))
        if not actual['complete']:raise ValueError('Probe did not retain complete real retirements')
        if mode=='normal':
            rows={row['pc']:row for row in actual['observations']}
            if len(rows)!=13 or any(rows[0xE000+p]['native_hits']!=1 for p,n in ENTRIES):
                raise ValueError('Later real declared-root execution/hit counts differ')
    if any(digest(Path(p))!=sha for p,sha in pins.items()) or verify(out/'consumer/project.toml')['tool_identity']!=checked['tool_identity']:
        raise ValueError('Probe inputs changed')
    receipt=dict(schema=1,kind='authored-declared-root-native-probe',execution_evidence=True,
        tool=checked['tool_identity'],binary_sha256=digest(binary),bindings=pins,results=results,
        scope='Developer-assisted WRAM flag triggers real previously unexecuted native code; full8192RAM and literal clocks; separate altered-ROM guard negative')
    write(root/'qualification.json',receipt);return receipt

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    for name in ('capture','prepare','qualify','probe'):
        p=sub.add_parser(name);p.add_argument('output',type=Path)
        if name=='capture':p.add_argument('--runner',type=Path,required=True)
        if name=='qualify':p.add_argument('--generator');p.add_argument('--cmake-arg',action='append',default=[])
    args=parser.parse_args()
    if args.command=='capture':result=capture(args.output,args.runner)
    elif args.command=='prepare':result=prepare(args.output)
    elif args.command=='qualify':result=qualify(args.output,args.generator,args.cmake_arg)
    else:result=probe(args.output)
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
