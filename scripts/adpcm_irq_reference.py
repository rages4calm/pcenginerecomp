"""Guest-created ADPCM HALF/END CPU IRQ checks against original Geargrafx."""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from scripts import mapper_reference as infra,filtered_audio_reference as ref,hucard_reference as common
from generate_adpcm_irq_fixture import generate,make_program,COLUMNS,STEPS
sha=ref.sha


def require(ok,message):
    if not ok:raise ValueError(message)


def key(row):return row['pc'],tuple(row['mpr']),tuple(row['physical']),tuple(row['data'])


def primer_clocks(case,gear):
    """Independent authored prefix timing, retaining the original CSH difference."""
    _,_,sources,_,_,_=make_program(case)
    divisor=12;result=[]
    for source in sources:
        raw=source['data'];opcode=raw[0]
        if opcode==0xD4:
            result.append((9 if gear else 27,3));divisor=3;continue
        cycles={0x78:2,0xA9:2,0x53:5,0xA2:2,0x9A:2,0x82:2,0x8D:5,0xAD:5}.get(opcode)
        if opcode==0x73:
            length=raw[5]|raw[6]<<8;cycles=17+6*(length or 65536)
        if opcode in(0x8D,0xAD)and(raw[1]|raw[2]<<8)<0x400:cycles+=1
        require(cycles is not None,'Unauthored prefix clock operation')
        result.append((cycles*divisor,divisor))
    return result


def row(actual,wanted):
    require(type(actual)is dict and set(actual)=={'values','wram_sha256','irq_vector'},'Strict ADPCM row fields required')
    require(type(actual['values'])is list and len(actual['values'])==len(COLUMNS) and all(type(v)is int and 0<=v<2**64 for v in actual['values']),'Typed ADPCM row extent required')
    require(type(actual['irq_vector'])is int and actual['irq_vector']==wanted['irq_vector'],'Actual IRQ vector differs')
    require(actual['values']==wanted['values'] and actual['wram_sha256']==wanted['wram_sha256'],'Independent ADPCM CPU/device/WRAM literal differs')


def qualify_execution(case,outputs,captures,abi):
    total=case['primer_steps']+case['steps'];sources={key(r):r['hits']for r in case['source_hits']}
    require(sum(sources.values())==total,'Independent source ledger extent differs')
    for tier in ('native','interpreter','gear'):
        actual=outputs[tier]
        fields={'case','tier','origin_ticks','initial','rows','block_steps'}|({'original_instructions'}if tier=='gear'else{'native','interpreted','guards'})
        require(type(actual)is dict and set(actual)==fields and actual['case']==case['id'] and actual['tier']==tier,'Strict actual execution report required')
        require(type(actual['origin_ticks'])is int and actual['origin_ticks']==sum(t for t,_ in primer_clocks(case,tier=='gear')),'Independent raw primer clock origin differs')
        require(type(actual['block_steps'])is int and actual['block_steps']==case['block_steps'],'Actual block count differs')
        row(actual['initial'],case['initial'])
        require(type(actual['rows'])is list and len(actual['rows'])==STEPS,'Exact actual measured extent required')
        for a,b in zip(actual['rows'],case['expected']):row(a,b)
        if tier=='gear':require(type(actual['original_instructions'])is int and actual['original_instructions']==total,'Original opcode count differs')
        else:
            require(all(type(actual[k])is int for k in ('native','interpreted','guards')),'Typed work required')
            require((actual['native'],actual['interpreted'],actual['guards'])==((total,0,4)if tier=='native'else(0,total,0)),'Actual tier/guard work differs')
            from pcerecomp.capture import validate_capture
            cap=captures[tier];validate_capture(cap)
            require(cap['runtime_abi']==abi and cap['complete'] and not cap['dropped_instructions'] and not cap['unreadable_instructions'] and cap['retired_instructions']==total,'Actual current complete capture required')
            selected='native_hits'if tier=='native'else'interpreted_hits';other='interpreted_hits'if tier=='native'else'native_hits'
            require(not any(r[other]for r in cap['observations']) and {key(r):r[selected]for r in cap['observations']}==sources,'Full PC/MPR/physical/byte identity hits differ')
    require(outputs['native']['rows']==outputs['interpreter']['rows']==outputs['gear']['rows'],'Cross-engine completed CPU/device rows differ')
    return total,sources


def qualify(case,outputs,captures,journal,abi):
    total,sources=qualify_execution(case,outputs,captures,abi)
    require(len(journal)==total,'Original journal opcode extent differs')
    got=Counter();last_clock=0;callbacks=[];actual_calls=0;primer=primer_clocks(case,True)
    for i,group in enumerate(journal):
        fields={'phase','ordinal','calls','pc','mpr','bytes','returned_ticks','internal_ticks','call_rows','clocks','callbacks','after'}
        require(type(group)is dict and set(group)==fields,'Strict original journal required')
        measured=i>=case['primer_steps'];ordinal=i-case['primer_steps']+1 if measured else i+1
        require(group['phase']==('measured'if measured else'primer') and type(group['ordinal'])is int and group['ordinal']==ordinal,'Actual phase/ordinal differs')
        require(type(group['calls'])is int and group['calls']>=1 and (not measured or group['calls']==1),'Actual continuation count differs')
        opcode=group['bytes'][0]
        require(group['calls']==(int.from_bytes(bytes(group['bytes'][5:7]),'little')+2 if opcode==0x73 else 1),'Original block continuation count differs')
        require(type(group['pc'])is int and type(group['mpr'])is list and len(group['mpr'])==8 and all(type(v)is int and 0<=v<=255 for v in group['mpr']),'Original full source mapping required')
        require(type(group['bytes'])is list and all(type(v)is int and 0<=v<=255 for v in group['bytes']),'Original fetched bytes required')
        physical=tuple((group['mpr'][((group['pc']+n)&65535)>>13]<<13)|((group['pc']+n)&8191)for n in range(len(group['bytes'])))
        got[(group['pc'],tuple(group['mpr']),physical,tuple(group['bytes']))]+=1
        require(type(group['returned_ticks'])is int and type(group['internal_ticks'])is int and 0<=group['internal_ticks']<=group['returned_ticks'],'Original raw clock partition required')
        span_sum=0;start=last_clock
        for span in group['clocks']:
            require(type(span)is list and len(span)==3 and all(type(v)is int for v in span),'Original callback span shape differs')
            before,ticks,after=span;require(before==last_clock and ticks>0 and after==before+ticks,'Original clock continuity differs');last_clock=after;span_sum+=ticks
        require(span_sum==group['returned_ticks'],'Original returned time versus actual clock callbacks differs')
        if not measured:require(group['returned_ticks']==primer[i][0],'Independent original primer duration differs')
        require(type(group['call_rows'])is list and len(group['call_rows'])==group['calls'],'Actual original call partition extent differs')
        cursor=call_ticks=call_internal=0
        for call in group['call_rows']:
            require(type(call)is list and len(call)==5 and all(type(v)is int and v>=0 for v in call),'Typed actual call kernel required')
            returned,internal,begin,internal_end,end=call
            require(begin==cursor and begin<=internal_end<=end<=len(group['clocks']) and internal<=returned,'Actual call kernel continuity differs')
            require(sum(s[1]for s in group['clocks'][begin:internal_end])==internal,'Original internally clocked span differs')
            require(end-internal_end==int(returned>internal) and sum(s[1]for s in group['clocks'][internal_end:end])==returned-internal,'Actual wrapper drain differs')
            cursor=end;call_ticks+=returned;call_internal+=internal
        require(cursor==len(group['clocks']) and call_ticks==group['returned_ticks'] and call_internal==group['internal_ticks'],'Original call/aggregate clock association differs')
        if opcode==0x73:
            divisor=primer[i][1]
            length=group['bytes'][5]|group['bytes'][6]<<8
            expected=[14*divisor,*([6*divisor]*(length or 65536)),3*divisor]
            require([r[0]for r in group['call_rows']]==expected,'Independent block continuation cadence differs')
        for event in group['callbacks']:
            require(type(event)is dict and type(event.get('cycle'))is int and start<=event['cycle']<=last_clock,'Original callback actual time outside instruction clocks')
            callback_fields={1:{'cycle','type','vector','pc','mask'},2:{'cycle','type','event','value'},
                             5:{'cycle','type','event','irq','active','enabled'},7:{'cycle','type','event','length','address','reg','value','state'}}
            require(type(event.get('type'))is int and event['type']in callback_fields and set(event)==callback_fields[event['type']]
                    and all(type(v)is int and 0<=v<2**64 for v in event.values()),'Strict original callback fields required')
            callbacks.append(event)
        if measured:
            if ordinal==1:require(start==outputs['gear']['origin_ticks'],'Actual original primer origin differs')
            row(group['after'],case['expected'][ordinal-1]);require(group['after']==outputs['gear']['rows'][ordinal-1],'Journal/actual stdout state association differs')
            require(group['after']['values'][7]==last_clock-outputs['gear']['origin_ticks'],'Actual measured retirement time differs from clock callbacks')
        else:require(group['after']['values'][7]==last_clock,'Actual primer time differs from callbacks')
        actual_calls+=group['calls']
    require(dict(got)==sources,'Actual original source identity/hit ledger differs')
    # Original callback witnesses establish source causes, not just a line seeded by an observer.
    primer=[e for g in journal[:case['primer_steps']]for e in g['callbacks']]
    half=[e for e in primer if e['type']==7 and e.get('event')==7 and e.get('value')==1]
    end=[e for e in primer if e['type']==7 and e.get('event')==8 and e.get('value')==1]
    if case['source']=='half-read':require(any(e['length']==32767 for e in half),'Read HALF threshold witness absent')
    if case['source']=='half-play':require(any(e['length']==32768 for e in half),'Playback HALF threshold witness absent')
    if case['source']=='threshold-read':require(not half and not end,'Read threshold incorrectly asserted HALF/END')
    if case['source']=='end-read':require(not half and any(e['length']==0 for e in end),'Zero-length read END cause absent')
    if case['source']=='both-write':require(any(e['length']==0 for e in half) and any(e['length']==0 for e in end),'Zero-length write dual causes absent')
    irq=[e for e in callbacks if e['type']==1]
    require([e['vector']for e in irq]==[r['irq_vector']for r in case['expected']if r['irq_vector']],'Original actual IRQ callback order differs')
    return dict(native=total,interpreted=total,measured=STEPS,source_identities=len(sources),
                literal_checks=3*(STEPS+1)*(len(COLUMNS)+2),original_calls=actual_calls,original_irq_callbacks=len(irq),pure_guards=4)


def build_gear(args,out,report,bindings,compiler):
    checkout,source=infra.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=ref.compile_sources(checkout,source);cpp.append(ROOT/'tests/geargrafx_adpcm_irq_probe.cpp');deps=checkout/'platforms/shared/dependencies'
    flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for p in(checkout/'src',ROOT/'tests',out/'fixture',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(p)]
    objects=out/'gear-objects';objects.mkdir();jobs=[]
    for i,path in enumerate(cpp+c):
        obj=objects/(str(i)+'-'+path.stem+'.o');cmd=[str(compiler),*flags,'-x','c++'if path.suffix=='.cpp'else'c',*(['-std=c++20','-include','cerrno']if path.suffix=='.cpp'else['-std=c11']),'-c',str(path),'-o',str(obj)]
        jobs.append((cmd,obj));report['commands'].append(cmd)
    def compile_one(job):
        cmd,obj=job;done=subprocess.run(cmd,capture_output=True,text=True,timeout=180);obj.with_suffix('.log').write_text(done.stdout+done.stderr);done.check_returncode()
    with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(compile_one,jobs))
    libraries=[p.resolve()for p in args.library];require(libraries and all(p.is_file()for p in libraries),'Existing explicit libraries required')
    bindings['external_libraries']={str(p):sha(p)for p in libraries};binary=out/'gear-adpcm-irq.exe'
    common.evidence([str(compiler),*[str(obj)for _,obj in jobs],*map(str,libraries),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(obj):sha(obj)for _,obj in jobs};bindings['gear_binary']={str(binary):sha(binary)};return binary


def build_tool(args,out,report,bindings,compiler):
    tool=args.tool_source.resolve();cmake,ninja=(Path(shutil.which(str(v))or'').resolve()for v in(args.cmake,args.ninja));bindings['tools'].update({str(p):sha(p)for p in(cmake,ninja)})
    fixture=out/'fixture';wrapper=out/'wrapper';wrapper.mkdir();quote=infra.cmake_quote
    text=['cmake_minimum_required(VERSION 3.20)','project(AdpcmIrqReference LANGUAGES CXX)',*['set('+v+' OFF CACHE BOOL "" FORCE)'for v in('BUILD_TESTING','PCE_BUILD_TESTS','PCE_BUILD_TOOLS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE')],
          f'add_subdirectory({quote(tool)} tool)',f'pce_add_native_module(_module MODULE {quote(fixture/"module.cpp")} MANIFEST {quote(fixture/"module.json")})',
          f'add_executable(adpcm-irq {quote(ROOT/"tests/adpcm_irq_probe.cpp")})',f'target_include_directories(adpcm-irq PRIVATE {quote(fixture)} {quote(ROOT/"tests")})','target_link_libraries(adpcm-irq PRIVATE ${_module} pce-runtime)']
    path=wrapper/'CMakeLists.txt';path.write_text('\n'.join(text)+'\n');bindings['tool_build_inputs']={str(path):sha(path)};build=out/'tool-build'
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],'tool-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--parallel','2'],'tool-build',out,report,bindings,600)
    binary=build/('adpcm-irq.exe'if os.name=='nt'else'adpcm-irq');bindings['tool_binary']={str(binary):sha(binary)};return binary


def run(args):
    tool=args.tool_source.resolve();out=args.out.resolve();compiler=Path(shutil.which(str(args.compiler))or'').resolve()
    require(not out.exists() and out.is_relative_to(ROOT/'.local') and compiler.is_file(),'New private output and existing compiler required')
    sys.path.insert(0,str(tool));from pcerecomp import project
    require(Path(project.__file__).resolve()==tool/'pcerecomp/project.py','Wrong compiler selected')
    sources=[Path(__file__),*[ROOT/'tests'/n for n in('generate_adpcm_irq_fixture.py','generate_irq_device_fixture.py','adpcm_irq_probe.cpp','geargrafx_adpcm_irq_probe.cpp','adpcm_irq_support.hpp','irq_trace_support.hpp','reference_trace_support.hpp','reset_probe_support.hpp')],*[ROOT/'scripts'/n for n in('mapper_reference.py','filtered_audio_reference.py','hucard_reference.py')]]
    sources+=sorted((tool/'pcerecomp').glob('*.py'))+sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))+[tool/'CMakeLists.txt',tool/'cmake/PCEConsumer.cmake']
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources={str(p):sha(p)for p in sources})
    report=dict(schema=1,result='incomplete',commands=[],bindings=bindings,oracle_commit=ref.COMMIT,scope='Guest-created ADPCM HALF/END CPU IRQ sources. Actual whole-primer and measured source hits; separate original core and independent CPU/WRAM/device literals. No injected IRQ state, retail, hardware bus or analog audio claim.')
    out.mkdir(parents=True);epoch=out/'authored-inputs';epoch.mkdir();bindings['authored_epoch']={}
    for i,p in enumerate(sources):
        saved=epoch/str(i)/p.name;saved.parent.mkdir();shutil.copyfile(p,saved);bindings['authored_epoch'][str(saved)]=sha(saved)
    try:
        fixture=generate(out/'fixture');bindings['fixture']={str(p):sha(p)for p in(out/'fixture').iterdir()if p.is_file()}
        gear=build_gear(args,out,report,bindings,compiler);native=build_tool(args,out,report,bindings,compiler);results=[];admissions={};observed_sources=set()
        from pcerecomp.capture import load_capture
        for case in fixture['cases']:
            folder=out/case['id'];folder.mkdir();outputs={};captures={}
            original=common.evidence([str(gear),str(out/'fixture'/case['rom']),str(out/'fixture/authored.cue'),case['id'],str(folder/'original.jsonl')],'gear-'+case['id'],out,report,bindings)
            outputs['gear']=json.loads(original.stdout);journal=[json.loads(line)for line in(folder/'original.jsonl').read_text().splitlines()];bindings['raw_outputs'][str(folder/'original.jsonl')]=sha(folder/'original.jsonl')
            for tier in('native','interpreter'):
                cap=folder/(tier+'-capture.json');done=common.evidence([str(native),case['id'],tier,str(cap)],tier+'-'+case['id'],out,report,bindings)
                outputs[tier]=json.loads(done.stdout);captures[tier],digest=load_capture(cap);bindings['raw_outputs'][str(cap)]=digest
                if tier=='native':observed_sources.update(key(r)for r in captures[tier]['observations'])
            admission=dict(case=case,outputs=outputs,captures=captures,journal=journal,abi=fixture['runtime_abi']);result=qualify(**admission);result['id']=case['id'];results.append(result)
            path=folder/'admission.json';path.write_text(json.dumps(admission,indent=2)+'\n');admissions[str(path)]=sha(path)
        bindings['admissions']=admissions
        manifest=json.loads((out/'fixture/module.json').read_text())
        require(manifest['native_instructions_emitted']==len(observed_sources) and not manifest['unsupported_observations'],'Every compiled authored source identity must actually execute')
        for p in(out/'tool-build').rglob('*'):
            if p.is_file() and p.suffix in('.obj','.a'):bindings.setdefault('tool_objects',{})[str(p)]=sha(p)
        report.update(result='pass',tool=project.source_identity(tool),cases=results,
                      native=sum(r['native']for r in results),interpreted=sum(r['interpreted']for r in results),
                      literal_checks=sum(r['literal_checks']for r in results),pure_guards=sum(r['pure_guards']for r in results),
                      compiled_observed_identities=len(observed_sources),block_transfers=sum(c['block_steps']for c in fixture['cases']))
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:
        ref.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    require(report['result']=='pass','Evidence preservation failed');print(json.dumps({k:v for k,v in report.items()if k not in('commands','bindings','cases')},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gear-source',type=Path,required=True);p.add_argument('--tool-source',type=Path,default=ROOT);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--compiler',default='clang++');p.add_argument('--cmake',default='cmake');p.add_argument('--ninja',default='ninja');p.add_argument('--library',type=Path,action='append',default=[])
    try:run(p.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as e:print(e,file=sys.stderr);raise SystemExit(1)

