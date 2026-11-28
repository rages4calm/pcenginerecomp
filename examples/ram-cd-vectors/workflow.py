"""Qualify authenticated RAM/CD pointer words and dynamic native indirect jumps."""
import argparse,hashlib,importlib.util,json,os,sys,tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
w=load('vector_loader_workflow',ROOT/'examples/live-overlays/workflow.py')
w.f=load('vector_call_fixture',Path(__file__).with_name('fixture.py'))
original_sources=w.sources
def sources():return original_sources()|{p.relative_to(ROOT).as_posix():w.digest(p) for p in (Path(__file__),Path(__file__).with_name('fixture.py'),ROOT/'examples/resident-far-calls/fixture.py')}
w.sources=sources
from pcerecomp import cd_loads as cd,prepare,project
from pcerecomp.history import compose_history
from pcerecomp.overlays import compose_overlays
from pcerecomp.native_catalog import load_native_catalog
from pcerecomp.toc import Toc
OPTIONS=dict(analysis_policy='bounded-ram-cd-vectors-v1',call_depth_limit=8,
    data_ranges=[(0x10400F,17),(0x104025,3),(0x10402B,1),(0x104030,16)],vector_ranges=[(0x104032,4)])
CODE=[(0x100000,2048),(0x104000,64)]
def require(value,message):
    if not value:raise ValueError(message)

def create(out):
    original=w.create(out)
    toc=out/'disc.toc';toc.write_text(Toc.from_image(out/'disc.iso').text(),encoding='ascii',newline='\n')
    recipe=tomllib.loads((out/'bootstrap.toml').read_text());recipe['toc']=dict(path='disc.toc')
    (out/'bootstrap.toml').write_text(prepare._toml(recipe),encoding='utf-8',newline='\n')
    # No consumer was prepared yet. Bind the final original recipe, rather than
    # changing an already qualified package or relabeling a checkpoint.
    original['originals']['bootstrap.toml']=w.digest(out/'bootstrap.toml');original['originals']['disc.toc']=w.digest(toc)
    (out/'creation.json').write_text(json.dumps(original,indent=2)+'\n',encoding='utf-8',newline='\n')
    return original

def qualify(out,generator,cmake_args):
    os.environ.update(SDL_VIDEODRIVER='dummy',SDL_RENDER_DRIVER='software',SDL_AUDIODRIVER='dummy')
    original=w.inputs(out);images=dict(disc=out/'disc.iso',toc=out/'disc.toc')
    prepare.prepare_project(out/'bootstrap.toml',out/'bootstrap')
    project.build(out/'bootstrap/project.toml',out/'bootstrap-build',generator=generator,cmake_args=cmake_args)
    baseline=w.session(out,'discovery',out/'bootstrap/project.toml',out/'bootstrap-build',reference=True,collect=True,
        analysis_options=OPTIONS,analysis_code_ranges=CODE)
    library=compose_overlays([out/'discovery/epoch-1',out/'discovery/epoch-2'],out/'overlays')
    groups=[]
    for phase in (1,2):
        mapping=w.f.MPR.copy()
        if phase==2:mapping[3]=0x82
        groups.append(dict(id=f'phase-{phase}',mpr=mapping,roots=[0x4000],loads=[dict(id='body',lba=phase,
            byte_offset=0,sectors=1,length=2048,destination=0x100000,sha256=hashlib.sha256(w.f.sector(phase)).hexdigest())]))
    document=dict(format=cd.MAP_FORMAT,schema=1,coordinate=cd.COORDINATE,policy=cd.POLICY,
        media=dict(format='iso',image_sha256=Toc.from_image(images['disc']).image_sha256,toc_sha256=w.digest(images['toc'])),groups=groups)
    w.write(out/'load-map.json',document)
    composed=cd.declare(out/'load-map.json',out/'declarations',**images,**OPTIONS,
        resident_snapshot=out/'discovery/snapshot-1',resident_ranges=[(0x104000,64)])
    require(composed.instructions==library.instructions,'Composed CD/resident and whole-snapshot candidates differ')
    require(any(row['pc']==0x6020 for row in composed.instructions),'Reconstructed transfer destination missing')
    graphs=json.loads(composed.path.read_text())['groups']
    require(all(any(edge['kind']=='reconstructed_return' for edge in group['analysis']['edges']) for group in graphs),'No source-proven reconstructed edges')
    for group in graphs:
        edges=[edge for edge in group['analysis']['edges'] if edge['kind']=='vector_jump']
        require(len(edges)==2,'Expected exactly two source-qualified vector edges')
        words=[edge['vector_word'] for edge in edges]
        require([(v['pointer'],v['target']) for v in words]==[(0x6032,0x6028),(0x6034,0x602C)],'Pointer targets differ from authored literals')
        require(all(v['low']['canonical_physical'] in (0x104032,0x104034) and v['high']['canonical_physical']==v['low']['canonical_physical']+1 for v in words),'Per-byte physical mapping differs')

    compose_history([out/'discovery/capture.jsonl'],out/'observed',history_version=2)
    recipe=tomllib.loads((out/'bootstrap.toml').read_text());recipe['runtime']['tier']='native';results={}
    for kind,path in (('overlay','overlays/library.json'),('cd-loads','declarations/roots.json')):
        recipe['module']=dict(kind=kind,path=path,history_path='observed/history.json',history_version=2,partition_layout='shared',partition_size=1024)
        spec=out/(kind+'.toml');spec.write_text(prepare._toml(recipe),encoding='utf-8',newline='\n')
        consumer=out/kind;build=out/(kind+'-build');prepare.prepare_project(spec,consumer)
        project.build(consumer/'project.toml',build,generator=generator,cmake_args=cmake_args)
        catalog=load_native_catalog(consumer/'module/module.json',consumer/'declarations/roots.json',
            observation_history=consumer/'observation-history/history.json',**({'source_images':images} if kind=='cd-loads' else {}))
        require(len(catalog.declared-catalog.observed)>0,'No unobserved candidates remain')
        routes=[]
        for variant in (0,1):
            runs=[w.session(out,f'{kind}-{tier}-{variant}',consumer/'project.toml',build,reference=reference,variant=variant,
                checkpoint='final.pcec' if not reference and variant==0 else None) for tier,reference in (('reference',True),('native',False))]
            require(len(runs[0]['stages'])==len(runs[1]['stages'])==3,'Missing route boundaries')
            for left,right in zip(runs[0]['stages'],runs[1]['stages']):
                require(left['label']==right['label'] and w.exact(left['memory'],right['memory'])
                    and w.exact(w._projection(left['status']),w._projection(right['status'])),'Native/reference state differs')
            routes.append(dict(reference=runs[0]['work'],native=runs[1]['work']))
        forks=[w.session(out,f'{kind}-fork-'+tier,consumer/'project.toml',build,reference=reference,
            fork=(out/f'{kind}-native-0/checkpoints','final.pcec')) for tier,reference in (('reference',True),('native',False))]
        require(w.exact(w._projection(forks[0]['final']),w._projection(forks[1]['final']))
            and w.exact(forks[0]['stages'][0]['memory'],forks[1]['stages'][0]['memory']),'Checkpoint suffix differs')
        results[kind]=dict(declared=len(catalog.declared),declared_only_before_routes=len(catalog.declared-catalog.observed),routes=routes,forks=[v['work'] for v in forks])
    composed.revalidate();w.inputs(out)
    result=dict(passed=True,tool=original['tool'],sources=sources(),baseline=baseline['work'],identities=len(composed.instructions),consumers=results,
        scope='Authored firmware TII copies resident source; actual CD READ overlays; disjoint closed-snapshot composition; proven popped/restored/synthesized RTS, changed MPR and authenticated known indexed/nonindexed vectors; full literal WRAM/CDRAM/finalCPU and native/reference paused state; same-build checkpoint suffixes. Assisted branch/data gates. No retail, arbitrary-thunk, hardware, GPU or cross-build-state claim.')
    w.write(out/'qualification.json',result);return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('create','qualify'));parser.add_argument('output',type=Path)
    parser.add_argument('--generator');parser.add_argument('--cmake-arg',action='append',default=[]);args=parser.parse_args();out=args.output.resolve()
    print(json.dumps(create(out) if args.command=='create' else qualify(out,args.generator,args.cmake_arg),indent=2))
if __name__=='__main__':main()
