"""Authored mutable WRAM facts -> banked native calls and exhaustive status matrix."""
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
f=load('wram_fixture',Path(__file__).with_name('fixture.py'))
support=load('native_example_support',ROOT/'examples/native_support.py')
digest,write,process=support.digest,support.write,support.process

def identity():
    from pcerecomp.project import source_identity
    return source_identity(ROOT)
def sources():
    names=['examples/wram-values/workflow.py','examples/wram-values/fixture.py','examples/wram-values/probe.cpp','examples/native_support.py']
    return {name:digest(ROOT/name) for name in names}
def inputs(out):
    value=json.loads((out/'creation.json').read_text())
    if value['tool']!=identity() or value['sources']!=sources():raise ValueError('Fixture/SDK changed; create a new proof, do not repin')
    if any(digest(out/name)!=h for name,h in value['originals'].items()):raise ValueError('Original authored input changed')
    return value
def create(output):
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False);rom,cases=f.fixture();(out/'card.pce').write_bytes(rom)
    entries=[(0xE000,f.M0,2)]+[(c['pc'],c['mpr'],len(c['plan'][0][2])) for c in cases]
    seeds=dict(format='pce-declared-roots-1',schema=1,kind='declared',execution_evidence=False,
        image=dict(sha256=digest(out/'card.pce'),profile='base',header='none',encoding='linear'),
        roots=[dict(pc=pc,mpr=list(mpr),selector=0,rom_offsets=[f.physical(pc+i,mpr) for i in range(size)]) for pc,mpr,size in entries])
    write(out/'seeds.json',seeds)
    value=dict(tool=identity(),sources=sources(),originals={name:digest(out/name) for name in ('card.pce','seeds.json')},compiled=False,executed=False)
    write(out/'creation.json',value);return value
def prepare(output):
    from pcerecomp.discovery import discover_roots
    from pcerecomp.prepare import prepare_project,_toml
    out=Path(output).resolve();inputs(out)
    graph=discover_roots(out/'seeds.json',out/'card.pce',out/'discovery',rom_ranges=f.code_ranges(),
        rom_data_ranges=f.ROM_RANGES,call_depth_limit=8,alu_facts=True,branch_facts=True,stack_facts=True,wram_facts=True,wram_data_ranges=f.WRAM_RANGES,instruction_limit=12000,context_limit=16)
    expected={(pc,mpr,tuple(f.physical(pc+i,mpr) for i in range(len(code)))) for pc,mpr,code in f.plan()}
    actual={(r['pc'],tuple(r['mpr']),tuple(r['rom_offsets'])) for r in graph.declarations.roots}
    if actual!=expected or graph.report['unresolved'] or graph.report['summary']['decided_conditionals']!=1:
        raise ValueError('Candidate graph differs from separate literal control/load plan')
    recipe=dict(schema=1,format='pce-consumer-prepare-1',name='authored-wram-values',
        module=dict(kind='discovery',path='discovery/discovery.json',partition_layout='shared',partition_size=1024),
        boot=dict(mode='hucard-reset',profile='base',header='none',encoding='linear'),cartridge=dict(path='card.pce'),
        runtime=dict(tier='native',video='snapshot',audio='off',cd_unknown_status='fault',joypad=2,region='usa',multitap='off'),
        limits=dict(steps=f.MAIN_STEPS,ticks=10000,wall_seconds=10))
    (out/'prepare.toml').write_text(_toml(recipe),encoding='utf-8')
    result=prepare_project(out/'prepare.toml',out/'consumer');graph.revalidate();inputs(out);write(out/'prepared.json',result);return result
def check_capture(path,mode):
    from pcerecomp.capture import load_capture
    value,sha=load_capture(path);matrix=mode.startswith('matrix');reference=mode in ('reference','matrix-reference')
    rows=f.plan()[f.MAIN_STEPS:] if matrix else f.plan()[:f.POINTER_STEPS if mode=='changed-pointer' else f.TRANSFER_STEPS if mode=='changed-transfer' else f.MAIN_STEPS]
    expected={(pc,mpr,tuple(f.physical(pc+i,mpr) for i in range(len(code))),tuple(code)):
              (0,1) if reference else (1,0) for pc,mpr,code in rows}
    actual={(r['pc'],tuple(r['mpr']),tuple(r['physical']),tuple(r['data'])):(r['native_hits'],r['interpreted_hits']) for r in value['observations']}
    if not value['complete'] or actual!=expected or value['retired_instructions']!=len(rows):raise ValueError('Exact source/hit/tier relation differs: '+mode)
    return dict(sha256=sha,identities=len(actual),retired=len(rows))

def qualify(output,generator=None,cmake_args=()):
    from pcerecomp.project import build,run,verify
    from pcerecomp.discovery import load_discovery
    out=Path(output).resolve();created=inputs(out);graph=load_discovery(out/'discovery',out/'card.pce')
    descriptor=out/'consumer/project.toml';checked=verify(descriptor)
    build(descriptor,out/'consumer-build',generator=generator,cmake_args=list(cmake_args))
    official=run(descriptor,out/'consumer-build',out/'official.json',code_capture=out/'official-capture.json',capture_limit=8192)
    expected=dict(pc=f.END,a=66,x=2,y=64,sp=0,p=4,mpr=list(f.M5),clock_divisor=12,cycles=f.MAIN_CYCLES,ticks=12*f.MAIN_CYCLES,native_steps=f.MAIN_STEPS,interpreter_steps=0,guard_misses=0)
    if not official['qualified'] or any(type(official['result'].get(k)) is not type(v) or official['result'][k]!=v for k,v in expected.items()):raise ValueError('Official cold literal endpoint differs')
    cold=check_capture(out/'official-capture.json','main')
    probe=out/'probe';probe.mkdir(exist_ok=False)
    lines=['#pragma once','struct Case { unsigned pc,end,a,x,y,p,cycles,steps,bank; };','static constexpr Case cases[] = {']
    for case in f.fixture()[1]:
        fields=[case[k] for k in ('pc','end','a','x','y','p','cycles','steps')]+[case['mpr'][7]]
        lines.append('{'+','.join(str(int(v)) for v in fields)+'},')
    lines.append('};')
    constants=dict(main_end=f.END,main_steps=f.MAIN_STEPS,main_cycles=f.MAIN_CYCLES,case_count=len(f.fixture()[1]),pointer_steps=f.POINTER_STEPS,transfer_steps=f.TRANSFER_STEPS,jump_pc=f.LABELS['jump'],adc_pc=f.LABELS['memory-add'],map_code=f.LABELS['map-code'])
    lines += ['static constexpr unsigned '+name+'='+str(v)+';' for name,v in constants.items()]
    lines.append('static constexpr unsigned char main_ram[8192] = {'+','.join(map(str,f.main_ram()))+'};')
    lines.append('struct Write {unsigned offset,value;};')
    lines.append('static constexpr Write writes[][3] = {')
    for case in f.fixture()[1]:
        entries=list(case['writes'].items());entries += [(8192,0)]*(3-len(entries));assert len(entries)==3
        lines.append('{'+','.join('{'+str(k)+','+str(v)+'}' for k,v in entries)+'},')
    lines.append('};')
    (probe/'cases.hpp').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    header_sha=digest(probe/'cases.hpp')
    binary,bound=support.build_probe(ROOT,out/'consumer/module',out/'consumer-build/build',probe,Path(__file__).with_name('probe.cpp'),'wram-probe')
    if digest(probe/'cases.hpp')!=header_sha:raise ValueError('Generated probe header changed during compilation')
    bound[str(probe/'cases.hpp')]=header_sha;results={}
    environment=None
    if os.name=='nt':
        environment=dict(os.environ)
        system=Path(os.environ['SystemRoot'])
        environment['PATH']=str(system/'System32')+os.pathsep+str(system)
    for mode in ('main','reference','matrix','matrix-reference','changed-pointer','changed-transfer'):
        capture=probe/(mode+'-capture.json');done=process(probe,mode,[binary,out/'card.pce',mode,capture],env=environment)
        results[mode]=dict(state=json.loads(done.stdout),capture=check_capture(capture,mode))
    if any(digest(p)!=h for p,h in bound.items()):raise ValueError('Bound probe artifacts changed')
    graph.revalidate();inputs(out)
    if verify(descriptor)['tool_identity']!=checked['tool_identity']:raise ValueError('SDK changed during qualification')
    value=dict(passed=True,tool=created['tool'],sources=created['sources'],probe_bindings=bound,
        discovery_sha256=graph.sha256,declared=len(f.plan()),cold=cold,results=results,probe_without_sdk_path=os.name=='nt',
        scope='Original banked mutable-data/pointer route and separate 354-reset addressing/RMW/test/T-ALU matrix. Literal CPU/clocks/full WRAM and exact encoded keys/hits. Changed live RAM data/pointers drive runtime mapping/jump guard refusals. No retail/external clock/hardware claim.')
    write(out/'qualification.json',value);return value
def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('create','prepare','qualify'));parser.add_argument('output',type=Path)
    parser.add_argument('--generator');parser.add_argument('--cmake-arg',action='append',default=[]);args=parser.parse_args(argv)
    try:
        result=create(args.output) if args.command=='create' else prepare(args.output) if args.command=='prepare' else qualify(args.output,args.generator,args.cmake_arg)
        print(json.dumps(result,indent=2));return 0
    except (ValueError,OSError,subprocess.SubprocessError) as error:print(str(error),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
