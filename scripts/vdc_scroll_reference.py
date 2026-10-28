"""Run authored guest scroll races against separately built pinned Geargrafx.

No original core code is linked into the toolkit. Raw reports, source/tool
bindings, actual source captures and separately expected scroll/pixel values
remain private in a new output directory.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,os,shutil,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from scripts import mapper_reference as infrastructure
from scripts import filtered_audio_reference as reference
from scripts import hucard_reference as common
from generate_vdc_scroll_fixture import generate


def require(ok,message):
    if not ok:raise ValueError(message)


def expected(case,report):
    require(type(report)is dict and report.get('schema')==1 and report.get('case')==case['id'],'Typed scroll report/case required')
    s=report['scroll']
    require(set(s)=={'x','y','counter','pending','x_clock','y_clock','lsb_clock','bxr_before','pixels'},'Strict scroll snapshot required')
    for name in ('x','y','counter','pending','x_clock','y_clock','lsb_clock','bxr_before'):
        require(type(s[name])is int,'Integer scroll field required')
    for name in ('x','y','counter'):require(s[name]==case[name],'Independent '+name+' literal differs')
    require(s['pending']==int(case['pending']),'Independent pending-Y literal differs')
    pixels=[1 if ((((case['x']+i)//8)&1)^(case['y']&1))==0 else 2 for i in range(16)]
    require(s['pixels']==pixels and all(type(p)is int for p in s['pixels']),'Independent rendered pixels differ')
    require(type(report['actions'])is list and len(report['actions'])==len(case['events']),'Bounded action list required')
    return 20


def identity(row):
    return row['pc'],tuple(row['mpr']),tuple(row['physical']),tuple(row['data'])


def qualify(case,native,interpreted,gear,captures):
    checks=sum(expected(case,r)for r in (native,interpreted,gear))
    for profile,r in (('runtime',native),('runtime',interpreted),('gear',gear)):
        require(r['guest']==dict(pc=case[profile]['end_pc'],ticks=case['sample_ticks'],a=0,x=0,y=0,sp=0,p=6,
            mpr=[255,248,0,0,0,1,0,0],wram_sha256=hashlib.sha256(bytes(8192)).hexdigest()),
            'Independent CPU/mapping/full-zero-WRAM literals differ')
    require(native['guest']==interpreted['guest']and native['scroll']==interpreted['scroll']and native['actions']==interpreted['actions'],'Complete native/interpreter report equality required')
    require(native['scroll']==gear['scroll'],'Actual original scroll latch/history/pixel state differs')
    require(native['guest']['ticks']==gear['ticks']==case['sample_ticks'],'Exact authored final clocks differ')
    require(native['guest']['wram_sha256']==gear['wram_sha256'],'Actual original full WRAM differs')
    for name,r,own in (('native',native,'native_steps'),('interpreter',interpreted,'interpreter_steps')):
        require(r[own]==case['runtime']['steps']and r['native_steps']+r['interpreter_steps']==r[own]and r['guard_misses']==0,'Actual tier work/fallback differs')
        capture=captures[name]
        require(capture['complete']is True and capture['dropped_instructions']==capture['unreadable_instructions']==0,'Complete actual source capture required')
        require(capture['retired_instructions']==r[own] and sum(v['native_hits']+v['interpreted_hits']for v in capture['observations'])==r[own],'Actual source hit conservation differs')
        from pcerecomp.project import ABI
        require(capture['runtime_abi']==ABI,'Actual source capture ABI differs')
        planned={identity(row)for row in case['runtime']['sources']}
        actual={identity(row)for row in capture['observations']}
        require(len(planned)==len(case['runtime']['sources']) and actual==planned and len(actual)==len(capture['observations']),'Actual logical-PC/full-MPR/physical/byte identities differ')
        for row in capture['observations']:
            require(type(row['native_hits'])is int and type(row['interpreted_hits'])is int and
                    row['native_hits']==int(name=='native') and row['interpreted_hits']==int(name=='interpreter'),
                    'Actual per-source native/interpreted hit ledger differs')
    for index,(_,value,phase)in enumerate(case['events']):
        require(native['actions'][index]['before']==gear['actions'][index]['before']and
                native['actions'][index]['after']==gear['actions'][index]['after'],
                'Original intermediate scroll history/pixels differ')
        for profile,r in (('runtime',native),('gear',gear)):
            a=r['actions'][index];want=case[profile]['actions'][index]
            require(a['step']==want['index'] and a['entry_ticks']+6==a['effect_ticks']==want['effect_ticks']and a['after_ticks']==a['effect_ticks']+9,'Independent instruction/port clock partition differs')
            require(a['value']==value and a['port']=={'st0':0,'st1':2,'st2':3}[want['operation']],'Actual port/value differs')
            if profile=='gear':
                writes=a['original_writes'];require(len(writes)==(0 if a['port']==0 else 1),'Original port event count differs')
                for w in writes:require(w['ticks']==a['effect_ticks']and w['raw']==value,'Original real register callback differs')
    return dict(literal_checks=checks,source_identities=len(captures['native']['observations']),native=native['native_steps'],interpreter=interpreted['interpreter_steps'],blocks=native['block_steps'])


def build_gear(args,out,report,bindings,compiler,fixture):
    checkout,source=infrastructure.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    report['gear_source_sha256']=hashlib.sha256(json.dumps(source,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    cpp,c=reference.compile_sources(checkout,source);cpp.append(ROOT/'tests/geargrafx_vdc_scroll_probe.cpp')
    deps=checkout/'platforms/shared/dependencies'
    flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for p in (checkout/'src',ROOT/'tests',fixture,deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(p)]
    objects=out/'gear-objects';objects.mkdir();jobs=[]
    for i,p in enumerate(cpp+c):
        obj=objects/(str(i)+'-'+p.stem+'.o')
        cmd=[str(compiler),*flags,'-x','c++'if p.suffix=='.cpp'else'c',*(['-std=c++20','-include','cerrno']if p.suffix=='.cpp'else['-std=c11']),'-c',str(p),'-o',str(obj)]
        report['commands'].append(cmd);jobs.append((cmd,obj))
    def compile_one(job):
        cmd,obj=job;r=subprocess.run(cmd,capture_output=True,timeout=180)
        obj.with_suffix('.stdout').write_bytes(r.stdout);obj.with_suffix('.stderr').write_bytes(r.stderr);r.check_returncode()
    with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(compile_one,jobs))
    libs=[p.resolve(strict=True)for p in args.library];require(bool(libs),'Explicit existing Gear dependency libraries required')
    bindings['external_libraries']={str(p):reference.sha(p)for p in libs}
    binary=out/('gear-scroll.exe'if os.name=='nt'else'gear-scroll')
    common.evidence([str(compiler),*[str(o)for _,o in jobs],*map(str,libs),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(o):reference.sha(o)for _,o in jobs};bindings['gear_binary']={str(binary):reference.sha(binary)}
    return binary


def run(args):
    out=args.out.resolve();require(not out.exists()and out.is_relative_to(ROOT/'.local'),'Choose a new private output directory')
    compiler=Path(shutil.which(str(args.compiler))or'').resolve();require(compiler.is_file(),'Existing compiler required')
    out.mkdir(parents=True);fixture=out/'fixture';metadata=generate(fixture)
    probe=args.tool_probe.resolve(strict=True)
    from pcerecomp.project import source_identity
    paths=[Path(__file__),ROOT/'tests/generate_vdc_scroll_fixture.py',ROOT/'tests/generate_irq_device_fixture.py',ROOT/'tests/vdc_scroll_probe.cpp',ROOT/'tests/geargrafx_vdc_scroll_probe.cpp',ROOT/'tests/vdc_scroll_support.hpp',ROOT/'runtime/src/scanline.cpp',ROOT/'runtime/include/pce/scanline.hpp']
    bindings=dict(tools={str(compiler):reference.sha(compiler),str(Path(sys.executable)):reference.sha(Path(sys.executable))},authored_sources={str(p):reference.sha(p)for p in paths},tool_binary={str(probe):reference.sha(probe)},fixtures={str(p):reference.sha(p)for p in fixture.rglob('*')if p.is_file()})
    report=dict(schema=1,result='incomplete',tool=source_identity(ROOT),commands=[],bindings=bindings,cases=[],scope='Authored genuine guest scroll writes, literal latch/pixel values and actual original VDC callbacks. Separate CSH prefix programs; no electrical bus or whole-renderer/hardware claim.')
    try:
        gear=build_gear(args,out,report,bindings,compiler,fixture)
        for c in metadata['cases']:
            directory=out/c['id'];directory.mkdir();outputs={};captures={}
            for tier in ('native','interpreter'):
                capture=directory/(tier+'-capture.json');cmd=[str(probe),c['id'],tier,str(capture)]
                common.evidence(cmd,tier,directory,report,bindings,120)
                outputs[tier]=json.loads((directory/(tier+'.stdout')).read_bytes());captures[tier]=json.loads(capture.read_bytes())
                bindings.setdefault('actual_captures',{})[str(capture)]=reference.sha(capture)
            common.evidence([str(gear),str(fixture/c['gear']['rom']),str(fixture/'authored.cue'),c['id']],'gear',directory,report,bindings,120)
            outputs['gear']=json.loads((directory/'gear.stdout').read_bytes())
            r=qualify(c,outputs['native'],outputs['interpreter'],outputs['gear'],captures)
            report['cases'].append(dict(id=c['id'],**r))
        report['result']='pass';report['actual_work']=dict(cases=len(report['cases']),native=sum(c['native']for c in report['cases']),interpreter=sum(c['interpreter']for c in report['cases']),fallback=0,source_identity_occurrences=sum(c['source_identities']for c in report['cases']))
    except Exception as error:report.update(result='fail',error=repr(error));raise
    finally:
        reference.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    require(all(report['preservation'].values()),'Bound scroll evidence changed')
    print(json.dumps({k:v for k,v in report.items()if k not in ('bindings','commands','cases')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True);parser.add_argument('--compiler',required=True)
    parser.add_argument('--tool-probe',type=Path,required=True);parser.add_argument('--library',type=Path,action='append',default=[])
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    try:run(args)
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:parser.exit(1,str(error)+'\n')
