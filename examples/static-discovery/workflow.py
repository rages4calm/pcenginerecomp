"""Authored bounded ROM discovery; static candidates never acquire invented hits."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
M0 = (0,0,0,0,0,0,0,0)
M1 = (0,248,0,0,0,0,0,0)
M2 = (0,248,0,0,0,0,0,1)
ROM_RANGES = ((0x100,8),(0x2108,14),(0x2140,9))
# Independent literal instruction boundaries, MPR views and decoded-ROM offsets.
PLAN = (
    (0xE100,M0,0x100,'A9 F8'),(0xE102,M0,0x102,'53 02'),
    (0xE104,M1,0x104,'A9 01'),(0xE106,M1,0x106,'53 80'),
    (0xE108,M2,0x2108,'D4'),(0xE109,M2,0x2109,'A2 FF'),(0xE10B,M2,0x210B,'9A'),
    (0xE10C,M2,0x210C,'AD 00 20'),(0xE10F,M2,0x210F,'F0 FB'),
    (0xE111,M2,0x2111,'20 40 E1'),(0xE114,M2,0x2114,'80 F6'),
    (0xE140,M2,0x2140,'A9 2A'),(0xE142,M2,0x2142,'8D 01 20'),
    (0xE145,M2,0x2145,'9C 00 20'),(0xE148,M2,0x2148,'60'))
LATE_PCS = frozenset((0xE111,0xE114,0xE140,0xE142,0xE145,0xE148))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(value,indent=2,allow_nan=False)+'\n')


def card_bytes():
    image = bytearray([0xEA]*16384)
    image[0x100:0x108] = bytes.fromhex('A9 F8 53 02 A9 01 53 80')
    image[0x2108:0x2116] = bytes.fromhex('D4 A2 FF 9A AD 00 20 F0 FB 20 40 E1 80 F6')
    image[0x2140:0x2149] = bytes.fromhex('A9 2A 8D 01 20 9C 00 20 60')
    image[0x2170:0x2173] = bytes.fromhex('6C 02 20')
    image[0x2180:0x2186] = bytes.fromhex('AD 00 20 53 80 EA')
    image[0x2190:0x2192] = bytes.fromhex('0B EA')
    image[0x2198:0x219C] = bytes.fromhex('20 A0 E1 EA')
    image[0x1FFE:0x2000] = bytes.fromhex('00 E1')
    return bytes(image)


def root_entry(pc,mpr,offset,length):
    return dict(pc=pc,mpr=list(mpr),selector=0,rom_offsets=list(range(offset,offset+length)))


def roots_document(image,entries=None):
    if entries is None:
        entries = [root_entry(0xE100,M0,0x100,2),root_entry(0xE114,M2,0x2114,2)]
    return dict(format='pce-declared-roots-1',schema=1,kind='declared',execution_evidence=False,
        image=dict(sha256=digest(image),profile='base',header='none',encoding='linear'),roots=entries)


def root_key(value):
    return value['pc'],tuple(value['mpr']),value['selector'],tuple(value['rom_offsets'])


def expected_roots():
    return [root_entry(pc,mpr,offset,len(bytes.fromhex(encoded))) for pc,mpr,offset,encoded in PLAN]


def _sdk(out):
    from pcerecomp.project import source_identity
    identity = source_identity(ROOT)
    if json.loads((out/'creation.json').read_text())['reader_sdk'] != identity:
        raise ValueError('Reader SDK changed; create a fresh fixture instead of repinning evidence')
    return identity


def _inputs(out):
    from pcerecomp.history import load_history
    paths = [out/'seed-roots.json',out/'authored-card.pce',out/'creation.json']
    if (out/'observed-history').exists():
        history = load_history(out/'observed-history')
        paths += [item['path'] for item in history.artifact_bindings.values()]
        paths += [out/'interpreted-prefix.json',out/'capture-summary.json']
    return {str(path):digest(path) for path in paths}


def _unchanged(bindings):
    if any(digest(path)!=value for path,value in bindings.items()):
        raise ValueError('Original seed, image or observed-history input changed')


def create(output):
    from pcerecomp.project import source_identity
    out = Path(output).resolve()
    if out.exists():raise ValueError('Choose a new fixture output directory')
    out.mkdir(parents=True)
    image = out/'authored-card.pce'; image.write_bytes(card_bytes())
    write(out/'seed-roots.json',roots_document(image))
    receipt = dict(schema=1,kind='authored-static-discovery-inputs',reader_sdk=source_identity(ROOT),
        image_sha256=digest(image),seed_sha256=digest(out/'seed-roots.json'),seed_roots=2,
        compiled=False,executed=False,execution_evidence=False)
    write(out/'creation.json',receipt)
    return receipt


def process(out,name,command,*,timeout=120):
    done = subprocess.run([str(item) for item in command],stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    for suffix,data in (('stdout',done.stdout),('stderr',done.stderr)):
        with (out/(name+'.'+suffix)).open('xb') as stream:stream.write(data)
    write(out/(name+'-process.json'),dict(argv=[str(item) for item in command],exit_code=done.returncode,
        stdout_sha256=digest(out/(name+'.stdout')),stderr_sha256=digest(out/(name+'.stderr'))))
    if done.returncode:raise ValueError('Process refused; original output retained: '+name)
    return done


def check_prefix(state,*,native):
    expected = dict(pc=0xE10F,a=0,x=255,y=0,sp=255,p=6,mpr=list(M2),clock_divisor=3,
        cycles=440,ticks=1464,native_steps=100 if native else 0,interpreter_steps=0 if native else 100)
    if any(type(state.get(key)) is not type(value) or state[key]!=value for key,value in expected.items()):
        raise ValueError('Independent literal prefix state/clocks differ')
    if native and state['guard_misses']!=0:raise ValueError('Unexpected native guard miss')


def check_capture(path,mode):
    from pcerecomp.capture import load_capture
    capture,sha = load_capture(Path(path))
    if not capture['complete']:raise ValueError('Fixture capture is lossy')
    prefix = mode in ('prefix-native','prefix-reference')
    reference = mode in ('reference','prefix-reference')
    guard = mode=='guard'
    expected = {}
    for pc,mpr,offset,encoded in PLAN:
        if prefix and pc in LATE_PCS:continue
        if guard and pc in LATE_PCS-{0xE111}:continue
        raw = tuple(bytes.fromhex(encoded)); hits = 1
        if pc==0xE10C:hits=47 if prefix else 48 if guard else 49
        elif pc==0xE10F:hits=46 if prefix else 48
        expected[(pc,mpr,tuple(range(offset,offset+len(raw))),raw)] = (0,hits) if reference else (hits,0)
    actual = {(row['pc'],tuple(row['mpr']),tuple(row['physical']),tuple(row['data'])):
              (row['native_hits'],row['interpreted_hits']) for row in capture['observations']}
    if actual!=expected:raise ValueError('Full per-key source mapping or actual tier hits differ')
    retired = 100 if prefix else 104 if guard else 110
    if capture['retired_instructions']!=retired:raise ValueError('Capture retirement total differs')
    return dict(sha256=sha,identities=len(actual),retired_instructions=retired,
                native=0 if reference else retired,interpreted=retired if reference else 0)


def capture(output,runner):
    from pcerecomp.history import compose_history
    out,runner = Path(output).resolve(),Path(runner).resolve(); identity = _sdk(out); pins = _inputs(out)
    path = out/'interpreted-prefix.json'
    done = process(out,'capture',[runner,'--hucard-reset','base',out/'authored-card.pce',100,100000,'hybrid',
        '--audio-output','off','--code-capture',path,'--capture-limit',64])
    check_prefix(json.loads(done.stdout),native=False)
    original = check_capture(path,'prefix-reference')
    history = compose_history([path],out/'observed-history',capacity=64)
    _unchanged(pins)
    receipt = dict(schema=1,kind='authored-static-reference-prefix',reader_sdk=identity,
        runner_sha256=digest(runner),capture=original,history_sha256=history.index_sha256,
        actual_work=dict(native=0,interpreted=100),
        scope='Actual interpreted prefix; optional history remains separate from static discovery')
    write(out/'capture-summary.json',receipt)
    return receipt


def discover(output):
    from pcerecomp.discovery import discover_roots,load_discovery
    out = Path(output).resolve(); identity = _sdk(out); pins = _inputs(out)
    admitted = discover_roots(out/'seed-roots.json',out/'authored-card.pce',out/'discovery',
        rom_ranges=ROM_RANGES,instruction_limit=128,context_limit=16)
    expected = {root_key(row) for row in expected_roots()}
    if {root_key(row) for row in admitted.declarations.roots} != expected:
        raise ValueError('Static candidates differ from independent literal instruction/MPR/ROM plan')
    report = admitted.report
    if (report['execution_evidence'] is not False or report['routine_closure'] is not False
            or report['static_reachability']!='candidates_only' or report['summary']['limit_reached']):
        raise ValueError('Discovery evidence/limit scope differs')
    if not {'dynamic_return_site','dynamic_return'} <= {row['reason'] for row in report['unresolved']}:
        raise ValueError('Call/return uncertainty was not retained')
    admitted.revalidate();load_discovery(out/'discovery',out/'authored-card.pce').revalidate();_unchanged(pins)
    receipt = dict(schema=1,kind='authored-bounded-static-discovery',reader_sdk=identity,
        discovery_sha256=admitted.sha256,expanded_roots_sha256=digest(admitted.roots_path),
        seed_roots=2,expanded_identities=15,mpr_contexts=3,compiled=False,executed=False,
        execution_evidence=False,original_inputs=pins,
        scope='Bounded static candidates, not complete control flow or newly observed work')
    write(out/'discovery-summary.json',receipt)
    return receipt


def prepare(output,*,with_history=False):
    from pcerecomp.discovery import load_discovery
    from pcerecomp.prepare import prepare_project,_toml
    out = Path(output).resolve();_sdk(out);pins = _inputs(out)
    admitted = load_discovery(out/'discovery',out/'authored-card.pce')
    module = dict(kind='declared',path='discovery/roots.json',partition_layout='stable')
    if with_history:module['history_path']='observed-history/history.json'
    spec = dict(schema=1,format='pce-consumer-prepare-1',name='authored-static-discovery',module=module,
        boot=dict(mode='hucard-reset',profile='base',header='none',encoding='linear'),
        cartridge=dict(path='authored-card.pce'),
        runtime=dict(tier='native',video='snapshot',audio='off',cd_unknown_status='fault',joypad=2,region='usa',multitap='off'),
        limits=dict(steps=100,ticks=100000,wall_seconds=10))
    with (out/'prepare.toml').open('x',encoding='utf-8',newline='\n') as stream:stream.write(_toml(spec))
    receipt = prepare_project(out/'prepare.toml',out/'consumer')
    admitted.revalidate();_unchanged(pins)
    write(out/'prepare-summary.json',receipt)
    return receipt


def qualify(output,generator=None,cmake_args=()):
    from pcerecomp.discovery import load_discovery
    from pcerecomp.project import build,run,verify
    out = Path(output).resolve();_sdk(out);pins = _inputs(out)
    discovery = load_discovery(out/'discovery',out/'authored-card.pce')
    descriptor = out/'consumer/project.toml'; checked = verify(descriptor)
    built = build(descriptor,out/'consumer-build',generator=generator,cmake_args=list(cmake_args))
    actual = run(descriptor,out/'consumer-build',out/'official-prefix.json',
        code_capture=out/'native-prefix.json',capture_limit=64)
    if not actual['qualified']:raise ValueError('Official native prefix refused')
    check_prefix(actual['result'],native=True);recorded = check_capture(out/'native-prefix.json','prefix-native')
    discovery.revalidate();_unchanged(pins)
    receipt = dict(schema=1,kind='authored-static-official-prefix',tool=checked['tool_identity'],
        discovery_sha256=discovery.sha256,build_receipt_sha256=digest(out/'consumer-build/build-receipt.json'),
        run_receipt_sha256=digest(out/'official-prefix.json'),binary_sha256=built['binary_sha256'],
        actual_work=actual['work'],capture=recorded,unexecuted_expanded_entries=6,
        scope='100 actual native retirements; six additional static candidates remain unexecuted')
    write(out/'prefix-qualified.json',receipt)
    return receipt


def probe(output):
    from pcerecomp.discovery import load_discovery
    from pcerecomp.project import verify
    out = Path(output).resolve();_sdk(out);pins = _inputs(out)
    discovery = load_discovery(out/'discovery',out/'authored-card.pce')
    checked = verify(out/'consumer/project.toml'); build = out/'consumer-build/build'
    archives = [path for path in build.rglob('*') if path.name in ('libpce-runtime.a','pce-runtime.lib')]
    if len(archives)!=1:raise ValueError('Expected one exact official runtime archive')
    options = {}
    for line in (build/'CMakeCache.txt').read_text(encoding='utf-8').splitlines():
        if '=' in line and ':' in line.split('=',1)[0]:
            key,value=line.split('=',1);options[key.split(':',1)[0]]=value
    target = out/'probe';target.mkdir(exist_ok=False);module=out/'consumer/module';archive=archives[0]
    cmake = shutil.which('cmake')
    if not cmake:raise ValueError('CMake required')
    text=f'''cmake_minimum_required(VERSION 3.20)
project(StaticDiscoveryProbe LANGUAGES CXX)
add_library(pce-runtime STATIC IMPORTED GLOBAL)
set_target_properties(pce-runtime PROPERTIES IMPORTED_LOCATION "{archive.as_posix()}"
 INTERFACE_INCLUDE_DIRECTORIES "{(ROOT/'runtime/include').as_posix()}" INTERFACE_COMPILE_FEATURES cxx_std_20)
include("{(ROOT/'cmake/PCEConsumer.cmake').as_posix()}")
pce_add_native_module(native_objects MODULE "{(module/'module.cpp').as_posix()}" MANIFEST "{(module/'module.json').as_posix()}")
add_executable(static-probe "{Path(__file__).with_name('probe.cpp').as_posix()}")
target_link_libraries(static-probe PRIVATE pce-runtime ${{native_objects}} ${{CMAKE_DL_LIBS}})
if(WIN32)
 target_link_libraries(static-probe PRIVATE ws2_32)
endif()
'''
    with (target/'CMakeLists.txt').open('x',encoding='utf-8',newline='\n') as stream:stream.write(text)
    bound = {str(path):digest(path) for path in (archive,Path(__file__).with_name('probe.cpp'),out/'authored-card.pce')}
    process(target,'configure',[cmake,'-S',target,'-B',target/'build','-G',options['CMAKE_GENERATOR'],
        '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+options['CMAKE_CXX_COMPILER'],
        '-DCMAKE_MAKE_PROGRAM='+options['CMAKE_MAKE_PROGRAM']])
    process(target,'build',[cmake,'--build',target/'build','--config','Release','--parallel','2'])
    binary=target/'build'/('static-probe.exe' if os.name=='nt' else 'static-probe')
    if not binary.is_file():binary=binary.parent/'Release'/binary.name
    results = {}
    for mode in ('native','reference','guard'):
        capture_path=target/(mode+'-capture.json');ram_path=target/(mode+'-ram.bin')
        result=process(target,mode,[binary,out/'authored-card.pce',mode,capture_path,ram_path])
        results[mode]=dict(state=json.loads(result.stdout),capture=check_capture(capture_path,mode),
                           ram_sha256=digest(ram_path),ram_bytes=ram_path.stat().st_size)
        expected = bytearray(8192)
        expected[0]=1 if mode=='guard' else 0
        if mode!='guard':expected[1]=42
        expected[0x1FE]=0x13;expected[0x1FF]=0xE1
        if ram_path.read_bytes()!=expected:raise ValueError('Independent full8192-byte WRAM expectation differs')
    discovery.revalidate();_unchanged(pins);_unchanged(bound)
    if verify(out/'consumer/project.toml')['tool_identity']!=checked['tool_identity']:
        raise ValueError('SDK changed during probe')
    receipt=dict(schema=1,kind='authored-static-native-reference-probe',tool=checked['tool_identity'],
        discovery_sha256=discovery.sha256,binary_sha256=digest(binary),bindings=bound,results=results,
        scope='Actual110 native/reference retirements, fullWRAM and literal clocks; separate104-native changed-source guard refusal. Host flag write is developer assistance, not guest work.')
    write(target/'qualified.json',receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    for name in ('create','capture','discover','prepare','qualify','probe'):
        command=commands.add_parser(name);command.add_argument('output',type=Path)
        if name=='capture':command.add_argument('--runner',type=Path,required=True)
        if name=='prepare':command.add_argument('--with-history',action='store_true')
        if name=='qualify':command.add_argument('--generator');command.add_argument('--cmake-arg',action='append',default=[])
    args=parser.parse_args()
    if args.command=='create':result=create(args.output)
    elif args.command=='capture':result=capture(args.output,args.runner)
    elif args.command=='discover':result=discover(args.output)
    elif args.command=='prepare':result=prepare(args.output,with_history=args.with_history)
    elif args.command=='qualify':result=qualify(args.output,args.generator,args.cmake_arg)
    else:result=probe(args.output)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
