"""Compose independent numeric RAM/BIOS sources, build and verify native calls."""
import argparse,importlib.util,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
f=load('source_set_fixture',Path(__file__).with_name('fixture.py'));support=load('source_set_support',ROOT/'examples/native_support.py')
boot=load('source_set_boot_workflow',ROOT/'examples/boot-sources/workflow.py')
digest,write,process=support.digest,support.write,support.process
def identity():
    from pcerecomp.project import source_identity
    return source_identity(ROOT)
def sources():return {str(p.relative_to(ROOT)):digest(p) for p in (Path(__file__),Path(__file__).with_name('fixture.py'),Path(__file__).with_name('probe.cpp'),ROOT/'examples/native_support.py',ROOT/'examples/boot-sources/fixture.py',ROOT/'examples/boot-sources/workflow.py')}
def inputs(out):
    v=json.loads((out/'creation.json').read_text(encoding='utf-8'))
    if v['tool']!=identity() or v['sources']!=sources() or any(digest(out/n)!=h for n,h in v['originals'].items()):raise ValueError('Source/SDK changed; create new proof rather than repin')
    return v
def images(out):return dict(payload=out/'payload.bin',bios=out/'bios.bin')
def create(output):
    from pcerecomp.boot_sources import FORMAT,metadata,source_offset
    from pcerecomp.source_sets import compose_source_set
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False);payload,bios,cases=f.fixture();(out/'payload.bin').write_bytes(payload);(out/'bios.bin').write_bytes(bios)
    members=[]
    for role in ('payload','bios'):
        image=dict(kind=role,sha256=digest(images(out)[role]))
        if role=='payload':image['physical_load']=0x100000
        source=metadata(image,len(payload if role=='payload' else bios));roots={}
        for c in cases:
            for i,row in enumerate(c['plan']):
                if (13<=i<=16)!=(role=='bios'):continue
                offsets=[source_offset(row['mpr'][((row['pc']+n)&65535)//8192]*8192+((row['pc']+n)&8191),source) for n in range(len(row['code']))]
                root=dict(pc=row['pc'],mpr=list(row['mpr']),selector=0,source_offsets=offsets);roots[json.dumps(root,sort_keys=True)]=root
        path=out/(role+'-roots.json');write(path,dict(format=FORMAT,schema=1,kind='declared',execution_evidence=False,image=image,roots=list(roots.values())));members.append(dict(id=role,asset=role,path=path))
    # A second exact annotation deliberately overlaps one member. The union
    # deduplicates code identities while retaining every member's provenance.
    members.append(dict(id='payload-review',asset='payload',path=out/'payload-roots.json'))
    compose_source_set(members,out/'sources',images(out))
    originals={p.relative_to(out).as_posix():digest(p) for p in out.rglob('*') if p.is_file()}
    v=dict(tool=identity(),sources=sources(),originals=originals,compiled=False,executed=False);write(out/'creation.json',v);return v
def prepare(output):
    from pcerecomp.prepare import prepare_project,_toml
    out=Path(output).resolve();inputs(out);c=f.case()
    recipe=dict(schema=1,format='pce-consumer-prepare-1',name='authored-source-set',module=dict(kind='declared',path='sources/roots.json',partition_layout='shared',partition_size=1024),
        payload=dict(path='payload.bin',physical_load=0x100000,pc=c['pc'],mpr=list(c['initial_mpr'])),bios=dict(path='bios.bin'),
        runtime=dict(tier='native',video='snapshot',audio='off',cd_unknown_status='fault',joypad=2,region='usa',multitap='off'),limits=dict(steps=23,ticks=100000,wall_seconds=10))
    (out/'prepare.toml').write_text(_toml(recipe),encoding='utf-8',newline='\n');v=prepare_project(out/'prepare.toml',out/'consumer');inputs(out);write(out/'prepared.json',v);return v
def qualify(output,generator=None,cmake_args=()):
    from pcerecomp.project import build,run,verify
    out=Path(output).resolve();created=inputs(out);payload,bios,cases=f.fixture();c=cases[0];descriptor=out/'consumer/project.toml'
    checked=verify(descriptor);build(descriptor,out/'consumer-build',generator=generator,cmake_args=cmake_args)
    official=run(descriptor,out/'consumer-build',out/'official.json',code_capture=out/'official-capture.json',capture_limit=16384,capture_profile='extended')
    expected=dict(pc=c['end'],a=0x43,x=3,y=4,sp=255,p=4,native_steps=23,interpreter_steps=0,guard_misses=0,cycles=80,ticks=942)
    if not official['qualified'] or any(official['result'].get(k)!=v for k,v in expected.items()):raise ValueError('Official cold endpoint differs')
    cold=boot.check_capture(out/'official-capture.json',[c['plan']]);probe=out/'probe';probe.mkdir(exist_ok=False)
    lines=['#pragma once','struct Expected { unsigned pc,a,x,y,sp,p; };','struct Case { unsigned pc,end,steps,tag; unsigned char initial[8],final[8]; Expected cpu[24]; };','static constexpr Case cases[] = {']
    for c in cases:
        states=','.join('{'+','.join(str(state[k]) for k in ('pc','a','x','y','sp','p'))+'}' for state in f.cpu_states(c))
        lines.append('{'+','.join(str(c[k]) for k in ('pc','end','steps','tag'))+',{'+','.join(map(str,c['initial_mpr']))+'},{'+','.join(map(str,c['final_mpr']))+'},{'+states+'}},')
    lines+=['};',f'static constexpr unsigned case_count={len(cases)};','static constexpr unsigned char expected_ram[8192]={'+','.join(map(str,f.expected_ram(cases[0])))+'};']
    (probe/'cases.hpp').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n');header=digest(probe/'cases.hpp')
    binary,bound=support.build_probe(ROOT,out/'consumer/module',out/'consumer-build/build',probe,Path(__file__).with_name('probe.cpp'),'source-set-probe');bound[str(probe/'cases.hpp')]=header
    env=dict(os.environ)
    if os.name=='nt':env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')+os.pathsep+os.environ['SystemRoot']
    results={}
    for mode in ('native','reference','changed-payload','changed-bios'):
        path=probe/(mode+'-capture.json');done=process(probe,mode,[binary,out/'payload.bin',out/'bios.bin',mode,path],env=env)
        plans=[case['plan'] for case in cases] if mode in ('native','reference') else [cases[0]['plan'][:5 if mode=='changed-payload' else 13]]
        results[mode]=dict(state=json.loads(done.stdout),capture=boot.check_capture(path,plans))
    from pcerecomp.native_catalog import load_native_catalog
    from pcerecomp.native_gaps import report_native_gaps
    catalog=load_native_catalog(out/'consumer/module/module.json',out/'consumer/declarations/roots.json',source_images=images(out))
    gaps=report_native_gaps(catalog,[probe/'native-capture.json']);write(out/'native-gaps.json',gaps)
    if gaps['summary']['declared_emitted_exercised']!=5888 or gaps['summary']['declared_emitted_unexercised']!=0:
        raise ValueError('Actual native capture disagrees with source-set catalogue')
    if any(digest(p)!=h for p,h in bound.items()):raise ValueError('Bound probe artifacts changed')
    if verify(descriptor)['tool_identity']!=checked['tool_identity']:raise ValueError('Toolkit changed during qualification')
    inputs(out);m=json.loads((out/'consumer/module/module.json').read_text(encoding='utf-8'));v=dict(passed=True,tool=created['tool'],sources=created['sources'],cold=cold,declared=m['declared_instructions'],source=m['declared_roots_source'],catalogue=catalog.provenance,gaps=dict(sha256=digest(out/'native-gaps.json'),summary=gaps['summary']),results=results,probe_bindings=bound,probe_without_sdk_path=os.name=='nt',scope='Authored cold native RAM/BIOS call and 256 separately preset mapping windows. Literal CPU/clocks/full WRAM/CD RAM and exact encoded keys/hits. Changed payload/BIOS refuse before guest effects. Catalogue/gaps keep original declared provenance and verify all entries against the actual native capture. No retail overlay inference, external device clocks or whole-title proof.')
    write(out/'qualification.json',v);return v
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('create','prepare','qualify'));p.add_argument('output',type=Path);p.add_argument('--generator');p.add_argument('--cmake-arg',action='append',default=[]);a=p.parse_args(argv)
    try:
        v=create(a.output) if a.command=='create' else prepare(a.output) if a.command=='prepare' else qualify(a.output,a.generator,a.cmake_arg);print(json.dumps(v,indent=2));return 0
    except (ValueError,OSError) as error:print(str(error),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
