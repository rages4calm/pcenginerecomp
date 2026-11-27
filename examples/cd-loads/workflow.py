"""Offline CD roots cross-checked against an authored original guest CD READ loader.

All fixtures are authored. SDL dummy/software drivers keep this off the GPU.
Optional chdman creates a genuine CD CHD from the same authored CUE/ISO.
"""
import argparse
import copy
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('authored_cd_loader',ROOT/'examples/live-overlays/workflow.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
from pcerecomp import cd_loads as cd,prepare,project
from pcerecomp.history import compose_history
from pcerecomp.native_catalog import load_native_catalog
from pcerecomp.native_gaps import report_native_gaps
from pcerecomp.overlay_snapshot import exact
from pcerecomp.toc import Toc
from pcerecomp.media import Chd,ChdReader
from pcerecomp.cue import Cue


def digest_bytes(raw):return hashlib.sha256(raw).hexdigest()


def producer():return {'examples/cd-loads/workflow.py':w.digest(Path(__file__))}


def require(value,message):
    if not value:raise ValueError(message)


def _map(out,disc,toc,format='iso',libchdr=None):
    media=dict(format=format,image_sha256=Toc.from_image(disc).image_sha256,toc_sha256=w.digest(toc))
    if libchdr is not None:media['libchdr_sha256']=w.digest(libchdr)
    return dict(format=cd.MAP_FORMAT,schema=1,coordinate=cd.COORDINATE,policy=cd.POLICY,media=media,
        groups=[dict(id=f'phase-{phase}',mpr=w.f.MPR.copy(),
            loads=[dict(id='body',lba=phase,byte_offset=0,sectors=1,length=2048,destination=0x100000,sha256=digest_bytes(w.f.sector(phase)))],
            roots=[0x4000+offset for offset in (0,3,5,7,9,11,14,17)]) for phase in (1,2)])


def create(output):
    out=Path(output).resolve();created=w.create(out)
    toc=out/'disc.toc';toc.write_text(Toc.from_image(out/'disc.iso').text(),encoding='ascii',newline='\n')
    value=_map(out,out/'disc.iso',toc)
    w.write(out/'load-map.json',value)
    admitted=cd.declare(out/'load-map.json',out/'declarations',disc=out/'disc.iso',toc=toc)
    receipt=dict(tool=created['tool'],producer=producer(),map_sha256=w.digest(out/'load-map.json'),declarations_sha256=admitted.sha256,
                 declared_identities=len(admitted.instructions),execution_evidence=False,compiled=False,executed=False)
    w.write(out/'offline-creation.json',receipt)
    return receipt


def media_variants(out,*,chdman=None,libchdr=None):
    """Read real cooked sectors and prepare typed maps; this is not guest execution."""
    (out/'disc.cue').write_text('FILE "disc.iso" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n',encoding='ascii')
    candidates=[('cue',out/'disc.cue',None)]
    result={}
    if chdman is not None:
        require(libchdr is not None,'CHD qualification requires explicit libchdr')
        command=[str(Path(chdman).resolve()),'createcd','-i',str(out/'disc.cue'),'-o',str(out/'disc.chd'),'-np','2']
        with (out/'chdman.log').open('xb') as stream:
            subprocess.run(command,check=True,stdout=stream,stderr=subprocess.STDOUT,timeout=120)
        result['creator']=dict(binary_sha256=w.digest(chdman),command=command,output_sha256=w.digest(out/'disc.chd'))
        candidates.append(('chd',out/'disc.chd',Path(libchdr).resolve()))
    for format,disc,decoder in candidates:
        toc=out/f'{format}.toc';toc.write_text(Toc.from_image(disc).text(),encoding='ascii',newline='\n')
        document=_map(out,disc,toc,format,decoder);map_path=out/f'{format}-map.json';w.write(map_path,document)
        images=dict(disc=disc,toc=toc)
        if decoder is not None:images['libchdr']=decoder
        admitted=cd.declare(map_path,out/f'{format}-declarations',**images)
        if format=='cue':
            reader=Cue(disc)
            sectors=[reader.read(phase) for phase in (1,2)]
        else:
            with ChdReader(Chd(disc),decoder) as reader:sectors=[reader.lba(phase) for phase in (1,2)]
        require(all(actual==w.f.sector(phase) for phase,actual in enumerate(sectors,1)),
                'Cooked '+format+' sectors differ from independent authored literals')
        baseline=cd.load(out/'declarations/roots.json',dict(disc=out/'disc.iso',toc=out/'disc.toc'))
        require(admitted.instructions==baseline.instructions,'CD reader source identities differ')
        result[format]=dict(images=images,declarations=admitted.path,sha256=admitted.sha256,
            cooked_sector_sha256=[digest_bytes(s) for s in sectors],literal_bytes_equal=True,
            scope='Actual media-reader and offline-declaration admission; not a guest route')
    return result


def qualify(output,generator=None,cmake_args=(),*,chdman=None,libchdr=None):
    os.environ.update(SDL_VIDEODRIVER='dummy',SDL_RENDER_DRIVER='software',SDL_AUDIODRIVER='dummy')
    out=Path(output).resolve();created=w.inputs(out)
    original=json.loads((out/'offline-creation.json').read_text())
    require(original['tool']==created['tool'] and original['producer']==producer() and original['map_sha256']==w.digest(out/'load-map.json'),
            'Original offline declarations/source changed')
    images=dict(disc=out/'disc.iso',toc=out/'disc.toc')
    offline=cd.load(out/'declarations/roots.json',images)
    require(offline.sha256==original['declarations_sha256'],'Original declaration graph changed')
    variants=media_variants(out,chdman=chdman,libchdr=libchdr)
    prepare.prepare_project(out/'bootstrap.toml',out/'bootstrap')
    project.build(out/'bootstrap/project.toml',out/'bootstrap-build',generator=generator,cmake_args=cmake_args)
    baseline=w.session(out,'discovery',out/'bootstrap/project.toml',out/'bootstrap-build',reference=True,collect=False)
    load_witness=[]
    for phase in (1,2):
        raw=(out/f'discovery/ready-{phase}.cd').read_bytes()
        require(raw==w.f.expected_cd(phase),'Actual guest-loaded CD RAM differs from literal sector bytes')
        member=offline.source_metadata['groups'][phase-1]['loads'][0]
        require(digest_bytes(raw[:member['length']])==member['sha256'],'Actual CD READ bytes differ from declared source')
        load_witness.append(dict(group=f'phase-{phase}',actual_snapshot_sha256=digest_bytes(raw),
            transferred_sha256=digest_bytes(raw[:member['length']]),declared_sha256=member['sha256'],
            original_snapshot=f'discovery/ready-{phase}.cd',bytes=member['length'],matches=True))
    compose_history([out/'discovery/capture.jsonl'],out/'observed',history_version=2)
    recipe=tomllib.loads((out/'bootstrap.toml').read_text())
    recipe['module']=dict(kind='cd-loads',path='declarations/roots.json',history_path='observed/history.json',
        history_version=2,partition_layout='shared',partition_size=1024)
    recipe['toc']=dict(path='disc.toc');recipe['runtime']['tier']='native'
    (out/'native.toml').write_text(prepare._toml(recipe),encoding='utf-8',newline='\n')
    prepare.prepare_project(out/'native.toml',out/'native')
    project.build(out/'native/project.toml',out/'native-build',generator=generator,cmake_args=cmake_args)
    catalog=load_native_catalog(out/'native/module/module.json',out/'native/declarations/roots.json',source_images=images,
        observation_history=out/'native/observation-history/history.json')
    require(len(catalog.declared-catalog.observed)==3,'Unexecuted explicit CD root count differs')
    prepared={}
    for name,variant in variants.items():
        if name=='creator':continue
        spec=copy.deepcopy(recipe);spec['module']['path']=str(variant['declarations'])
        for asset,path in variant['images'].items():spec[asset]=dict(path=str(path))
        spec_path=out/f'{name}-consumer.toml';spec_path.write_text(prepare._toml(spec),encoding='utf-8',newline='\n')
        receipt=prepare.prepare_project(spec_path,out/f'{name}-consumer')
        checked=project.verify(out/f'{name}-consumer/project.toml')
        args=project.declaration_arguments(checked)
        c=load_native_catalog(checked['files']['module_manifest'],checked['files']['module_declared_roots'],
            observation_history=checked['files']['module_observation_history'],**args)
        require(c.emitted==catalog.emitted,'Prepared reader changes emitted source identities')
        build=out/f'{name}-build'
        project.build(out/f'{name}-consumer/project.toml',build,generator=generator,cmake_args=cmake_args)
        reference=w.session(out,f'{name}-reference',out/f'{name}-consumer/project.toml',build,reference=True)
        native=w.session(out,f'{name}-native',out/f'{name}-consumer/project.toml',build,reference=False)
        require(len(reference['stages'])==len(native['stages'])==3,'Media-provider route stage count differs')
        for left,right in zip(reference['stages'],native['stages']):
            require(left['label']==right['label'] and exact(left['memory'],right['memory'])
                    and exact(w._projection(left['status']),w._projection(right['status'])),
                    name+' actual guest loader native/reference state differs')
        prepared[name]=dict(prepared=receipt['prepared'],compiled=True,executed=True,
                            work=native['work'],reference_work=reference['work'],
                            map_sha256=checked['identities']['module_declared_roots'])
    routes=[]
    for variant in (0,1):
        ref=w.session(out,f'reference-{variant}',out/'native/project.toml',out/'native-build',reference=True,variant=variant)
        native=w.session(out,f'native-{variant}',out/'native/project.toml',out/'native-build',reference=False,variant=variant,
                         checkpoint='final.pcec' if variant==0 else None)
        require(len(ref['stages'])==len(native['stages'])==3,'ISO route stage count differs')
        for left,right in zip(ref['stages'],native['stages']):
            require(left['label']==right['label'] and exact(left['memory'],right['memory'])
                    and exact(w._projection(left['status']),w._projection(right['status'])),
                    'Native/reference complete paused observations differ')
        routes.append(dict(variant=variant,work=native['work'],keys=native['keys']))
    gaps=report_native_gaps(catalog,[out/f'native-{v}/capture.jsonl' for v in (0,1)],capture_profile='extended')
    require(gaps['summary']['declared_emitted_exercised']==11 and gaps['summary']['declared_emitted_unexercised']==0,
            'Explicit CD roots were not all exercised')
    w.write(out/'native-gaps.json',gaps)
    forks=[w.session(out,'fork-reference' if ref else 'fork-native',out/'native/project.toml',out/'native-build',
        reference=ref,fork=(out/'native-0/checkpoints','final.pcec')) for ref in (True,False)]
    require(exact(w._projection(forks[0]['final']),w._projection(forks[1]['final']))
            and exact(forks[0]['stages'][0]['memory'],forks[1]['stages'][0]['memory']),
            'Same-build checkpoint fork differs')
    changed=w.session(out,'changed-source',out/'native/project.toml',out/'native-build',reference=False,changed=True)
    offline.revalidate();w.inputs(out)
    require(original['producer']==producer(),'Offline workflow producer changed during qualification')
    for variant in variants.values():
        if 'images' in variant:variant['images']={k:str(v) for k,v in variant['images'].items()};variant['declarations']=str(variant['declarations'])
    result=dict(passed=True,tool=created['tool'],sources=w.sources()|producer(),original_offline=original,
        actual_guest_loads=load_witness,media_readers=variants,prepared_readers=prepared,
        declared=len(catalog.declared),declared_only_before_routes=len(catalog.declared-catalog.observed),routes=routes,
        baseline=dict(work=baseline['work'],capture_sha256=baseline['capture_sha256']),
        forks=[row['work'] for row in forks],changed_guard=changed['guard_result'],gaps=gaps['summary'],
        scope='Authored original-program CD READ loader, offline roots declared before execution, full literal WRAM/CDRAM and CPU/device state reference comparisons. ISO executes both branches and same-build checkpoint forks; CUE and optional genuine CD CHD execute native/reference loader routes after separate consumer preparation/builds. Explicit assisted data gates and branch choice; no fabricated snapshots/hits, routine closure, retail coverage or cross-build checkpoint migration.')
    w.write(out/'qualification.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('create','qualify'));parser.add_argument('output',type=Path)
    parser.add_argument('--generator');parser.add_argument('--cmake-arg',action='append',default=[])
    parser.add_argument('--chdman',type=Path);parser.add_argument('--libchdr',type=Path)
    args=parser.parse_args()
    result=(create(args.output) if args.command=='create' else qualify(args.output,args.generator,args.cmake_arg,
        chdman=args.chdman,libchdr=args.libchdr))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
