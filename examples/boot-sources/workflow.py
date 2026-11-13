"""Source-qualified boot declarations -> official native consumer and literal probes."""
import argparse,importlib.util,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
f=load('boot_fixture',Path(__file__).with_name('fixture.py'));support=load('boot_native_support',ROOT/'examples/native_support.py')
digest,write,process=support.digest,support.write,support.process
def identity():
    from pcerecomp.project import source_identity
    return source_identity(ROOT)
def sources():return {str(p.relative_to(ROOT)):digest(p) for p in (Path(__file__),Path(__file__).with_name('fixture.py'),Path(__file__).with_name('probe.cpp'),ROOT/'examples/native_support.py')}
def inputs(out):
    v=json.loads((out/'creation.json').read_text(encoding='utf-8'))
    if v['tool']!=identity() or v['sources']!=sources() or any(digest(out/n)!=h for n,h in v['originals'].items()):raise ValueError('Source/SDK changed; create new proof rather than repin')
    return v
def create(output,variant='cd-ram'):
    from pcerecomp.boot_sources import FORMAT,metadata,source_offset
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False);raw,image,cases=f.fixture(variant);(out/'source.bin').write_bytes(raw)
    image['sha256']=digest(out/'source.bin');source=metadata(image,len(raw));roots={}
    for c in cases:
        for row in c['plan']:
            offsets=[source_offset(row['mpr'][((row['pc']+i)&65535)//8192]*8192+((row['pc']+i)&8191),source) for i in range(len(row['code']))]
            root=dict(pc=row['pc'],mpr=list(row['mpr']),selector=0,source_offsets=offsets);roots[json.dumps(root,sort_keys=True)]=root
    write(out/'roots.json',dict(format=FORMAT,schema=1,kind='declared',execution_evidence=False,image=image,roots=list(roots.values())))
    value=dict(tool=identity(),sources=sources(),variant=variant,originals={n:digest(out/n) for n in ('source.bin','roots.json')},compiled=False,executed=False)
    write(out/'creation.json',value);return value
def prepare(output):
    from pcerecomp.prepare import prepare_project,_toml
    out=Path(output).resolve();created=inputs(out);variant=created['variant'];raw,image,cases=f.fixture(variant);c=cases[0]
    recipe=dict(schema=1,format='pce-consumer-prepare-1',name='authored-boot-'+variant,module=dict(kind='declared',path='roots.json',partition_layout='shared',partition_size=1024),
        runtime=dict(tier='native',video='snapshot',audio='off',cd_unknown_status='fault',joypad=2,region='usa',multitap='off'),limits=dict(steps=c['steps'],ticks=100000,wall_seconds=10))
    if image['kind']=='payload':recipe['payload']=dict(path='source.bin',physical_load=image['physical_load'],pc=c['pc'],mpr=list(c['initial_mpr']))
    else:recipe.update(boot=dict(mode='system-card-reset',profile=image['profile']),bios=dict(path='source.bin'))
    (out/'prepare.toml').write_text(_toml(recipe),encoding='utf-8',newline='\n');v=prepare_project(out/'prepare.toml',out/'consumer');inputs(out);write(out/'prepared.json',v);return v
def check_capture(path,plans):
    from collections import Counter
    from pcerecomp.capture import load_capture
    v,sha=load_capture(path);expected=Counter((row['pc'],tuple(row['mpr']),tuple(row['code'])) for plan in plans for row in plan)
    actual={(row['pc'],tuple(row['mpr']),tuple(row['data'])):row['native_hits']+row['interpreted_hits'] for row in v['observations']}
    if v['dropped_instructions'] or v['unreadable_instructions'] or v['retired_instructions']!=sum(expected.values()) or actual!=dict(expected):raise ValueError('Encoded keys/hits differ from authored plan')
    return dict(sha256=sha,keys=len(actual),retired=v['retired_instructions'])
def qualify(output,generator=None,cmake_args=()):
    from pcerecomp.project import build,run,verify
    out=Path(output).resolve();created=inputs(out);variant=created['variant'];raw,image,cases=f.fixture(variant);c=cases[0];descriptor=out/'consumer/project.toml'
    checked=verify(descriptor);build(descriptor,out/'consumer-build',generator=generator,cmake_args=cmake_args)
    official=run(descriptor,out/'consumer-build',out/'official.json',code_capture=out/'official-capture.json',capture_limit=16384,capture_profile='extended')
    expected=dict(pc=c['end'],a=0x43,x=3,y=4,sp=255,p=4,native_steps=c['steps'],interpreter_steps=0,guard_misses=0,cycles=c['cycles'],ticks=c['ticks'])
    if not official['qualified'] or any(official['result'].get(k)!=v for k,v in expected.items()):raise ValueError('Official literal cold endpoint differs')
    cold=check_capture(out/'official-capture.json',[c['plan']]);probe=out/'probe';probe.mkdir(exist_ok=False)
    lines=['#pragma once','struct Expected { unsigned pc,a,x,y,sp,p; };','struct Case { unsigned bank,pc,end,cycles,ticks,steps,tag; unsigned char initial[8],final[8]; Expected cpu[24]; };','static constexpr Case cases[] = {']
    for c in cases:
        states=','.join('{'+','.join(str(state[k]) for k in ('pc','a','x','y','sp','p'))+'}' for state in f.cpu_states(c))
        lines.append('{'+','.join(str(c[k]) for k in ('bank','pc','end','cycles','ticks','steps','tag'))+',{'+','.join(map(str,c['initial_mpr']))+'},{'+','.join(map(str,c['final_mpr']))+'},{'+states+'}},')
    lines+=['};',f'static constexpr unsigned case_count={len(cases)};',f'static constexpr bool bios={str(image["kind"]=="system-card").lower()}, super_card={str(variant=="system-super").lower()};',f'static constexpr unsigned physical_load={image.get("physical_load",0)},initial_sp={cases[0]["initial_sp"]},initial_divisor={cases[0]["clock_divisor"]};',
        'static constexpr unsigned char expected_ram[8192]={'+','.join(map(str,f.expected_ram(variant,cases[0])))+'};']
    (probe/'cases.hpp').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n');header=digest(probe/'cases.hpp')
    binary,bound=support.build_probe(ROOT,out/'consumer/module',out/'consumer-build/build',probe,Path(__file__).with_name('probe.cpp'),'boot-probe');bound[str(probe/'cases.hpp')]=header
    env=dict(os.environ)
    if os.name=='nt':env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')+os.pathsep+os.environ['SystemRoot']
    results={}
    for mode in ('native','reference','changed-source'):
        path=probe/(mode+'-capture.json');done=process(probe,mode,[binary,out/'source.bin',mode,path],env=env)
        plans=[case['plan'] for case in cases] if mode!='changed-source' else [cases[0]['plan'][:5]]
        results[mode]=dict(state=json.loads(done.stdout),capture=check_capture(path,plans))
    if any(digest(p)!=h for p,h in bound.items()):raise ValueError('Bound probe artifacts changed')
    if verify(descriptor)['tool_identity']!=checked['tool_identity']:raise ValueError('Toolkit changed during qualification')
    inputs(out);v=dict(passed=True,tool=created['tool'],sources=created['sources'],variant=variant,cold=cold,declared=json.loads((out/'consumer/module/module.json').read_text(encoding='utf-8'))['declared_instructions'],results=results,probe_bindings=bound,probe_without_sdk_path=os.name=='nt',scope='Authored explicit boot-source candidates. Cold official path and separately preset source mapping windows, literal CPU/clocks/full WRAM and exact encoded keys/hits. Changed source byte refuses before guest effects. No live CD overlay inference, hardware or whole-title proof.')
    write(out/'qualification.json',v);return v
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('create','prepare','qualify'));p.add_argument('output',type=Path);p.add_argument('--source',choices=f.VARIANTS,default='cd-ram');p.add_argument('--generator');p.add_argument('--cmake-arg',action='append',default=[]);a=p.parse_args(argv)
    try:
        v=create(a.output,a.source) if a.command=='create' else prepare(a.output) if a.command=='prepare' else qualify(a.output,a.generator,a.cmake_arg);print(json.dumps(v,indent=2));return 0
    except (ValueError,OSError) as error:print(str(error),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
