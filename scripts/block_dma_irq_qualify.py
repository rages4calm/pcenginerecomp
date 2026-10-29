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
from scripts.block_dma_irq_reference import COMMIT,ABI,sha,sources,require,cases,program,validate_report,validate_capture,validate_hits,raw_differences,fixtures,ref,requested_tier
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
    return json.loads(Path(path).read_text(),object_pairs_hook=unique,parse_constant=constant)
def validate_stderr(label,text):require(label in BUILDS or text=='','Unexpected actual guest stderr: '+label)
def full_hits(prefix,window,case):
    a=Counter(validate_hits(prefix,case));a.update(validate_hits(window,case));_,markers,plan=program(case)
    for row in plan:
        pc=row['pc'];key=pc,tuple(row['mpr']),tuple(row['physical']),tuple(row['data']);n=a.get(key,0)
        if pc==markers['done']:require(n==0,'Compiled terminal BRA falsely counted as executed')
        elif pc>=0xf800:require(n==int(case['kind']=='enabled'),'Actual handler source extent differs')
        elif pc in(markers['block'],markers['block']+7,markers['block']+8):require(n==case['loops'],'Actual finite block/DEX/BNE loop extent differs')
        elif row['data'][0]in(0xad,0x29,0xc9,0xd0):require(n>0,'Required actual guest polling source missing')
        else:require(n==1,'Required actual one-shot setup/command/ACK source differs')
    for op,port,wanted in((0x8d,0x1801,6),(0xad,0x1801,2),(0x8d,0x180b,3),(0xad,0x180b,1),(0x8d,0x180d,4)):
        require(sum(n for (_,_,_,raw),n in a.items()if list(raw)==[op,port&255,port>>8])==wanted,'Autonomous actual protocol/mode1-control stores/reads differ')
    return a

def qualify(path):
    path=Path(path).resolve();out=path.parent;r=load(path)
    fields={'schema','result','oracle_commit','tool','tool_root','commands','bindings','rows','scope','not_checked','gear_git_blobs','recipes','cases','preservation','processes','compilations'}
    require(type(r)is dict and set(r)==fields and type(r['schema'])is int and r['schema']==1 and r['result']=='pass'and r['oracle_commit']==COMMIT,'Exact reference receipt/schema required')
    require(type(r['recipes'])is int and r['recipes']==20 and type(r['cases'])is int and r['cases']==40,'Exact authored recipe/cut extent required')
    require(type(r['bindings'])is dict and set(r['bindings'])==GROUPS and type(r['preservation'])is dict and set(r['preservation'])==GROUPS and all(v is True for v in r['preservation'].values()),'Complete preserved binding groups required');b=r['bindings'];count=0
    for group,table in b.items():
        require(type(table)is dict and bool(table),'Nonempty artifact binding group required')
        for name,digest in table.items():require(type(name)is str and Path(name).is_absolute()and type(digest)is str and sha(name)==digest,'Changed bound artifact: '+str(name));count+=1
    tool=Path(r['tool_root']);require(r['tool']==source_identity(tool)and b['authored_sources']==sources(tool),'Exact toolkit identity/authored source bindings differ')
    checkouts={str(Path(name).resolve().parents[1])for name in b['reference_raw_sources']if name.replace('\\','/').endswith('/src/input.h')};require(len(checkouts)==1,'Original checkout identity differs')
    tree=subprocess.check_output(['git','-C',next(iter(checkouts)),'ls-tree','-r',COMMIT],text=True).splitlines();originals={line.split('\t',1)[1]:line.split()[2]for line in tree};prefixes=('src/','platforms/shared/dependencies/miniz/','platforms/shared/dependencies/minivorbis/','platforms/shared/dependencies/qon/','platforms/shared/dependencies/json/','platforms/shared/dependencies/libchdr/include/');required={name:digest for name,digest in originals.items()if name.startswith(prefixes)and Path(name).suffix in('.c','.cpp','.h','.hpp')}
    require(r['gear_git_blobs']==required,'Complete original Git blob set differs');pinned=out/'pinned-reference-source';require(set(b['reference_compile_sources'])=={str(pinned/name)for name in required},'Complete original compile-source set differs')
    for name,digest in required.items():
        data=(pinned/name).read_bytes();require(hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==digest,'Original compiled Git blob differs')
    fixture_names=[c['id']+'.pce'for c in cases()]+['data.bin','data.cue','fixture/module.cpp','fixture/module.json','fixture/fixture.json','fixture/block_dma_irq_fixture.hpp']
    require(set(b['fixtures'])=={str(out/name)for name in fixture_names},'Complete authored/generated fixture binding set differs')
    with tempfile.TemporaryDirectory(prefix='pce-block-dma-irq-reemit-')as folder:
        expected_root=Path(folder);fixtures(expected_root)
        require(all((expected_root/name).read_bytes()==(out/name).read_bytes()for name in fixture_names),'Independently reauthored ROM/data/CUE/header/static translation differs')
    expected=[dict(case=c,cut=cut,tier=tier,mode=mode,label=c['id']+'-cut'+str(cut)+'-'+tier+'-'+mode)for c in cases()for cut in(0,1)for tier in('native','interpreter')for mode in('write','resume')]
    require(json.dumps(r['rows'],sort_keys=True)==json.dumps(expected,sort_keys=True),'Complete actual case/tier/process matrix differs')
    labels=list(BUILDS)+[c['id']+'-cut'+str(cut)+'-gear'for c in cases()for cut in(0,1)]+[row['label']for row in expected]
    require(type(r['processes'])is list and all(type(p)is dict and set(p)=={'label','returncode'}and type(p['label'])is str and type(p['returncode'])is int for p in r['processes']),'Strict actual process metadata required');require(sorted(r['processes'],key=lambda p:p['label'])==sorted([dict(label=l,returncode=0)for l in labels],key=lambda p:p['label']),'Actual successful process set differs')
    require(type(r['commands'])is list and len(r['commands'])>=3 and all(type(c)is list and bool(c)and all(type(v)is str for v in c)for c in r['commands']),'Strict actual commands required')
    raw={str(out/(label+'.'+suffix))for label in labels for suffix in('stdout','stderr')}
    for row in expected:
        raw.add(str(out/(row['label']+'-capture.json')))
        if row['mode']=='write':raw.update({str(out/(row['label']+'-capture.json.prefix.json')),str(out/(row['case']['id']+'-cut'+str(row['cut'])+'-'+row['tier']+'.pcec'))})
    require(set(b['raw_outputs'])==raw,'Complete raw stdout/stderr/capture/checkpoint set differs')
    for label in labels:validate_stderr(label,(out/(label+'.stderr')).read_text())
    binary=str(out/'tool-build'/('block-dma-irq.exe'if sys.platform=='win32'else'block-dma-irq'));gear_binary=str(out/'gear-block-dma-irq.exe');require(set(b['tool_binary'])=={binary}and set(b['gear_binary'])=={gear_binary},'Exact build/output binary associations required');wanted_commands=[]
    compiler=r['commands'][0][0];require(compiler in b['tools'],'Actual compiler binding missing');cpp,c=ref.compile_sources(pinned,{name:sha(pinned/name)for name in required});cpp.append(ROOT/'tests/geargrafx_block_dma_irq_probe.cpp');deps=pinned/'platforms/shared/dependencies';flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for p in(pinned/'src',ROOT/'tests',out/'fixture',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(p)]
    compile_commands=[];objects=[];compilations=[]
    for index,p in enumerate(cpp+c):
        obj=out/'gear-objects'/(str(index)+'-'+p.stem+'.o');objects.append(obj);compile_commands.append([compiler,*flags,'-x','c++'if p.suffix=='.cpp'else'c',*(['-std=c++20','-include','cerrno']if p.suffix=='.cpp'else['-std=c11']),'-c',str(p),'-o',str(obj)]);compilations.append(dict(object=str(obj),log=str(obj.with_suffix('.log')),returncode=0))
    require(type(r['compilations'])is list and all(type(v)is dict and set(v)=={'object','log','returncode'}and type(v['object'])is str and type(v['log'])is str and type(v['returncode'])is int for v in r['compilations']),'Actual original compilation process records required');require(sorted(r['compilations'],key=lambda v:v['object'])==sorted(compilations,key=lambda v:v['object']),'Original compile process/object/log/success extent differs')
    require(set(b['gear_objects'])=={str(p)for p in objects}and set(b['gear_compile_logs'])=={str(p.with_suffix('.log'))for p in objects},'Complete original object/diagnostic bindings differ')
    gear_link=[compiler,*map(str,objects),*b['external_libraries'],'-Wl,--gc-sections','-o',gear_binary]
    cmakes=[p for p in b['tools']if Path(p).stem.lower()=='cmake'];ninjas=[p for p in b['tools']if Path(p).stem.lower()=='ninja'];require(len(cmakes)==len(ninjas)==1,'Exact CMake/Ninja bindings required');cmake,ninja=cmakes[0],ninjas[0]
    configure=[cmake,'-S',str(out/'wrapper'),'-B',str(out/'tool-build'),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+compiler,'-DCMAKE_MAKE_PROGRAM='+ninja];build=[cmake,'--build',str(out/'tool-build'),'--target','block-dma-irq','--parallel','4']
    require(r['commands'][:len(compile_commands)+3]==compile_commands+[gear_link,configure,build],'Complete actual compile/link/configure/build command association differs')
    from scripts.mapper_reference import cmake_quote as q
    config=out/'wrapper/CMakeLists.txt';fixture=out/'fixture';lines=['cmake_minimum_required(VERSION 3.20)','project(BlockDmaIrq LANGUAGES CXX)',*['set('+v+' OFF CACHE BOOL "" FORCE)'for v in('BUILD_TESTING','PCE_BUILD_TESTS','PCE_BUILD_TOOLS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE')],f'add_subdirectory({q(tool)} tool)',f'pce_add_native_module(_module MODULE {q(fixture/"module.cpp")} MANIFEST {q(fixture/"module.json")})',f'add_executable(block-dma-irq {q(ROOT/"tests/block_dma_irq_probe.cpp")})',f'target_include_directories(block-dma-irq PRIVATE {q(fixture)} {q(ROOT/"tests")})','target_link_libraries(block-dma-irq PRIVATE ${_module} pce-runtime)']
    require(set(b['tools'])=={compiler,cmake,ninja}and set(b['tool_build_inputs'])=={str(config)}and config.read_text()=='\n'.join(lines)+'\n','Exact build tools/configured source/module/probe inputs differ')
    built={str(p)for p in(out/'tool-build').rglob('*')if p.is_file()and(p.suffix in('.o','.obj','.a')or p.name in('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))};require(set(b['tool_objects'])==built,'Complete toolkit object/build-input set differs')
    checks=joins=native=interpreted=original_calls=original_instructions=original_clocks=0;differences=[];observed=set();actual_rows={};phase_work=Counter()
    for case in cases():
        for cut in(0,1):
            stem=case['id']+'-cut'+str(cut);arguments=[case['id'],str(out/(case['id']+'.pce')),str(out/'data.cue'),str(cut)];gear=load(out/(stem+'-gear.stdout'));checks+=validate_report(gear,case,cut,gear=True);full_hits(gear['prefix_hits'],gear['window_hits'],case);joins+=1;original_calls+=gear['prefix_work']['calls']+gear['window_work']['calls'];original_instructions+=gear['prefix_work']['instructions']+gear['window_work']['instructions'];original_clocks+=gear['prefix_work']['clock_calls']+gear['window_work']['clock_calls'];wanted_commands.append([gear_binary,*arguments])
            for phase in('prefix','window'):
                for field,value in gear[phase+'_work'].items():phase_work['gear_'+phase+'_'+field]+=value
            pair_by_tier={}
            for tier in('native','interpreter'):
                pair=[];checkpoint=out/(stem+'-'+tier+'.pcec')
                for mode in('write','resume'):
                    label=stem+'-'+tier+'-'+mode;capture=out/(label+'-capture.json');a=load(out/(label+'.stdout'));requested_tier(a,tier);checks+=validate_report(a,case,cut,resume=mode=='resume');validate_capture(load(capture),a,case,resume=mode=='resume');require(a['checkpoint_sha256']==sha(checkpoint),'Checkpoint raw byte hash association differs');wanted_commands.append([binary,*arguments,mode,tier,str(checkpoint),str(capture)]);joins+=1
                    if mode=='write':validate_capture(load(str(capture)+'.prefix.json'),a,case,prefix=True);observed.update(full_hits(a['prefix_hits'],a['window_hits'],case))
                    work=a['window_work']['instructions']+(a['prefix_work']['instructions']if mode=='write'else 0)
                    if tier=='native':native+=work
                    else:interpreted+=work
                    if mode=='write':phase_work[tier+'_creating_prefix']+=a['prefix_work']['instructions'];phase_work[tier+'_creating_prefix_blocks']+=a['prefix_work']['blocks'];phase_work[tier+'_creating_prefix_block_bytes']+=a['prefix_work']['block_bytes']
                    phase_work[tier+('_creating_suffix'if mode=='write'else'_restored_suffix')]+=a['window_work']['instructions'];phase_work[tier+('_creating_suffix_blocks'if mode=='write'else'_restored_suffix_blocks')]+=a['window_work']['blocks'];phase_work[tier+('_creating_suffix_block_bytes'if mode=='write'else'_restored_suffix_block_bytes')]+=a['window_work']['block_bytes']
                    pair.append(a);actual_rows[label]=a
                keys={'dma_counter_role','case','cut_id','tier','cut','final','window_work','window_hits','journal','ram','prefix_native','prefix_interpreted','window_native','window_interpreted','origin_frame','checkpoint_sha256','final_sha256','prefix_blocks','prefix_block_bytes'};require(all(pair[0][k]==pair[1][k]for k in keys),'Fresh exact same-tier state/hash/source/journal continuation differs');require(pair[1]['prefix_work']['instructions']==0 and not pair[1]['prefix_hits'],'Restoring process replayed primer');pair_by_tier[tier]=pair[0]
            a,both=pair_by_tier['native'],pair_by_tier['interpreter']
            require(all(a[k]==both[k]for k in('cut','final','window_work','prefix_work','window_hits','prefix_hits','journal','prefix_journal','ram')),'Internal separately interpreted/native continuation differs');differences+=raw_differences(gear,a,case,cut)
    require(r['commands']==compile_commands+[gear_link,configure,build]+wanted_commands,'Complete actual build/guest command ledger differs')
    manifest=load(out/'fixture/module.json');plan=load(out/'fixture/fixture.json');require(plan['execution_evidence']is False,'Compilation source plan promoted to execution evidence');require(manifest['unsupported_observations']==0,'Authored opcode emission unsupported')
    return dict(result='pass',recipes=20,cases=40,fresh_restores=80,native_steps=native,interpreter_steps=interpreted,gear_guest_cpu_calls=original_calls,gear_retired_instructions=original_instructions,gear_extra_continuation_calls=original_calls-original_instructions,gear_hardware_callbacks=original_clocks,admitted_values=checks,independent_adpcm_ram_values=65536*joins,independent_wram_values=8192*joins,semantic_reports=joins,phase_work=dict(phase_work),artifact_bindings=count,original_git_blobs=len(required),execution_joins=joins,compilation_joins=len(compilations),compiled_sources=manifest['native_instructions_emitted'],actual_native_sources=len(observed),raw_difference_cases=len({(row['case'],row['cut'])for row in differences}),raw_difference_fields=dict(Counter(row['phase']+'.'+str(row['field'])for row in differences)),raw_differences=differences,tool=r['tool'])

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
