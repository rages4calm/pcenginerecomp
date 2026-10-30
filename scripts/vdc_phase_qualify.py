"""Strict rehash and semantic/source/counter joins; never execute a guest."""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from scripts.vdc_phase_reference import COMMIT,ABI,sha,sources,require,cases,program,validate_report,validate_capture,validate_hits,raw_differences,fixtures,ref,requested_tier
from pcerecomp.project import source_identity
BUILDS={'gear-link','tool-configure','tool-build'}
GROUPS={'tools','authored_sources','reference_raw_sources','reference_compile_sources','external_libraries','gear_objects','gear_compile_logs','gear_binary','tool_build_inputs','tool_objects','tool_binary','fixtures','raw_outputs'}
def load(path):
    def unique(rows):
        result={}
        for k,v in rows:
            if k in result:raise ValueError('Duplicate evidence key')
            result[k]=v
        return result
    def constant(value):raise ValueError('Nonfinite evidence')
    return json.loads(Path(path).read_text(),object_pairs_hook=unique,parse_constant=constant,parse_float=constant)
def validate_stderr(label,text):require(label in BUILDS or text=='','Unexpected actual guest stderr: '+label)

def validate_original_sources(bindings,required,raw_root,pinned):
    for group,root in(('reference_raw_sources',Path(raw_root)),('reference_compile_sources',Path(pinned))):
        require(set(bindings[group])=={str(root/name)for name in required},'Complete original raw/compiled source binding set differs')
        for name,digest in required.items():
            path=root/name;raw=path.read_bytes();data=raw.replace(b'\r\n',b'\n')if group=='reference_raw_sources'else raw;require(sha(path)==bindings[group][str(path)]and hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==digest,'Original raw/compiled source SHA/Git blob differs')
def qualify(path):
    path=Path(path).resolve();out=path.parent;r=load(path)
    fields={'schema','result','oracle_commit','tool','tool_root','commands','bindings','rows','scope','not_checked','gear_git_blobs','recipes','cases','preservation','processes','compilations'}
    require(type(r)is dict and set(r)==fields and type(r['schema'])is int and r['schema']==1 and r['result']=='pass'and r['oracle_commit']==COMMIT,'Exact reference receipt/schema required')
    require(type(r['recipes'])is int and r['recipes']==48 and type(r['cases'])is int and r['cases']==48,'Exact authored recipe/cut extent required')
    require(type(r['bindings'])is dict and set(r['bindings'])==GROUPS and type(r['preservation'])is dict and set(r['preservation'])==GROUPS and all(v is True for v in r['preservation'].values()),'Complete preserved binding groups required');b=r['bindings'];count=0
    for group,table in b.items():
        require(type(table)is dict and bool(table),'Nonempty artifact binding group required')
        for name,digest in table.items():require(type(name)is str and Path(name).is_absolute()and type(digest)is str and sha(name)==digest,'Changed bound artifact: '+str(name));count+=1
    tool=Path(r['tool_root']);require(r['tool']==source_identity(tool)and b['authored_sources']==sources(tool),'Exact toolkit identity/authored source bindings differ')
    checkouts={str(Path(name).resolve().parents[1])for name in b['reference_raw_sources']if name.replace('\\','/').endswith('/src/input.h')};require(len(checkouts)==1,'Original checkout identity differs')
    tree=subprocess.check_output(['git','-C',next(iter(checkouts)),'ls-tree','-r',COMMIT],text=True).splitlines();originals={line.split('\t',1)[1]:line.split()[2]for line in tree};prefixes=('src/','platforms/shared/dependencies/miniz/','platforms/shared/dependencies/minivorbis/','platforms/shared/dependencies/qon/','platforms/shared/dependencies/json/','platforms/shared/dependencies/libchdr/include/');required={name:digest for name,digest in originals.items()if name.startswith(prefixes)and Path(name).suffix in('.c','.cpp','.h','.hpp')}
    require(r['gear_git_blobs']==required,'Complete original Git blob set differs');pinned=out/'pinned-reference-source';validate_original_sources(b,required,next(iter(checkouts)),pinned)
    fixture_names=[c['id']+'.pce'for c in cases()]+['fixture/module.cpp','fixture/module.json','fixture/fixture.json','fixture/vdc_phase_fixture.hpp']
    require(set(b['fixtures'])=={str(out/name)for name in fixture_names},'Complete authored/generated fixture binding set differs')
    with tempfile.TemporaryDirectory(prefix='pce-vdc-phase-reemit-')as folder:
        expected_root=Path(folder);fixtures(expected_root)
        require(all((expected_root/name).read_bytes()==(out/name).read_bytes()for name in fixture_names),'Independently reauthored ROM/data/CUE/header/static translation differs')
    expected=[dict(case=c,tier=tier,label=c['id']+'-'+tier)for c in cases()for tier in('gear','native','interpreter')]
    require(json.dumps(r['rows'],sort_keys=True)==json.dumps(expected,sort_keys=True),'Complete actual recipe/tier/process matrix differs')
    labels=list(BUILDS)+[row['label']for row in expected]
    require(type(r['processes'])is list and all(type(p)is dict and set(p)=={'label','returncode'}and type(p['label'])is str and type(p['returncode'])is int for p in r['processes']),'Strict actual process metadata required');require(sorted(r['processes'],key=lambda p:p['label'])==sorted([dict(label=l,returncode=0)for l in labels],key=lambda p:p['label']),'Actual successful process set differs')
    require(type(r['commands'])is list and len(r['commands'])>=3 and all(type(c)is list and bool(c)and all(type(v)is str for v in c)for c in r['commands']),'Strict actual commands required')
    raw={str(out/(label+'.'+suffix))for label in labels for suffix in('stdout','stderr')}
    for row in expected:
        if row['tier']!='gear':raw.add(str(out/(row['label']+'-capture.json')))
    require(set(b['raw_outputs'])==raw,'Complete raw stdout/stderr/capture/checkpoint set differs')
    for label in labels:validate_stderr(label,(out/(label+'.stderr')).read_text())
    binary=str(out/'tool-build'/('vdc-phase.exe'if sys.platform=='win32'else'vdc-phase'));gear_binary=str(out/'gear-vdc-phase.exe');require(set(b['tool_binary'])=={binary}and set(b['gear_binary'])=={gear_binary},'Exact build/output binary associations required');wanted_commands=[]
    compiler=r['commands'][0][0];require(compiler in b['tools'],'Actual compiler binding missing');cpp,c=ref.compile_sources(pinned,{name:sha(pinned/name)for name in required});cpp.append(ROOT/'tests/geargrafx_vdc_phase_probe.cpp');deps=pinned/'platforms/shared/dependencies';flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for p in(pinned/'src',ROOT/'tests',out/'fixture',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(p)]
    compile_commands=[];objects=[];compilations=[]
    for index,p in enumerate(cpp+c):
        obj=out/'gear-objects'/(str(index)+'-'+p.stem+'.o');objects.append(obj);compile_commands.append([compiler,*flags,'-x','c++'if p.suffix=='.cpp'else'c',*(['-std=c++20','-include','cerrno']if p.suffix=='.cpp'else['-std=c11']),'-c',str(p),'-o',str(obj)]);compilations.append(dict(object=str(obj),log=str(obj.with_suffix('.log')),returncode=0))
    require(type(r['compilations'])is list and all(type(v)is dict and set(v)=={'object','log','returncode'}and type(v['object'])is str and type(v['log'])is str and type(v['returncode'])is int for v in r['compilations']),'Actual original compilation process records required');require(sorted(r['compilations'],key=lambda v:v['object'])==sorted(compilations,key=lambda v:v['object']),'Original compile process/object/log/success extent differs')
    require(set(b['gear_objects'])=={str(p)for p in objects}and set(b['gear_compile_logs'])=={str(p.with_suffix('.log'))for p in objects},'Complete original object/diagnostic bindings differ')
    gear_link=[compiler,*map(str,objects),*b['external_libraries'],'-Wl,--gc-sections','-o',gear_binary]
    cmakes=[p for p in b['tools']if Path(p).stem.lower()=='cmake'];ninjas=[p for p in b['tools']if Path(p).stem.lower()=='ninja'];require(len(cmakes)==len(ninjas)==1,'Exact CMake/Ninja bindings required');cmake,ninja=cmakes[0],ninjas[0]
    configure=[cmake,'-S',str(out/'wrapper'),'-B',str(out/'tool-build'),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+compiler,'-DCMAKE_MAKE_PROGRAM='+ninja];build=[cmake,'--build',str(out/'tool-build'),'--target','vdc-phase','--parallel','4']
    require(r['commands'][:len(compile_commands)+3]==compile_commands+[gear_link,configure,build],'Complete actual compile/link/configure/build command association differs')
    from scripts.mapper_reference import cmake_quote as q
    config=out/'wrapper/CMakeLists.txt';fixture=out/'fixture';lines=['cmake_minimum_required(VERSION 3.20)','project(VdcPhase LANGUAGES CXX)',*['set('+v+' OFF CACHE BOOL "" FORCE)'for v in('BUILD_TESTING','PCE_BUILD_TESTS','PCE_BUILD_TOOLS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE')],f'add_subdirectory({q(tool)} tool)',f'pce_add_native_module(_module MODULE {q(fixture/"module.cpp")} MANIFEST {q(fixture/"module.json")})',f'add_executable(vdc-phase {q(ROOT/"tests/vdc_phase_probe.cpp")})',f'target_include_directories(vdc-phase PRIVATE {q(fixture)} {q(ROOT/"tests")})','target_link_libraries(vdc-phase PRIVATE ${_module} pce-runtime)']
    require(set(b['tools'])=={compiler,cmake,ninja}and set(b['tool_build_inputs'])=={str(config)}and config.read_text()=='\n'.join(lines)+'\n','Exact build tools/configured source/module/probe inputs differ')
    built={str(p)for p in(out/'tool-build').rglob('*')if p.is_file()and(p.suffix in('.o','.obj','.a')or p.name in('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))};require(set(b['tool_objects'])==built,'Complete toolkit object/build-input set differs')
    checks=joins=native=interpreted=original_calls=original_instructions=original_clocks=0;differences=[];observed=set();admissions=[];phase_work=Counter()
    for case in cases():
        by_tier={}
        for tier in('gear','native','interpreter'):
            label=case['id']+'-'+tier;actual=load(out/(label+'.stdout'));requested_tier(actual,tier);hits=None
            if tier=='gear':wanted_commands.append([gear_binary,case['id'],str(out/(case['id']+'.pce'))])
            else:
                capture=out/(label+'-capture.json');wanted_commands.append([binary,case['id'],str(out/(case['id']+'.pce')),tier,str(capture)]);hits=validate_capture(load(capture),case,tier)
                if tier=='native':native+=actual['instructions'];observed.update(hits)
                else:interpreted+=actual['instructions']
            admission=validate_report(actual,case,hits);admissions.append(dict(case=case['id'],tier=tier,**admission));joins+=1;checks+=8192+32768+35
            for key in('instructions','calls','clock_calls','blocks','block_bytes','wait_ticks'):phase_work[tier+'_'+key]+=actual[key]
            if tier=='gear':original_calls+=actual['calls'];original_instructions+=actual['instructions'];original_clocks+=actual['clock_calls']
            by_tier[tier]=actual
        a,both=by_tier['native'],by_tier['interpreter'];require(all(a[k]==both[k]for k in a if k!='tier'),'Internal native/interpreter source/CPU/phase/fullmemory differs')
        original=by_tier['gear'];require(all(original[k]==a[k]for k in('wram','vram','blocks','block_bytes','instructions')),'Independent original CPU source-count/fullmemory endpoint differs');require(original['final_cpu'][:7]==a['final_cpu'][:7]and original['final_cpu'][8:]==a['final_cpu'][8:],'Independent original final logical CPU differs');differences+=raw_differences(original,a,case)
    require(sum(a['hsw_excluded']for a in admissions)==138 and sum(not a['hsw_excluded']for a in admissions)==6,'Exact46predicted/2off-profile recipe admission differs')
    require(r['commands']==compile_commands+[gear_link,configure,build]+wanted_commands,'Complete actual build/guest command ledger differs')
    manifest=load(out/'fixture/module.json');plan=load(out/'fixture/fixture.json');require(plan['execution_evidence']is False,'Compilation source plan promoted to execution evidence');require(manifest['unsupported_observations']==0,'Authored opcode emission unsupported')
    return dict(result='pass',recipes=48,cases=48,actual_guest_processes=144,predicted_recipes=46,predictions=138,hsw_control_recipes=2,explicit_model_refusals=6,native_steps=native,interpreter_steps=interpreted,gear_guest_cpu_calls=original_calls,gear_retired_instructions=original_instructions,gear_extra_continuation_calls=original_calls-original_instructions,gear_hardware_callbacks=original_clocks,admitted_values=checks,independent_wram_values=8192*joins,independent_vram_words=32768*joins,semantic_reports=joins,phase_work=dict(phase_work),artifact_bindings=count,original_git_blobs=len(required),execution_joins=joins,compilation_joins=len(compilations),compiled_sources=manifest['native_instructions_emitted'],actual_native_sources=len(observed),raw_difference_cases=len({row['case']for row in differences}),raw_differences=differences,admissions=admissions,tool=r['tool'])


def negative_controls(path):
    r=load(path);out=Path(path).parent;mutations=[('result',lambda x:x.update(result='incomplete')),('fixture-missing',lambda x:x['bindings']['fixtures'].pop(next(iter(x['bindings']['fixtures'])))),('matrix-missing',lambda x:x['rows'].pop()),('build-command-missing',lambda x:x['commands'].pop(len(x['compilations'])+2)),('process-missing',lambda x:x['processes'].pop()),('process-code-bool',lambda x:x['processes'][0].update(returncode=False)),('identity',lambda x:x['tool'].update(runtime_abi=999)),('binding-missing',lambda x:x['bindings']['raw_outputs'].pop(next(iter(x['bindings']['raw_outputs'])))),('binding-change',lambda x:x['bindings']['tools'].update({next(iter(x['bindings']['tools'])):'0'*64})),('oracle-blob',lambda x:x['gear_git_blobs'].update({next(iter(x['gear_git_blobs'])):'0'*40}))];refused=[]
    for name,change in mutations:
        altered=copy.deepcopy(r);change(altered);target=out/('negative-'+name+'.json');require(not target.exists(),'New negative receipt required');target.write_text(json.dumps(altered)+'\n')
        try:qualify(target)
        except(ValueError,OSError,KeyError):refused.append(name)
        else:raise ValueError('Altered receipt admitted: '+name)
    return refused

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('result',type=Path);p.add_argument('--negative-controls',action='store_true');args=p.parse_args()
    try:
        result=qualify(args.result)
        if args.negative_controls:result['negative_controls_refused']=negative_controls(args.result)
        print(json.dumps(result,indent=2))
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:print(error,file=sys.stderr);raise SystemExit(1)
