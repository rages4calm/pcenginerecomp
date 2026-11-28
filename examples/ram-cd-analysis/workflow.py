"""Qualify shared RAM/CD analysis through real authored CD loads and TCP forks."""
import argparse,hashlib,importlib.util,json,os,sys,tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

w=load('ram_cd_loader_workflow',ROOT/'examples/live-overlays/workflow.py')
w.f=load('ram_cd_call_fixture',Path(__file__).with_name('fixture.py'))
original_sources=w.sources
def sources():return original_sources()|{p.relative_to(ROOT).as_posix():w.digest(p) for p in (Path(__file__),Path(__file__).with_name('fixture.py'))}
w.sources=sources
from pcerecomp import cd_loads as cd,prepare,project
from pcerecomp.history import compose_history
from pcerecomp.overlays import compose_overlays
from pcerecomp.native_catalog import load_native_catalog
from pcerecomp.toc import Toc

OPTIONS=dict(analysis_policy='bounded-ram-cd-candidates-v1',call_depth_limit=8,data_ranges=[(0x100030,1)])

def require(value,message):
    if not value:raise ValueError(message)

def create(out):
    result=w.create(out)
    toc=out/'disc.toc';toc.write_text(Toc.from_image(out/'disc.iso').text(),encoding='ascii',newline='\n')
    document=dict(format=cd.MAP_FORMAT,schema=1,coordinate=cd.COORDINATE,policy=cd.POLICY,
        media=dict(format='iso',image_sha256=Toc.from_image(out/'disc.iso').image_sha256,toc_sha256=w.digest(toc)),
        groups=[dict(id=f'phase-{phase}',mpr=w.f.MPR.copy(),roots=[0x4000],loads=[dict(id='body',lba=phase,
            byte_offset=0,sectors=1,length=2048,destination=0x100000,sha256=hashlib.sha256(w.f.sector(phase)).hexdigest())]) for phase in (1,2)])
    w.write(out/'load-map.json',document)
    admitted=cd.declare(out/'load-map.json',out/'declarations',disc=out/'disc.iso',toc=toc,**OPTIONS)
    w.write(out/'offline-creation.json',dict(sha256=admitted.sha256,identities=len(admitted.instructions),map_sha256=w.digest(out/'load-map.json'),toc_sha256=w.digest(toc)))
    return result

def qualify(out,generator,cmake_args):
    os.environ.update(SDL_VIDEODRIVER='dummy',SDL_RENDER_DRIVER='software',SDL_AUDIODRIVER='dummy')
    created=w.inputs(out);images=dict(disc=out/'disc.iso',toc=out/'disc.toc')
    offline=cd.load(out/'declarations/roots.json',images)
    original=json.loads((out/'offline-creation.json').read_text())
    require(offline.sha256==original['sha256'] and w.digest(out/'load-map.json')==original['map_sha256']
        and w.digest(out/'disc.toc')==original['toc_sha256'],'Original offline input changed')
    prepare.prepare_project(out/'bootstrap.toml',out/'bootstrap')
    project.build(out/'bootstrap/project.toml',out/'bootstrap-build',generator=generator,cmake_args=cmake_args)
    baseline=w.session(out,'discovery',out/'bootstrap/project.toml',out/'bootstrap-build',reference=True,collect=True,analysis_options=OPTIONS)
    library=compose_overlays([out/'discovery/epoch-1',out/'discovery/epoch-2'],out/'overlays')
    require(offline.instructions==library.instructions,'RAM/CD shared candidates differ for identical source bytes')
    require(all(row['pc']!=0x4030 for row in offline.instructions),'Data became executable')
    compose_history([out/'discovery/capture.jsonl'],out/'observed',history_version=2)
    recipe=tomllib.loads((out/'bootstrap.toml').read_text());recipe['runtime']['tier']='native'
    results={}
    for kind,path in (('overlay','overlays/library.json'),('cd-loads','declarations/roots.json')):
        if kind=='cd-loads':recipe['toc']=dict(path='disc.toc')
        recipe['module']=dict(kind=kind,path=path,history_path='observed/history.json',history_version=2,partition_layout='shared',partition_size=1024)
        spec=out/(kind+'.toml');spec.write_text(prepare._toml(recipe),encoding='utf-8',newline='\n')
        consumer=out/kind;build=out/(kind+'-build');prepare.prepare_project(spec,consumer)
        project.build(consumer/'project.toml',build,generator=generator,cmake_args=cmake_args)
        catalog=load_native_catalog(consumer/'module/module.json',consumer/'declarations/roots.json',
            observation_history=consumer/'observation-history/history.json',**({'source_images':images} if kind=='cd-loads' else {}))
        require(len(catalog.declared-catalog.observed)>0,'No unobserved static candidates remain')
        routes=[]
        for variant in (0,1):
            runs=[w.session(out,f'{kind}-{tier}-{variant}',consumer/'project.toml',build,reference=reference,variant=variant,
                checkpoint='final.pcec' if not reference and variant==0 else None) for tier,reference in (('reference',True),('native',False))]
            for left,right in zip(runs[0]['stages'],runs[1]['stages']):
                require(left['label']==right['label'] and w.exact(left['memory'],right['memory'])
                    and w.exact(w._projection(left['status']),w._projection(right['status'])),'Native/reference paused state differs')
            routes.append(dict(reference=runs[0]['work'],native=runs[1]['work']))
        forks=[w.session(out,f'{kind}-fork-'+tier,consumer/'project.toml',build,reference=reference,
            fork=(out/f'{kind}-native-0/checkpoints','final.pcec')) for tier,reference in (('reference',True),('native',False))]
        require(w.exact(w._projection(forks[0]['final']),w._projection(forks[1]['final']))
            and w.exact(forks[0]['stages'][0]['memory'],forks[1]['stages'][0]['memory']),'Checkpoint suffix differs')
        results[kind]=dict(declared=len(catalog.declared),declared_only_before_routes=len(catalog.declared-catalog.observed),routes=routes,forks=[v['work'] for v in forks])
    offline.revalidate();w.inputs(out)
    result=dict(passed=True,tool=created['tool'],sources=sources(),baseline=baseline['work'],identities=len(offline.instructions),consumers=results,
        scope='Authored actual CD READ; matched shared RAM/CD candidate sets; balanced JSR/PHA/PLA/RTS and explicit data store; independently literal full WRAM/CDRAM/final CPU; native/reference TCP routes and same-build checkpoint suffixes. Assisted branch/data gates disclosed. No retail, hardware, GPU, cross-build checkpoint or routine-closure claim.')
    w.write(out/'qualification.json',result);return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('create','qualify'));parser.add_argument('output',type=Path)
    parser.add_argument('--generator');parser.add_argument('--cmake-arg',action='append',default=[]);args=parser.parse_args();out=args.output.resolve()
    print(json.dumps(create(out) if args.command=='create' else qualify(out,args.generator,args.cmake_arg),indent=2))
if __name__=='__main__':main()
