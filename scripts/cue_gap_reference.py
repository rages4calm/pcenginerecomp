"""Authored CUE POSTGAP media proof against original Beetle and Gear readers.

Beetle reads the actual POSTGAP CUE. Gear receives a separately retained,
explicit equivalent-PREGAP fixture where available; its CUE reader does not
implement POSTGAP. Raw unstored audio remains unavailable while the toolkit's
existing playback cache produces silence. This is media evidence, not CPU,
drive scheduling, raw subchannel or complete emulator/hardware qualification.
"""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from cue_fixture import audio_sector,data_sector,write_case,composite_identity
from scripts import beetle_reference as beetle
from scripts import mapper_reference as infrastructure
from scripts import filtered_audio_reference as gear
from scripts import cue_reference as comparison
from scripts import hucard_reference as common
sha=gear.sha


def definitions():
    """Literal disc coordinates; never derived from either production parser."""
    legacy='FILE "a.bin" BINARY\n TRACK 01 AUDIO\n INDEX 01 00:00:00\n TRACK 02 AUDIO\n INDEX 01 00:00:03\n'
    split='FILE "a.bin" BINARY\n TRACK 01 AUDIO\n INDEX 01 00:00:00\n POSTGAP 00:00:02\nFILE "b.bin" BINARY\n TRACK 02 AUDIO\n PREGAP 00:00:01\n INDEX 01 00:00:00\n POSTGAP 00:00:03\nFILE "c.bin" BINARY\n TRACK 03 AUDIO\n PREGAP 00:00:02\n INDEX 01 00:00:00\n POSTGAP 00:00:02\n'
    split_gear='FILE "a.bin" BINARY\n TRACK 01 AUDIO\n INDEX 01 00:00:00\nFILE "b.bin" BINARY\n TRACK 02 AUDIO\n PREGAP 00:00:03\n INDEX 01 00:00:00\nFILE "c.bin" BINARY\n TRACK 03 AUDIO\n PREGAP 00:00:05\n INDEX 01 00:00:00\n'
    mixed='FILE "data.bin" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n POSTGAP 00:00:02\nFILE "a.bin" BINARY\n TRACK 02 AUDIO\n PREGAP 00:00:01\n INDEX 01 00:00:00\n POSTGAP 00:00:02\n'
    mixed_gear='FILE "data.bin" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\nFILE "a.bin" BINARY\n TRACK 02 AUDIO\n PREGAP 00:00:03\n INDEX 01 00:00:00\n'
    cases=[
        dict(id='legacy-no-gaps',cue=legacy,files=[('a.bin',[('a',1,f) for f in range(5)])],tracks=[[0,0],[3,0]],leadout=5,
             mapping=[(f,'a',1,f) for f in range(5)],playable=list(range(5)),gear_cue=legacy,gear_leadout=5,beetle_pcm=list(range(5))),
        dict(id='split-post-pre-trailing',cue=split,files=[('a.bin',[('a',2,f) for f in range(3)]),('b.bin',[('a',3,f) for f in range(4)]),('c.bin',[('a',4,f) for f in range(3)])],
             tracks=[[0,0],[6,0],[15,0]],leadout=20,mapping=[(f,'a',2,f) for f in range(3)]+[(6+f,'a',3,f) for f in range(4)]+[(15+f,'a',4,f) for f in range(3)],
             playable=[0,1,2,6,7,8,9,15,16,17],gear_cue=split_gear,gear_leadout=18,beetle_pcm=list(range(20))),
        dict(id='shared-stored-with-postgap',cue='FILE "a.bin" BINARY\n TRACK 01 AUDIO\n INDEX 01 00:00:00\n POSTGAP 00:00:02\n TRACK 02 AUDIO\n INDEX 00 00:00:02\n INDEX 01 00:00:03\n TRACK 03 AUDIO\n INDEX 01 00:00:06\n POSTGAP 00:00:01\n',
             files=[('a.bin',[('a',5,f) for f in range(7)])],tracks=[[0,0],[5,0],[8,0]],leadout=10,
             mapping=[(0,'a',5,0),(1,'a',5,1),(4,'s',5,2),(5,'a',5,3),(6,'a',5,4),(7,'a',5,5),(8,'a',5,6)],
             playable=[0,1,4,5,6,7,8],gear_cue=None,gear_leadout=None,beetle_pcm=list(range(10))),
        dict(id='mixed-data-audio-postgap',cue=mixed,files=[('data.bin',[('d',6,f) for f in range(3)]),('a.bin',[('a',7,f) for f in range(2)])],
             tracks=[[0,4],[6,0]],leadout=10,mapping=[(f,'d',6,f) for f in range(3)]+[(6+f,'a',7,f) for f in range(2)],playable=[6,7],
             gear_cue=mixed_gear,gear_leadout=8,beetle_pcm=[6,7,8,9]),
        dict(id='final-postgap-only',cue='FILE "a.bin" BINARY\n TRACK 01 AUDIO\n INDEX 01 00:00:00\n POSTGAP 00:00:03\n',
             files=[('a.bin',[('a',8,f) for f in range(2)])],tracks=[[0,0]],leadout=5,mapping=[(f,'a',8,f) for f in range(2)],playable=[0,1],
             gear_cue='FILE "a.bin" BINARY\n TRACK 01 AUDIO\n INDEX 01 00:00:00\n',gear_leadout=2,beetle_pcm=list(range(5))),
        dict(id='zero-postgap',cue=legacy.replace('INDEX 01 00:00:03','INDEX 01 00:00:03\n POSTGAP 00:00:00'),
             files=[('a.bin',[('a',1,f) for f in range(5)])],tracks=[[0,0],[3,0]],leadout=5,mapping=[(f,'a',1,f) for f in range(5)],playable=list(range(5)),
             gear_cue=legacy,gear_leadout=5,beetle_pcm=list(range(5))),
        dict(id='msf-gap-boundary',cue='FILE "a.bin" BINARY\n TRACK 01 AUDIO\n INDEX 01 00:00:00\n POSTGAP 00:00:74\nFILE "b.bin" BINARY\n TRACK 02 AUDIO\n PREGAP 00:00:02\n INDEX 01 00:00:00\n',
             files=[('a.bin',[('a',9,f) for f in range(3)]),('b.bin',[('a',10,f) for f in range(2)])],tracks=[[0,0],[79,0]],leadout=81,
             mapping=[(f,'a',9,f) for f in range(3)]+[(79+f,'a',10,f) for f in range(2)],playable=[0,1,2,79,80],
             gear_cue='FILE "a.bin" BINARY\n TRACK 01 AUDIO\n INDEX 01 00:00:00\nFILE "b.bin" BINARY\n TRACK 02 AUDIO\n PREGAP 00:01:01\n INDEX 01 00:00:00\n',gear_leadout=81,beetle_pcm=list(range(81))),
    ]
    return cases


def operations(case,tier='tool'):
    mapping={row[0]:row[1:] for row in case['mapping']}
    ops=[('t',)]
    if tier=='beetle':
        for lba,(kind,_,_) in sorted(mapping.items()):ops.append(('d' if kind=='d' else 'a',lba))
        ops += [('m',lba) for lba in case['beetle_pcm']]
    else:
        end=case['leadout'] if tier=='tool' else case['gear_leadout']
        for lba in range(end+2):
            ops.append(('p',lba))
            if tier=='tool':ops += [('d',lba),('a',lba),('m',lba)]
            elif mapping.get(lba,('',))[0]=='d':ops.append(('d',lba))
            else:ops.append(('a',lba))
    return ops+[('t',)]


def expected(case,ops,tier='tool'):
    mapping={row[0]:row[1:] for row in case['mapping']};rows=[]
    for op in ops:
        code=op[0]
        if code=='t':rows.append(dict(kind='toc',leadout=case['gear_leadout'] if tier=='gear' else case['leadout'],tracks=case['tracks']));continue
        lba=op[1];item=mapping.get(lba);kind=item[0] if item else ''
        if code=='p':row=dict(kind='playable',lba=lba,value=lba in case['playable'])
        elif code=='d':
            row=dict(kind='data',lba=lba,ok=kind=='d')
            if kind=='d':row['bytes']=data_sector(item[1],item[2]).hex()
            else:row['error']='out_of_range' if lba>=case['leadout'] else 'wrong_data_track' if kind=='a' else 'unrecoverable_data'
        elif code=='a':
            row=dict(kind='audio',lba=lba,ok=kind in ('a','s'))
            if row['ok']:row['samples']=audio_sector(item[1],item[2])
            else:row['error']='unavailable_audio'
        elif code=='m':row=dict(kind='pcm',lba=lba,samples=audio_sector(item[1],item[2]) if lba in case['playable'] else [0]*1176)
        else:raise ValueError('Unknown authored plan operation')
        rows.append(row)
    return rows


def read_rows(text):
    def obj(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate JSON key')
            result[key]=value
        return result
    rows=[json.loads(line,object_pairs_hook=obj,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Invalid JSON constant'))) for line in text.splitlines()]
    if len(rows)>4096:raise ValueError('Observation bound exceeded')
    return rows


def validate(actual,wanted):
    mismatch=comparison.difference(actual,wanted)
    if mismatch:raise ValueError('Authored media observation differs: '+str(mismatch))
    def count(value):
        if isinstance(value,dict):return sum(count(v) for v in value.values())
        if isinstance(value,list):return sum(map(count,value))
        return 1
    return count(wanted)


def negative_controls(actual,wanted):
    """Mutate observed closed media rows only; never alter sources or images."""
    validate(actual,wanted);controls=[]
    def selected(predicate):return next(i for i,row in enumerate(actual) if predicate(row))
    def reject(name,index,mutate):
        bad=list(actual);bad[index]=copy.deepcopy(actual[index]);mutate(bad[index])
        try:validate(bad,wanted)
        except ValueError:controls.append(dict(name=name,rejected=True))
        else:raise ValueError('Unexpected negative acceptance: '+name)
    toc=selected(lambda r:r['kind']=='toc')
    reject('leadout',toc,lambda r:r.update(leadout=r['leadout']+1))
    reject('INDEX01-coordinate',toc,lambda r:r['tracks'][0].__setitem__(0,1))
    reject('track-control-type',toc,lambda r:r['tracks'][0].__setitem__(1,4))
    data=selected(lambda r:r['kind']=='data' and r['ok'])
    reject('program-data-payload',data,lambda r:r.update(bytes=('ff' if r['bytes'][:2]!='ff' else '00')+r['bytes'][2:]))
    audio=selected(lambda r:r['kind']=='audio' and r['ok'])
    reject('signed-audio-payload',audio,lambda r:r['samples'].__setitem__(0,r['samples'][0]^1))
    reject('short-audio-payload',audio,lambda r:r['samples'].pop())
    silence=selected(lambda r:r['kind']=='pcm' and r['lba']==3 and not any(r['samples']))
    reject('virtual-gap-PCM',silence,lambda r:r['samples'].__setitem__(0,1))
    unavailable=selected(lambda r:r['kind']=='audio' and not r['ok'])
    reject('unavailable-raw-audio-accepted',unavailable,lambda r:r.update(ok=True))
    gap=selected(lambda r:r['kind']=='data' and r.get('error')=='unrecoverable_data')
    reject('gap-data-accepted',gap,lambda r:r.update(ok=True))
    reject('data-failure-category',gap,lambda r:r.update(error='out_of_range'))
    playable=selected(lambda r:r['kind']=='playable')
    reject('boolean-is-not-integer',playable,lambda r:r.update(value=int(r['value'])))
    for name,bad in [('missing-row',actual[:-1]),('extra-row',actual+[actual[-1]])]:
        try:validate(bad,wanted)
        except ValueError:controls.append(dict(name=name,rejected=True))
        else:raise ValueError('Unexpected negative acceptance: '+name)
    return controls


def plan_file(path,ops):
    if len(ops)>4096:raise ValueError('Bounded authored plan required')
    path.write_text(str(len(ops))+'\n'+'\n'.join(' '.join(map(str,op)) for op in ops)+'\n',encoding='ascii')


def build_beetle(args,out,report,bindings,compiler):
    directory=out/'beetle';directory.mkdir()
    tree,tree_sha,files=beetle.source_snapshot(args.beetle_source.resolve(),directory)
    bindings['beetle_raw_sources']={item['original']['path']:item['original']['sha256'] for item in files.values()}
    bindings['beetle_compile_sources']={item['compiled']['path']:item['compiled']['sha256'] for item in files.values()}
    cpp,c=beetle.sources(tree);wrapper=directory/'wrapper';wrapper.mkdir()
    cmake,ninja=(Path(shutil.which(str(v)) or '').resolve() for v in (args.cmake,args.ninja))
    c_compiler=compiler.with_name(compiler.name.replace('clang++','clang').replace('g++','gcc'))
    if any(not p.is_file() for p in (cmake,ninja,c_compiler)):raise ValueError('Existing C/C++ compiler, CMake and Ninja required')
    bindings['tools'].update({str(p):sha(p) for p in (cmake,ninja,c_compiler)})
    q=beetle.quote;probe=ROOT/'tests/beetle_cue_probe.cpp'
    lines=['cmake_minimum_required(VERSION 3.20)','project(OriginalBeetleCue LANGUAGES C CXX)','set(CMAKE_C_STANDARD 11)','set(CMAKE_CXX_STANDARD 20)',
           'add_executable(beetle-cue '+q(probe)+' '+' '.join(q(tree/p) for p in cpp+c)+')',
           'target_include_directories(beetle-cue PRIVATE '+' '.join(q(p) for p in (tree,tree/'mednafen',tree/'mednafen/include',tree/'mednafen/hw_sound',tree/'mednafen/hw_cpu',tree/'mednafen/hw_misc',tree/'libretro-common/include'))+')',
           'target_compile_definitions(beetle-cue PRIVATE INLINE=inline WANT_PCE_EMU WANT_STEREO_SOUND WANT_16BPP FRONTEND_SUPPORTS_RGB565 NEED_TREMOR STDC_HEADERS __STDC_LIMIT_MACROS __LIBRETRO__ _LOW_ACCURACY_ MEDNAFEN_VERSION_NUMERIC=931 PACKAGE="mednafen")',
           'if(WIN32)','target_link_libraries(beetle-cue PRIVATE winmm)','endif()']
    config=wrapper/'CMakeLists.txt';config.write_text('\n'.join(lines)+'\n',encoding='utf-8');bindings['beetle_build_inputs']={str(config):sha(config)}
    build=directory/'build'
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_COMPILER='+str(c_compiler),'-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],'beetle-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','beetle-cue','--parallel','4'],'beetle-build',out,report,bindings,600)
    binary=build/('beetle-cue.exe' if os.name=='nt' else 'beetle-cue')
    bindings['beetle_binary']={str(binary):sha(binary)}
    bindings['beetle_objects']={str(p):sha(p) for p in build.rglob('*') if p.is_file() and p.suffix in ('.o','.obj')}
    report['beetle_tree_sha256']=tree_sha
    return binary


def build_gear(args,out,report,bindings,compiler):
    directory=out/'gear';directory.mkdir()
    tree,files=infrastructure.pinned_snapshot(args.gear_source.resolve(),directory,bindings)
    names=['src/cdrom_image.cpp','src/cdrom_cuebin_image.cpp','src/media_file.cpp','src/media_file_native.cpp','src/ogg_vorbis_decoder.cpp',
           'platforms/shared/dependencies/minivorbis/minivorbis.c','platforms/shared/dependencies/miniz/miniz.c']
    if any(name not in files for name in names):raise ValueError('Pinned original media source missing')
    deps=tree/'platforms/shared/dependencies';flags=['-O2','-ffunction-sections','-fdata-sections','-DGG_DISABLE_DISASSEMBLER','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for path in (tree/'src',deps/'miniz',deps/'minivorbis'):flags+=['-I',str(path)]
    objects=directory/'objects';objects.mkdir();jobs=[]
    for index,path in enumerate([tree/name for name in names]+[ROOT/'tests/geargrafx_cue_gap_probe.cpp']):
        obj=objects/(str(index)+'-'+path.stem+'.o');cpp=path.suffix=='.cpp'
        command=[str(compiler),*flags,'-x','c++' if cpp else 'c',*(['-std=c++20','-include','cerrno'] if cpp else ['-std=c11']),'-c',str(path),'-o',str(obj)]
        jobs.append((command,obj));report['commands'].append(command)
    def compile_one(job):
        command,obj=job;result=subprocess.run(command,capture_output=True,text=True,timeout=180)
        obj.with_suffix('.log').write_text(result.stdout+result.stderr,encoding='utf-8');result.check_returncode()
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(compile_one,jobs))
    binary=directory/'gear-cue-gap.exe'
    common.evidence([str(compiler),*[str(p) for _,p in jobs],'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(p):sha(p) for _,p in jobs};bindings['gear_binary']={str(binary):sha(binary)}
    return binary


def build_tool(args,out,report,bindings,compiler):
    cmake,ninja=(Path(shutil.which(str(v)) or '').resolve() for v in (args.cmake,args.ninja))
    wrapper=out/'tool-wrapper';wrapper.mkdir();q=infrastructure.cmake_quote;tool=args.tool_source.resolve()
    lines=['cmake_minimum_required(VERSION 3.20)','project(AuthoredCueGap LANGUAGES CXX)',
           *['set('+option+' OFF CACHE BOOL "" FORCE)' for option in ('PCE_BUILD_TOOLS','PCE_BUILD_TESTS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE','BUILD_TESTING')],
           'add_subdirectory('+q(tool)+' tool)',
           'add_executable(cue-gap '+q(ROOT/'tests/cue_gap_tests.cpp')+' '+q(tool/'runtime/src/no_module.cpp')+')',
           'target_link_libraries(cue-gap PRIVATE pce-runtime)']
    config=wrapper/'CMakeLists.txt';config.write_text('\n'.join(lines)+'\n',encoding='utf-8');bindings['tool_build_inputs']={str(config):sha(config)}
    build=out/'tool-build'
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],'tool-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','cue-gap','--parallel','4'],'tool-build',out,report,bindings,600)
    binary=build/('cue-gap.exe' if os.name=='nt' else 'cue-gap')
    bindings['tool_binary']={str(binary):sha(binary)};bindings['tool_objects']={str(p):sha(p) for p in build.rglob('*') if p.is_file() and p.suffix in ('.o','.obj','.a')}
    return binary


def run(args):
    out=args.out.resolve();tool=args.tool_source.resolve();compiler=Path(shutil.which(str(args.compiler)) or '').resolve()
    if out.exists() or not out.is_relative_to(ROOT/'.local') or not compiler.is_file():raise ValueError('Require compiler and NEW private output')
    sys.path.insert(0,str(tool))
    from pcerecomp.project import source_identity
    from pcerecomp.cue import Cue
    import pcerecomp.cue
    if Path(pcerecomp.cue.__file__).resolve()!=tool/'pcerecomp/cue.py':raise ValueError('Wrong selected Python package')
    sources=[Path(__file__),ROOT/'tests/test_cue_gap_reference.py',ROOT/'tests/beetle_cue_probe.cpp',ROOT/'tests/geargrafx_cue_gap_probe.cpp',ROOT/'tests/cue_gap_tests.cpp',
             ROOT/'tests/cue_fixture.py',ROOT/'tests/hucard_fixture.py',ROOT/'scripts/beetle_reference.py',ROOT/'scripts/cue_reference.py',
             ROOT/'scripts/mapper_reference.py',ROOT/'scripts/hucard_reference.py',ROOT/'scripts/filtered_audio_reference.py',ROOT/'scripts/psg_reference.py',
             tool/'CMakeLists.txt',*sorted((tool/'runtime').rglob('*.cpp')),*sorted((tool/'runtime').rglob('*.hpp')),*sorted((tool/'pcerecomp').glob('*.py')),*sorted((tool/'cmake').glob('*.cmake'))]
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources={str(p.resolve()):sha(p) for p in sources})
    report=dict(schema=1,result='incomplete',bindings=bindings,commands=[],cases=[],beetle_revision=beetle.PIN,gear_revision=gear.COMMIT,
                scope='Authored provider/media proof: actual POSTGAP CUE through original Beetle; explicitly transformed equivalent-PREGAP Gear fixtures; independent complete payload/sample literals and toolkit playback-cache gap silence',
                not_checked=['CPU execution','Drive/seek timing','Subchannel Q/indices beyond01','EDC/ECC validity','Retail media','Hardware','Direct Gear parsing of CUE POSTGAP','Full-engine PCM scheduler'])
    out.mkdir(parents=True)
    try:
        original_beetle=build_beetle(args,out,report,bindings,compiler);original_gear=build_gear(args,out,report,bindings,compiler);probe=build_tool(args,out,report,bindings,compiler)
        bindings['authored_fixtures']={};all_actual=[];all_wanted=[]
        for case in definitions():
            directory=out/case['id'];cue=write_case(directory,case);requests={tier:operations(case,tier) for tier in ('tool','beetle')}
            bindings['authored_fixtures'].update({str(p):sha(p) for p in directory.rglob('*') if p.is_file()})
            if case['gear_cue'] is not None:requests['gear']=operations(case,'gear')
            image=Cue(cue);identity=composite_identity(cue,case)
            if image.image_sha256()!=identity or image.leadout_lba!=case['leadout'] or [[t.disc_start,0 if t.type=='AUDIO' else 4] for t in image.tracks]!=case['tracks']:
                raise ValueError('Python geometry or independent complete-image identity differs')
            python_checks=0
            for row in expected(case,requests['tool']):
                if row['kind']=='toc':continue
                lba=row['lba'];kind=row['kind']
                if kind=='playable':validate(image.audio_playable(lba),row['value']);python_checks+=1
                elif kind in ('data','audio'):
                    try:value=image.read(lba).hex() if kind=='data' else list(image.read_audio(lba))
                    except Exception as error:
                        from pcerecomp.media import MediaError
                        if not isinstance(error,MediaError) or row['ok']:raise
                        python_checks+=1
                    else:
                        if not row['ok']:raise ValueError('Python accepted unavailable raw payload')
                        python_checks+=validate(value,row.get('bytes',row.get('samples')))
            row=dict(id=case['id'],python_literal_checks=python_checks,identity=identity,tiers={})
            for tier,ops in requests.items():
                plan=directory/(tier+'.plan');plan_file(plan,ops);wanted=expected(case,ops,tier)
                expectation=directory/(tier+'-literal.json');expectation.write_text(json.dumps(wanted)+'\n',encoding='utf-8')
                if tier=='gear':
                    selected=directory/'gear-equivalent-pregap.cue';selected.write_text(case['gear_cue'],encoding='ascii')
                    command=[str(original_gear),str(selected),str(plan)]
                elif tier=='beetle':command=[str(original_beetle),str(cue),str(plan)]
                else:command=[str(probe),'--probe',str(cue),str(plan)]
                for p in (plan,expectation,Path(command[1]) if tier=='gear' else cue):bindings['authored_fixtures'][str(p)]=sha(p)
                result=common.evidence(command,case['id']+'-'+tier,out,report,bindings,60)
                actual=read_rows(result.stdout);checks=validate(actual,wanted)
                if tier=='tool':all_actual+=actual;all_wanted+=wanted
                row['tiers'][tier]=dict(observations=len(actual),literal_checks=checks,scope='direct original POSTGAP raw media' if tier=='beetle' else 'equivalent-PREGAP transformed input; trailing POSTGAP excluded' if tier=='gear' else 'actual provider and playback cache')
            bindings['authored_fixtures'].update({str(p):sha(p) for p in directory.rglob('*') if p.is_file()})
            if image.image_sha256()!=identity:raise ValueError('Authored input changed during comparison')
            report['cases'].append(row)
        controls=negative_controls(all_actual,all_wanted)
        control_path=out/'negative-controls.json';control_path.write_text(json.dumps(dict(schema=1,passed=True,controls=controls,scope='In-memory mutations of actual observed toolkit rows; no media/source mutation or new runtime execution'),indent=2)+'\n',encoding='utf-8')
        bindings['raw_outputs'][str(control_path)]=sha(control_path)
        report.update(result='pass',tool=source_identity(tool),cases_verified=len(report['cases']),negative_controls=len(controls),native_execution_claim=False)
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:
        gear.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if report['result']!='pass':raise ValueError('Bound proof input changed')
    print(json.dumps({k:v for k,v in report.items() if k not in ('bindings','commands')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--beetle-source',type=Path,required=True);parser.add_argument('--gear-source',type=Path,required=True)
    parser.add_argument('--tool-source',type=Path,default=ROOT);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--compiler',default='clang++');parser.add_argument('--cmake',default='cmake');parser.add_argument('--ninja',default='ninja')
    try:run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:print(error,file=sys.stderr);raise SystemExit(1)
