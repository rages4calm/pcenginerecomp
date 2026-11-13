"""Authored nested software interrupts and all-byte saved status -> native code."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
f=load('software_fixture',Path(__file__).with_name('fixture.py'))
support=load('native_example_support',ROOT/'examples/native_support.py')
digest,write,process=support.digest,support.write,support.process

def identity():
    from pcerecomp.project import source_identity
    return source_identity(ROOT)
def sources():
    names=['examples/software-interrupts/workflow.py','examples/software-interrupts/fixture.py','examples/software-interrupts/probe.cpp','examples/native_support.py']
    return {name:digest(ROOT/name) for name in names}
def inputs(out):
    value=json.loads((out/'creation.json').read_text(encoding='utf-8'))
    if value['tool']!=identity() or value['sources']!=sources():raise ValueError('Fixture/SDK changed; create a new proof, do not repin')
    if any(digest(out/name)!=h for name,h in value['originals'].items()):raise ValueError('Original authored input changed')
    return value
def create(output):
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False);rom,cases=f.fixture();(out/'card.pce').write_bytes(rom)
    entries=[(0xC200,f.M0,2)]+[(c['pc'],c['mpr'],len(c['plan'][0]['code'])) for c in cases]
    seeds=dict(format='pce-declared-roots-1',schema=1,kind='declared',execution_evidence=False,
        image=dict(sha256=digest(out/'card.pce'),profile='base',header='none',encoding='linear'),
        roots=[dict(pc=pc,mpr=list(mpr),selector=0,rom_offsets=[f.physical(pc+i,mpr) for i in range(size)]) for pc,mpr,size in entries])
    write(out/'seeds.json',seeds)
    value=dict(tool=identity(),sources=sources(),originals={name:digest(out/name) for name in ('card.pce','seeds.json')},profile='base',compiled=False,executed=False)
    write(out/'creation.json',value);return value
def prepare(output):
    from pcerecomp.discovery import discover_roots
    from pcerecomp.prepare import prepare_project,_toml
    out=Path(output).resolve();created=inputs(out)
    graph=discover_roots(out/'seeds.json',out/'card.pce',out/'discovery',rom_ranges=f.code_ranges(),
        rom_data_ranges=f.ROM_RANGES,call_depth_limit=8,alu_facts=True,branch_facts=True,stack_facts=True,wram_facts=True,wram_data_ranges=f.WRAM_RANGES,instruction_limit=12000,context_limit=256,memory_flow=True,block_transfer_limit=256,software_interrupts=True,rom_vector_ranges=f.VECTOR_RANGES)
    expected={(row['pc'],row['mpr'],tuple(f.physical(row['pc']+i,row['mpr']) for i in range(len(row['code'])))) for row in f.plan()}
    actual={(r['pc'],tuple(r['mpr']),tuple(r['rom_offsets'])) for r in graph.declarations.roots}
    if actual!=expected or graph.report['unresolved']:
        raise ValueError('Candidate graph differs from separate literal control/load plan')
    recipe=dict(schema=1,format='pce-consumer-prepare-1',name='authored-software-interrupts',
        module=dict(kind='discovery',path='discovery/discovery.json',partition_layout='shared',partition_size=1024),
        boot=dict(mode='hucard-reset',profile=created['profile'],header='none',encoding='linear'),cartridge=dict(path='card.pce'),
        runtime=dict(tier='native',video='snapshot',audio='off',cd_unknown_status='fault',joypad=2,region='usa',multitap='off'),
        limits=dict(steps=f.MAIN_STEPS,ticks=100000,wall_seconds=10))
    (out/'prepare.toml').write_text(_toml(recipe),encoding='utf-8')
    result=prepare_project(out/'prepare.toml',out/'consumer');graph.revalidate();inputs(out);write(out/'prepared.json',result);return result
def check_capture(path,mode):
    from collections import Counter
    from pcerecomp.capture import load_capture
    value,sha=load_capture(path);matrix=mode.startswith('matrix');reference=mode in ('reference','matrix-reference')
    rows=f.plan()[f.MAIN_STEPS:] if matrix else f.plan()[:f.NEGATIVE_STEPS if mode=='changed-vector' else f.MAIN_STEPS]
    if mode=='changed-status':rows=f.fixture()[1][1]['plan'][:-1]
    count=4 if matrix else 1
    counts=Counter((row['pc'],row['mpr'],tuple(f.physical(row['pc']+i,row['mpr']) for i in range(len(row['code']))),tuple(row['code'])) for row in rows)
    expected={k:(0,h*count) if reference else (h*count,0) for k,h in counts.items()}
    actual={(r['pc'],tuple(r['mpr']),tuple(r['physical']),tuple(r['data'])):(r['native_hits'],r['interpreted_hits']) for r in value['observations']}
    if not value['complete'] or actual!=expected or value['retired_instructions']!=len(rows)*count:raise ValueError('Exact source/hit/tier relation differs: '+mode)
    return dict(sha256=sha,identities=len(actual),retired=len(rows)*count)

def qualify(output,generator=None,cmake_args=()):
    from pcerecomp.project import build,run,verify
    from pcerecomp.discovery import load_discovery
    out=Path(output).resolve();created=inputs(out);graph=load_discovery(out/'discovery',out/'card.pce')
    descriptor=out/'consumer/project.toml';checked=verify(descriptor)
    build(descriptor,out/'consumer-build',generator=generator,cmake_args=list(cmake_args))
    official=run(descriptor,out/'consumer-build',out/'official.json',code_capture=out/'official-capture.json',capture_limit=8192)
    expected=dict(pc=f.END,a=16,x=3,y=4,sp=0,p=12,mpr=list(f.M5),clock_divisor=12,cycles=f.MAIN_CYCLES,ticks=12*f.MAIN_CYCLES,native_steps=f.MAIN_STEPS,interpreter_steps=0,guard_misses=0)
    if not official['qualified'] or any(type(official['result'].get(k)) is not type(v) or official['result'][k]!=v for k,v in expected.items()):raise ValueError('Official cold literal endpoint differs')
    cold=check_capture(out/'official-capture.json','main')
    probe=out/'probe';probe.mkdir(exist_ok=False)
    cases=f.fixture()[1]
    lines=['#pragma once','struct Case { unsigned pc,end,a,x,y,p,cycles,steps; };','static constexpr Case cases[] = {']
    for case in cases:lines.append('{'+','.join(str(v) for v in [case[k] for k in ('pc','end','a','x','y','p','cycles','steps')])+'},')
    lines.append('};')
    constants=dict(main_end=f.END,main_steps=f.MAIN_STEPS,main_cycles=f.MAIN_CYCLES,case_count=len(cases),negative_steps=f.NEGATIVE_STEPS,write_pc=f.WRITE_PC,negative_pc=0xC480)
    lines += ['static constexpr unsigned '+name+'='+str(v)+';' for name,v in constants.items()]
    lines.append('static constexpr unsigned char main_ram[8192] = {'+','.join(map(str,f.main_ram()))+'};')
    lines.append('static constexpr unsigned char negative_ram[8192] = {'+','.join(map(str,f.main_ram(True)))+'};')
    lines.append('static constexpr unsigned char status_bytes[256] = {'+','.join(str(c['status']) for c in cases)+'};')
    (probe/'cases.hpp').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    header_sha=digest(probe/'cases.hpp')
    binary,bound=support.build_probe(ROOT,out/'consumer/module',out/'consumer-build/build',probe,Path(__file__).with_name('probe.cpp'),'software-probe')
    if digest(probe/'cases.hpp')!=header_sha:raise ValueError('Generated probe header changed during compilation')
    bound[str(probe/'cases.hpp')]=header_sha;results={}
    environment=None
    if os.name=='nt':
        environment=dict(os.environ)
        system=Path(os.environ['SystemRoot'])
        environment['PATH']=str(system/'System32')+os.pathsep+str(system)
    for mode in ('main','reference','matrix','matrix-reference','changed-vector','changed-status'):
        capture=probe/(mode+'-capture.json');done=process(probe,mode,[binary,out/'card.pce',mode,capture],env=environment)
        results[mode]=dict(state=json.loads(done.stdout),capture=check_capture(capture,mode))
    if any(digest(p)!=h for p,h in bound.items()):raise ValueError('Bound probe artifacts changed')
    graph.revalidate();inputs(out)
    if verify(descriptor)['tool_identity']!=checked['tool_identity']:raise ValueError('SDK changed during qualification')
    value=dict(passed=True,tool=created['tool'],sources=created['sources'],probe_bindings=bound,
        discovery_sha256=graph.sha256,declared=len(graph.declarations.roots),analysis_states=len(graph.report['nodes']),cold=cold,results=results,probe_without_sdk_path=os.name=='nt',
        scope='Original nested BRK/RTI main and 1024 separately preset status/SP windows. Literal CPU/clocks/full WRAM and exact encoded keys/hits. Changed live WRAM vector or saved status drives an omitted target and source guard refusal. No retail/external clock/hardware claim.')
    write(out/'qualification.json',value);return value
def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('create','prepare','qualify'));parser.add_argument('output',type=Path)
    parser.add_argument('--generator');parser.add_argument('--cmake-arg',action='append',default=[]);args=parser.parse_args(argv)
    try:
        result=create(args.output) if args.command=='create' else prepare(args.output) if args.command=='prepare' else qualify(args.output,args.generator,args.cmake_arg)
        print(json.dumps(result,indent=2));return 0
    except (ValueError,OSError,subprocess.SubprocessError) as error:print(str(error),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
