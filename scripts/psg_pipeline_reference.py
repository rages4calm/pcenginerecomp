"""Original guest PSG source and HPF domains through 2048 stereo frames.

An unchanged original Gear CPU executes each authored instruction. Its channel
buffers are observed before EndFrame and its actual HPF PCM after EndFrame.
Separate toolkit native/interpreter raw/filtered executions normalize only the
documented /3 mixer headroom. There is no 48 kHz or retail parity claim.
"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, localcontext
from pathlib import Path
import argparse, copy, hashlib, json, os, shutil, struct, subprocess, sys
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from pcerecomp import project
from pcerecomp.audio_trace import compare_traces, validate_trace
from scripts import psg_phase_reference as phase
from scripts import mapper_reference as infrastructure
from scripts import filtered_audio_reference as reference
from scripts import hucard_reference as common

FRAMES=2048
MASTER=21477273
GROUPS={'inputs','tools','reference_raw_sources','reference_compile_sources','raw_outputs','external_libraries','gear_objects','gear_binary','authored_fixture','admissions','traces'}
def require(ok,message):
    if not ok:raise ValueError(message)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def f32(value):return struct.unpack('<f',struct.pack('<f',value))[0]
def divide(value,denominator):return value//denominator if value>=0 else -((-value)//denominator)
def strict(value):
    if type(value)is dict:
        for k,v in value.items():require(type(k)is str,'Strict string key required');strict(v)
    elif type(value)is list:
        for v in value:strict(v)
    else:require(type(value)in(int,str),'Strict integers and strings required')

def independent_samples(case):
    """Decimal gain, literal authored state and individually rounded binary32."""
    with localcontext()as ctx:
        ctx.prec=70
        gains=[int(Decimal(65535)/192/(Decimal(10)**(Decimal(3)*n/40)))for n in range(31)]+[0]
    volume=(0,3,5,7,9,11,13,15,16,19,21,23,25,27,29,31)
    dda=case['old'];control=223;balance=255
    for reg,value in phase.expected_write_values(case):
        if reg==6:dda=value&31
        if reg==4:control=value
        if reg==5:balance=value
    require(dda==case['new'],'Authored final DAC expectation differs')
    loss=31-volume[balance&15]+31-(control&31)
    final=(2*dda-31)*gains[min(loss,31)]if control&128 else 0
    values=[(2*case['old']-31)*gains[0]]+[final]*(FRAMES-1)
    source=[[v,v]for v in values]
    raw=[[divide(divide(v,2),3)]*2 for v in values]
    previous_input=previous_output=f32(0);hpf=[]
    for v in values:
        current=f32(v*0.5)
        output=f32(f32(current-previous_input)+f32(f32(0.9985)*previous_output))
        hpf.append([max(-32768,min(32767,int(output)))]*2)
        previous_input=current;previous_output=output
    return source,raw,hpf

def qualify(case,speed,reports):
    labels={'gear','native-raw','interpreted-raw','native-filtered','interpreted-filtered'}
    require(type(reports)is dict and set(reports)==labels,'Exact five executions required')
    source,raw,hpf=independent_samples(case)
    filtered=[[divide(v,3)for v in row]for row in hpf]
    start=488-(19 if case['size']==7 else 4)*speed
    end=start+case['cycles']*speed
    last=(FRAMES*MASTER+44099)//44100
    continuation=end+(last-end+speed-1)//speed*speed
    base=dict(case=case['name'],divisor=speed,pc=case['pc'],mpr=[255,248,248,248,248,255,248,0],physical=list(range(case['pc']&8191,(case['pc']&8191)+case['size'])),bytes=case['data'],start=start,end=end,final_pc=case['pc']+case['size'],dda=case['new'],frames=FRAMES,continuation_end=continuation,partition_end_frames=[512,1024,1536,2048],source_ticks=[(i*MASTER+44099)//44100 for i in range(1,FRAMES+1)])
    stride=8 if case['size']==7 and case['data'][2]==0 else 6
    writes=[[start+(14+(i+1)*stride)*speed if case['size']==7 else end,reg,value]for i,(reg,value)in enumerate(phase.expected_write_values(case))]
    gear=dict(base,calls=5 if case['size']==7 else 1,writes=writes,source_sums=source,hpf=hpf)
    for label,row in reports.items():
        strict(row)
        expected=gear if label=='gear'else dict(base,native=int(label.startswith('native-')),interpreted=int(label.startswith('interpreted-')),profile=label.split('-')[1],rate=44100,observed_source_first_frame=2,observed_source_sums=source[1:],pcm=filtered if label.endswith('filtered')else raw)
        require(type(row)is dict and set(row)==set(expected),'Strict complete report fields required: '+label)
        for key in expected:require(row[key]==expected[key],'Independent '+key+' expectation differs: '+case['name']+'/'+str(speed)+'/'+label)
    return dict(case=case['name'],divisor=speed,frames=FRAMES,source_scalar_checks=FRAMES*2,original_hpf_scalar_checks=FRAMES*2,tool_pcm_scalar_checks=FRAMES*2*4,tool_observed_source_scalar_checks=(FRAMES-1)*2*4,native=2,interpreted=2,original_cpu_calls=gear['calls'],original_psg_writes=len(writes),unexplained_differences=0)

def trace(case,speed,stage,samples,engine,fixture_sha256):
    value=dict(schema=1,format='pce-audio-trace-1',engine=engine,fixture_sha256=fixture_sha256,case=case['name']+'-d'+str(speed),domain=dict(stage=stage,timing='gear-v1',source_rate=44100,output_rate=44100,gain_divisor=3,latency_source_frames=0,resampler='identity-v1'),first_frame=1,samples=samples)
    validate_trace(value);return value

def match(expected,actual):
    result=compare_traces(expected,actual)
    # The public comparator raises on incompatible contracts. Compatible
    # samples are additionally compared literally, independent of report shape.
    require(expected['samples']==actual['samples'],'Compared audio trace differs')
    return result

def git_blobs(checkout):
    rows=subprocess.check_output(['git','-C',str(checkout),'ls-tree','-r',reference.COMMIT,'src','platforms/shared/dependencies'],text=True).splitlines()
    return {name:metadata.split()[2]for metadata,name in (r.split('\t',1)for r in rows)if Path(name).suffix in('.cpp','.c','.h','.hpp')}

def audit_receipt(path):
    path=Path(path).resolve();report=json.loads(path.read_text());bindings=report['bindings']
    require(report['result']=='pass'and set(bindings)==GROUPS,'Exact complete evidence groups required')
    required_inputs={'psg_pipeline_reference.py','psg_pipeline_probe.cpp','geargrafx_psg_pipeline_probe.cpp','audio_trace.py','generate_psg_phase_fixture.py','runtime.cpp','audio.cpp','audio_dsp.cpp','pcm.cpp','emitter.py','project.py'}
    require(required_inputs.issubset({Path(p).name for p in bindings['inputs']}),'Required pipeline source bindings missing')
    for group in GROUPS:
        require(type(bindings[group])is dict and bindings[group],'Nonempty binding group required: '+group)
        for filename,digest in bindings[group].items():require(type(filename)is str and type(digest)is str and sha(filename)==digest,'Preserved file binding differs: '+group)
    require(report['oracle_commit']==reference.COMMIT,'Pinned original commit differs')
    checkout=Path(report['oracle_checkout']);original=git_blobs(checkout)
    require(original==report['original_git_blobs'],'Pinned original Git metadata differs')
    compile_sources={}
    for filename,digest in bindings['reference_compile_sources'].items():
        saved=Path(filename);relative=saved.relative_to(Path(report['reference_compile_root'])).as_posix();data=saved.read_bytes();blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        require(blob==original.get(relative),'Original compile Git blob differs')
        raw=checkout/relative;require(str(raw)in bindings['reference_raw_sources']and raw.read_bytes().replace(b'\r\n',b'\n')==data,'Original raw/compile association differs')
        compile_sources[relative]=sha(saved)
    require(len(bindings['reference_raw_sources'])==len(bindings['reference_compile_sources']),'Complete original source association differs')
    require(report['oracle_source_sha256']==hashlib.sha256(json.dumps(compile_sources,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'Original source digest metadata differs')
    actual_tool=project.source_identity(Path(report['tool_source']))
    require(all(actual_tool[k]==report['tool'][k]for k in('source_sha256','source_files')),'Toolkit source metadata differs')
    headers=[Path(p)for p in bindings['authored_fixture']if Path(p).name=='psg_phase_fixture.hpp'];require(len(headers)==1,'Exact authored fixture header required');cases=phase.parse_fixture(headers[0]);matrix=[(c,s)for c in cases for s in(3,12)]
    images=[p for p in bindings['authored_fixture']if Path(p).name=='authored.pce'];require(len(images)==1 and report['fixture_sha256']==sha(images[0]),'Authored image digest metadata differs')
    require(len(matrix)==len(report['cases'])==len(bindings['admissions'])==72,'Complete authored execution matrix required')
    probes=[p for p in bindings['inputs']if Path(p).name==report['probe_basename']];require(len(probes)==1 and len(bindings['gear_binary'])==1,'Exact actual executable bindings required')
    original_binary=next(iter(bindings['gear_binary']));commands=[];processes=[]
    for case,speed in matrix:
        commands.append([original_binary,case['name'],str(speed),images[0]]);processes.append(dict(label='gear',returncode=0))
        for profile in('raw','filtered'):
            for tier in('native','interpreted'):
                commands.append([probes[0],case['name'],str(speed),tier,profile]);processes.append(dict(label=tier+'-'+profile,returncode=0))
    require(report['commands'][-360:]==commands and report['processes'][-360:]==processes,'Actual command/process execution association differs')
    used=set();trace_used=set()
    for result,(case,speed)in zip(report['cases'],matrix):
        folder=path.parent/(case['name']+'-'+str(speed));admission=folder/'admission.json'
        require(str(admission)in bindings['admissions'],'Case admission binding missing')
        a=json.loads(admission.read_text());require(set(a)=={'case','speed','reports','raw_stdout','traces'}and a['case']==case and type(a['speed'])is int and a['speed']==speed,'Strict canonical case association required')
        require(set(a['reports'])==set(a['raw_stdout'])=={'gear','native-raw','interpreted-raw','native-filtered','interpreted-filtered'},'Exact actual five execution joins required')
        for label,filename in a['raw_stdout'].items():
            raw=folder/(label+'.stdout');require(filename==str(raw)and filename not in used and filename in bindings['raw_outputs'],'Raw stdout case association differs');used.add(filename)
            require(str(raw.with_suffix('.stderr'))in bindings['raw_outputs'],'Raw stderr binding missing')
            require(json.loads(raw.read_text())==a['reports'][label],'Raw stdout differs from admission')
        require(qualify(case,speed,a['reports'])==result,'Recomputed pipeline qualification differs')
        expected_traces=make_traces(case,speed,a['reports'],report)
        require(set(a['traces'])==set(expected_traces),'Complete pipeline trace association required')
        loaded={}
        for label,value in expected_traces.items():
            filename=str(folder/(label+'.trace.json'));require(a['traces'][label]==filename and filename in bindings['traces']and filename not in trace_used,'Trace case association differs');trace_used.add(filename);loaded[label]=json.loads(Path(filename).read_text());require(loaded[label]==value,'Trace differs from actual source report');validate_trace(loaded[label])
        compare_case_traces(loaded)
    require(trace_used==set(bindings['traces']),'Unassociated pipeline trace binding')
    return dict(result='pass',cases=len(matrix),raw_stdout=len(used),traces=len(trace_used),original_git_blobs=len(bindings['reference_raw_sources']),bindings=sum(len(v)for v in bindings.values()))

def make_traces(case,speed,reports,report):
    fixture=report['fixture_sha256'];tool=report['tool'];binary=next(iter(report['bindings']['inputs'][p]for p in report['bindings']['inputs']if Path(p).name==report['probe_basename']))
    original_engine=dict(name='original-geargrafx',revision=reference.COMMIT,source_sha256=report['oracle_source_sha256'],binary_sha256=next(iter(report['bindings']['gear_binary'].values())))
    sources=reports['gear']['source_sums'];values={'gear-raw':('psg-raw',[[divide(divide(v,2),3)for v in row]for row in sources],original_engine),'gear-filtered':('psg-hpf',[[divide(v,3)for v in row]for row in reports['gear']['hpf']],original_engine)}
    for label in ('native-raw','interpreted-raw','native-filtered','interpreted-filtered'):
        engine=dict(name='pcerecomp-'+label.split('-')[0],revision=tool['revision'],source_sha256=tool['source_sha256'],binary_sha256=binary)
        values[label]=('psg-hpf'if label.endswith('filtered')else'psg-raw',reports[label]['pcm'],engine)
    return {label:trace(case,speed,stage,samples,engine,fixture)for label,(stage,samples,engine)in values.items()}

def compare_case_traces(values):
    for profile in('raw','filtered'):
        for tier in('native','interpreted'):match(values['gear-'+profile],values[tier+'-'+profile])

def written_negative_controls(receipt,out):
    """Reaudit a valid changed copy, then retain written refusal candidates.

    Source/object/binary files stay bound to the preserved execution. Only case
    journals, stdout/stderr and traces are copied. Every candidate is written
    and reloaded, and an accepted-copy audit precedes any negative assertion.
    """
    receipt=Path(receipt).resolve();out=Path(out).resolve()
    require(not out.exists()and out.is_relative_to(ROOT/'.local'),'Require NEW private controls directory')
    audit_receipt(receipt);original=json.loads(receipt.read_text());base=copy.deepcopy(original)
    out.mkdir(parents=True);cloned=out/'accepted-copy';cloned.mkdir()
    old=receipt.parent
    def copied(filename):return str(cloned/Path(filename).relative_to(old))
    for group in('raw_outputs','traces','admissions'):
        rewritten={}
        for filename,digest in base['bindings'][group].items():
            source=Path(filename)
            is_case=source.parent.parent==old and any(source.parent.name==c['case']+'-'+str(c['divisor'])for c in base['cases'])
            if not is_case:rewritten[filename]=digest;continue
            target=Path(copied(filename));target.parent.mkdir(parents=True,exist_ok=True)
            if group=='admissions':
                data=json.loads(source.read_text());data['raw_stdout']={k:copied(v)for k,v in data['raw_stdout'].items()};data['traces']={k:copied(v)for k,v in data['traces'].items()};target.write_text(json.dumps(data,separators=(',',':'))+'\n')
            else:shutil.copyfile(source,target)
            rewritten[str(target)]=sha(target)
        base['bindings'][group]=rewritten
    basepath=cloned/'result.json';basepath.write_text(json.dumps(base,indent=2)+'\n');accepted=audit_receipt(basepath)
    controls=[]
    def refuse(name,candidate):
        path=cloned/(name+'.candidate.json');path.write_text(json.dumps(candidate,indent=2)+'\n')
        try:audit_receipt(path)
        except(ValueError,OSError,KeyError)as error:controls.append(dict(name=name,result='refused',candidate=str(path),candidate_sha256=sha(path),reason=str(error)))
        else:raise ValueError('Changed-copy candidate accepted: '+name)
    for group in sorted(GROUPS):
        candidate=copy.deepcopy(base);filename,digest=next(iter(candidate['bindings'][group].items()));source=Path(filename)
        changed=out/('binding-'+group)/source.name;changed.parent.mkdir();changed.write_bytes(source.read_bytes()+b'\nchanged-copy-control\n')
        del candidate['bindings'][group][filename];candidate['bindings'][group][str(changed)]=digest
        refuse('changed-'+group,candidate)
    for key,value in(('oracle_commit','0'*40),('oracle_source_sha256','0'*64),('fixture_sha256','0'*64)):
        candidate=copy.deepcopy(base);candidate[key]=value;refuse('metadata-'+key,candidate)
    candidate=copy.deepcopy(base);candidate['original_git_blobs'][next(iter(candidate['original_git_blobs']))]='0'*40;refuse('metadata-original-git-blob',candidate)
    candidate=copy.deepcopy(base);candidate['tool']['source_sha256']='0'*64;refuse('metadata-tool-source',candidate)
    candidate=copy.deepcopy(base);candidate['commands'][-1][-1]='raw';refuse('execution-command-profile',candidate)
    # Written journals exercise joins even when the modified file hash is
    # correctly rebound. Restore the accepted copy after each refusal while
    # retaining each changed journal and exact rejection receipt separately.
    first=next(iter(base['bindings']['admissions']));journal=Path(first);saved=journal.read_bytes();payload=json.loads(saved)
    mutations={
        'raw-case-swap':lambda d:d['raw_stdout'].__setitem__('gear',str(journal.parent/'native-raw.stdout')),
        'raw-relabel':lambda d:d['reports']['gear'].__setitem__('dda',99),
        'output-profile':lambda d:d['reports']['native-raw'].__setitem__('profile','filtered'),
        'trace-domain-association':lambda d:d['traces'].__setitem__('gear-raw',d['traces']['gear-filtered']),
    }
    for name,mutate in mutations.items():
        changed=copy.deepcopy(payload);mutate(changed);journal.write_text(json.dumps(changed,separators=(',',':'))+'\n')
        retained=out/(name+'.changed-admission.json');shutil.copyfile(journal,retained)
        candidate=copy.deepcopy(base);candidate['bindings']['admissions'][first]=sha(journal)
        try:refuse(name,candidate)
        finally:journal.write_bytes(saved)
    # Cross-domain rejection uses actual valid samples, rather than corrupting
    # their numbers to manufacture a failure.
    trace_path=next(p for p in base['bindings']['traces']if Path(p).name=='gear-raw.trace.json');left=json.loads(Path(trace_path).read_text());right=copy.deepcopy(left);right['domain']['stage']='psg-hpf'
    domain_path=out/'cross-domain.changed-trace.json';domain_path.write_text(json.dumps(right)+'\n')
    try:match(left,json.loads(domain_path.read_text()))
    except ValueError as error:controls.append(dict(name='raw-vs-filtered-domain',result='refused',candidate=str(domain_path),candidate_sha256=sha(domain_path),reason=str(error)))
    else:raise ValueError('Raw-versus-filtered domain admitted')
    require(audit_receipt(basepath)==accepted,'Accepted-copy restoration differs')
    result=dict(result='pass',accepted_copy=accepted,refused=len(controls),controls=controls)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');return result

def build_gear(args,out,report,bindings,compiler,fixture):
    checkout,sources=infrastructure.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=reference.compile_sources(checkout,sources);cpp.append(ROOT/'tests/geargrafx_psg_pipeline_probe.cpp')
    deps=checkout/'platforms/shared/dependencies';flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for path in(checkout/'src',fixture,deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(path)]
    folder=out/'gear-objects';folder.mkdir();jobs=[]
    for index,path in enumerate(cpp+c):
        obj=folder/(str(index)+'-'+path.stem+'.o');cmd=[str(compiler),*flags,'-x','c++'if path.suffix=='.cpp'else'c',*(['-std=c++20','-include','cerrno']if path.suffix=='.cpp'else['-std=c11']),'-c',str(path),'-o',str(obj)];report['commands'].append(cmd);jobs.append((cmd,obj))
    def one(job):
        cmd,obj=job;done=subprocess.run(cmd,capture_output=True,timeout=180)
        for suffix,data in[('stdout',done.stdout),('stderr',done.stderr)]:
            path=obj.with_suffix('.'+suffix);path.write_bytes(data);bindings.setdefault('raw_outputs',{})[str(path)]=sha(path)
        done.check_returncode()
    with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(one,jobs))
    libraries=[p.resolve(strict=True)for p in args.library];require(libraries,'Explicit original dependency libraries required');bindings['external_libraries']={str(p):sha(p)for p in libraries}
    binary=out/('original-gear-psg-pipeline.exe'if os.name=='nt'else'original-gear-psg-pipeline')
    common.evidence([str(compiler),*[str(obj)for _,obj in jobs],*map(str,libraries),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(obj):sha(obj)for _,obj in jobs};bindings['gear_binary']={str(binary):sha(binary)}
    report['oracle_source_sha256']=hashlib.sha256(json.dumps(sources,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return binary

def run(args):
    out=args.out.resolve();tool=args.tool_source.resolve();probe=args.probe.resolve();compiler=Path(shutil.which(args.compiler)or'').resolve()
    require(not out.exists()and out.is_relative_to(ROOT/'.local')and probe.is_file()and compiler.is_file(),'Require NEW private .local output, probe and compiler')
    require(Path(project.__file__).resolve()==tool/'pcerecomp/project.py','Selected toolkit import differs')
    inputs=[Path(__file__),ROOT/'tests/geargrafx_psg_pipeline_probe.cpp',ROOT/'tests/psg_pipeline_probe.cpp',ROOT/'tests/generate_psg_phase_fixture.py',ROOT/'scripts/psg_phase_reference.py',ROOT/'scripts/mapper_reference.py',ROOT/'scripts/filtered_audio_reference.py',ROOT/'scripts/hucard_reference.py',ROOT/'scripts/psg_reference.py',tool/'CMakeLists.txt',probe]
    for folder in('runtime','pcerecomp','cmake'):inputs +=[p for p in(tool/folder).rglob('*')if p.is_file()and p.suffix in('.cpp','.hpp','.h','.py','.cmake')and'__pycache__'not in p.parts]
    bindings=dict(inputs={str(p):sha(p)for p in inputs},tools={str(compiler):sha(compiler)})
    report=dict(schema=1,result='incomplete',tool=project.source_identity(tool),tool_source=str(tool),oracle_commit=reference.COMMIT,oracle_checkout=str(args.gear_source.resolve()),reference_compile_root=str(out/'pinned-reference-source'),original_git_blobs=git_blobs(args.gear_source.resolve()),probe_basename=probe.name,commands=[],bindings=bindings,cases=[],scope='Authored guest instruction followed by device-clock continuation; 2048 source frames per case, 512-frame drains. Independent source and HPF expectations; source sums before half gain; raw and filtered 44.1kHz matching domains after fixed /3. No 48kHz, retail, listening or campaign claim. Toolkit first source sum is not observed directly.')
    out.mkdir(parents=True)
    try:
        fixture=out/'module';common.evidence([sys.executable,str(ROOT/'tests/generate_psg_phase_fixture.py'),str(fixture)],'fixture',out,report,bindings);cases=phase.parse_fixture(fixture/'psg_phase_fixture.hpp');bindings['authored_fixture']={str(p):sha(p)for p in fixture.iterdir()if p.is_file()}
        rom=bytearray([0xea])*8192
        for case in cases:offset=case['pc']&8191;rom[offset:offset+case['size']]=bytes(case['data'])
        rom[-4:]=bytes([0,224,0,224]);image=out/'authored.pce';image.write_bytes(rom);bindings['authored_fixture'][str(image)]=sha(image);report['fixture_sha256']=sha(image)
        gear=build_gear(args,out,report,bindings,compiler,fixture);bindings['admissions']={};bindings['traces']={}
        for case in cases:
            for speed in(3,12):
                folder=out/(case['name']+'-'+str(speed));folder.mkdir();values={}
                commands=[('gear',gear,[str(image)])]+[(tier+'-'+profile,probe,[tier,profile])for profile in('raw','filtered')for tier in('native','interpreted')]
                for label,binary,extra in commands:
                    done=common.evidence([str(binary),case['name'],str(speed),*extra],label,folder,report,bindings);values[label]=json.loads(done.stdout)
                report['cases'].append(qualify(case,speed,values));traces=make_traces(case,speed,values,report);compare_case_traces(traces);paths={}
                for label,value in traces.items():
                    path=folder/(label+'.trace.json');path.write_text(json.dumps(value,separators=(',',':'))+'\n');paths[label]=str(path);bindings['traces'][str(path)]=sha(path)
                admission=folder/'admission.json';admission.write_text(json.dumps(dict(case=case,speed=speed,reports=values,raw_stdout={label:str(folder/(label+'.stdout'))for label in values},traces=paths),separators=(',',':'))+'\n');bindings['admissions'][str(admission)]=sha(admission)
        require(project.source_identity(tool)==report['tool'],'Toolkit source changed during pipeline proof');report['result']='pass'
    except BaseException as error:report['result']='fail';report['error']=repr(error);raise
    finally:reference.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    require(report['result']=='pass','Source/evidence preservation failed');audited=audit_receipt(out/'result.json');(out/'audit.json').write_text(json.dumps(audited,indent=2)+'\n');controls=written_negative_controls(out/'result.json',out/'negative-controls');print(json.dumps(dict(audit=audited,changed_copy_refusals=controls['refused']),indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--probe',type=Path,required=True);parser.add_argument('--gear-source',type=Path,required=True);parser.add_argument('--tool-source',type=Path,default=ROOT);parser.add_argument('--compiler',default='clang++');parser.add_argument('--library',type=Path,action='append',default=[]);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--audit',type=Path)
    args=parser.parse_args()
    try:
        if args.audit:print(json.dumps(audit_receipt(args.audit),indent=2))
        else:run(args)
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:print(error,file=sys.stderr);raise SystemExit(1)
