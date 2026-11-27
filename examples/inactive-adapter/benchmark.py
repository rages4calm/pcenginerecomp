"""Compare host instruction-boundary cost using separately qualified consumers.

This Windows-only measurement uses the authored title-adapter fixture. Expected
instruction-budget exhaustion is a fixed-work benchmark endpoint, never a
successful reached-target probe. It neither builds nor migrates a checkpoint.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.dev_client import DevClient

MAPPING = [255,248,248,248,248,248,248,248]
UNREACHABLE_PC = 0x6000
PROGRAM_SHA256 = '997e24cb99d5d6253ac2dc630b6a76dc2a85f195ae06d371a9777051a61b7e65'
MODES = {
    'plain-scalar': ('original', None, None),
    'pristine-scalar': ('adapted', 'pristine', dict(exp=1,gold=1,protection=0)),
    'pristine-span8': ('span', 'pristine', dict(exp=1,gold=1,protection=0)),
    'enhanced-span8': ('span', 'enhanced', dict(exp=2,gold=8,protection=1)),
}


def require(ok, message):
    if not ok: raise ValueError(message)


def sha(raw): return hashlib.sha256(raw).hexdigest()
def write(path, value): path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


class ProcessClock:
    """Cumulative kernel+user CPU of all threads in this one child process."""
    def __init__(self, pid):
        if os.name != 'nt': raise ValueError('This benchmark requires Windows GetProcessTimes')
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.OpenProcess.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD)
        self.api.OpenProcess.restype=wintypes.HANDLE
        self.api.GetProcessTimes.argtypes=(wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)]*4))
        self.api.GetProcessTimes.restype=wintypes.BOOL
        self.api.CloseHandle.argtypes=(wintypes.HANDLE,)
        self.api.CloseHandle.restype=wintypes.BOOL
        self.handle=self.api.OpenProcess(0x1000,False,pid) # QUERY_LIMITED_INFORMATION
        if not self.handle: raise ctypes.WinError(ctypes.get_last_error())

    def read(self):
        values=[wintypes.FILETIME() for _ in range(4)]
        if not self.api.GetProcessTimes(self.handle,*(ctypes.byref(value) for value in values)):
            raise ctypes.WinError(ctypes.get_last_error())
        count=lambda value:(value.dwHighDateTime<<32)|value.dwLowDateTime
        return count(values[2])+count(values[3])

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle);self.handle=None


def unreachable_fixture(qualification):
    """Admit the original authored CFG, without claiming timed code capture."""
    inputs=qualification/'inputs';raw=(inputs/'authored.bin').read_bytes()
    meta=json.loads((inputs/'fixture.json').read_bytes())
    roots=json.loads((inputs/'roots.json').read_bytes())['roots']
    require(sha(raw)==meta['program_sha256']==PROGRAM_SHA256,'Not the reviewed 170-byte authored fixture')
    pcs={item['pc'] for item in roots}
    require(pcs and min(pcs)==0x2800 and max(pcs)<UNREACHABLE_PC,'Target overlaps authored code')
    # Explicit stack, SEI and no CLI/PLP/RTI/BRK/TAM/indirect control. Direct
    # calls and branches remain in this graph; RTS returns to those call sites.
    allowed={0x78,0xD8,0xD4,0xA2,0x9A,0xA9,0x8D,0x9C,0x03,0x13,0x23,
             0xAD,0x29,0xF0,0xCA,0xD0,0x85,0x64,0x18,0x65,0x38,0xA5,
             0xE9,0x20,0x80,0xE6,0xC6,0x60}
    require(raw[:6]==bytes.fromhex('78D8D4A2FF9A'),'Missing authored interrupt/stack setup')
    for item in roots:
        offset=item['source_offsets'][0];opcode=raw[offset];pc=item['pc']
        require(item['mpr']==MAPPING and item['selector']==0 and opcode in allowed,
                'Fixture added mapping, interrupt or unknown control semantics')
        if opcode in (0xF0,0xD0,0x80):
            displacement=int.from_bytes(raw[offset+1:offset+2],'little',signed=True)
            require(pc+2+displacement in pcs,'Authored branch escapes declared graph')
        if opcode==0x20:
            require(int.from_bytes(raw[offset+1:offset+3],'little') in pcs and pc+3 in pcs,
                    'Authored call/return escapes declared graph')
    return dict(program_sha256=sha(raw),roots_sha256=sha((inputs/'roots.json').read_bytes()),
                declared_identities=len(pcs),target_pc=UNREACHABLE_PC,
                evidence='Static authored CFG admission, not observed timed source-hit counts')


PLAN_CODE = '''import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from pcerecomp import project
from pcerecomp.checkpoint_continuation import _audit
v=json.loads(sys.stdin.read())
options=dict(dev_port=0,start_paused=True,reference_enabled=True,checkpoint_dir=Path(v['checkpoints']))
if v['mode'] is not None:options.update(title_mode=v['mode'],title_settings=v['settings'])
plan=project.prepare_launch(Path(v['descriptor']),Path(v['build']),**options)
checked=project.verify(Path(v['descriptor']))
built=json.loads((Path(v['build'])/'build-receipt.json').read_bytes())
audit=_audit(checked,built,Path(v['build']))
print(json.dumps(dict(tool=project.source_identity(Path(sys.argv[1])),plan=plan,
                     config=checked['config'],identities=checked['identities'],audit=audit,
                     module_tree=built['cache']['input_contract']['trees']['module'])))
'''


def plans(sdk, qualification, output):
    result={}
    for name,(package,mode,settings) in MODES.items():
        descriptor=qualification/'inputs'/package/'project.toml'
        build=qualification/(package+'-build')
        receipt=json.loads((build/'build-receipt.json').read_bytes())
        require(receipt['desktop'] is True and receipt['cache']['hit'] is False,'Requires qualified audited desktop MISS package')
        checked=subprocess.run([sys.executable,'-B','-c',PLAN_CODE,str(sdk)],cwd=sdk,
            input=json.dumps(dict(descriptor=str(descriptor),build=str(build),
                                 checkpoints=str(output/'checkpoints'),mode=mode,settings=settings)),
            text=True,encoding='utf-8',stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=180)
        row=json.loads(checked.stdout)
        require(row['tool']==receipt['binding']['tool'],'Controller does not match package SDK')
        config=row['config']
        require(config['payload']['sha256']==PROGRAM_SHA256 and config['payload']['pc']==0x2800
                and config['payload']['physical_load']==0x1F0800 and config['payload']['mpr']==MAPPING,
                'Package payload/boot does not bind reviewed unreachable-target fixture')
        require(config['runtime'].get('native_span',1)==(8 if package=='span' else 1)
                and config['runtime']['tier']=='native','Package native-span policy differs from mode label')
        command=row['plan']['command']
        require(not any(flag in command for flag in ('--audio-out','--title-audit','--code-capture','--checkpoint-load')),
                'Timed command must have no WAV/audit/capture or foreign checkpoint import')
        command += ['--hidden','on','--window-scale','1','--unthrottled','on']
        row['recipe']=dict(descriptor_sha256=sha(descriptor.read_bytes()),
                           build_receipt_sha256=sha((build/'build-receipt.json').read_bytes()))
        result[name]=row
    return result


def sdk_inventory(sdk):
    paths=[sdk/'CMakeLists.txt']
    for directory in ('pcerecomp','runtime','cmake'):
        paths.extend(path for path in (sdk/directory).rglob('*') if path.is_file()
            and '__pycache__' not in path.parts and path.suffix not in ('.pyc','.pyo'))
    require(not any(path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&0x400 for path in paths),
            'SDK inventory contains a link')
    return {path.relative_to(sdk).as_posix():sha(path.read_bytes()) for path in sorted(paths)}


def cross_side_equivalence(admitted, sides):
    inventories={side:sdk_inventory(value['sdk']) for side,value in sides.items()}
    require(inventories['baseline'].keys()==inventories['candidate'].keys(),'SDK production membership differs')
    changed=[name for name in inventories['baseline'] if inventories['baseline'][name]!=inventories['candidate'][name]]
    require(changed==['runtime/src/headless.cpp'],'Benchmark permits only intended host-source change')
    results={}
    for mode in MODES:
        normalized={}
        for side,value in sides.items():
            row=admitted[side][mode]
            config=json.loads(json.dumps(row['config']));config.pop('tool')
            # Full audits were revalidated by each matching pinned SDK. Compare
            # compiler/dependencies and effective flags, not just endpoint state.
            audit=json.loads(json.dumps(row['audit']))
            audit.pop('current_audit_sha256')
            audit['shared']['tool'].pop('source_sha256')
            for key in ('CMAKE_CXX_COMPILER','CMAKE_MAKE_PROGRAM','SDL3_DIR'):
                if key in audit['shared']['options']:
                    audit['shared']['options'][key]=Path(audit['shared']['options'][key]).resolve().as_posix()
            for tree in audit['shared']['trees']['tool_compile']:
                if Path(tree['path']).resolve()==(value['sdk']/'runtime').resolve():
                    tree['sha256']='<EXACT_HEADLESS_ONLY_CHANGE>'
            roots=sorted([(str(value['sdk']),'<SDK>'),(str(value['qualification']),'<QUALIFICATION>')],key=lambda item:len(item[0]),reverse=True)
            def clean(item):
                if type(item) is dict:return {key:clean(value) for key,value in item.items()}
                if type(item) is list:return [clean(value) for value in item]
                if type(item) is str:
                    for root,token in roots:
                        item=item.replace(root,token).replace(root.replace('\\','/'),token)
                return item
            normalized[side]=clean(dict(config=config,identities=row['identities'],audit=audit,module_tree=row['module_tree']))
        require(normalized['baseline']==normalized['candidate'],mode+' recipe/emission/compiler/dependency/effective policy differs')
        results[mode]=dict(equivalent=True,normalized_policy_sha256=sha(json.dumps(normalized['baseline'],sort_keys=True,separators=(',',':')).encode()))
    return dict(sdk_inventories=inventories,intended_changed_files=changed,modes=results)


def fixed_work(client, count, poll_seconds):
    before=client.call('status')
    require(before['paused'] is True,'Fixed-work start must be paused')
    ack=client.call('run_until',pc=UNREACHABLE_PC,mpr=bytes(MAPPING).hex(),
                    mpr_mask=255,instructions=count,ticks=10000000000)
    polls=[];deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        status=client.call('status');polls.append(status)
        window=status.get('instruction_window',{})
        if window.get('state')!='running':
            require(status['paused'] is True and window.get('state')=='instruction_limit',
                    'Endpoint is not the explicitly expected instruction-budget exhaustion')
            host=status['host'];old=before['host']
            require(window['native_steps']==count and window['interpreter_steps']==0
                    and host['native_steps']-old['native_steps']==count
                    and host['interpreter_steps']==old['interpreter_steps']==0,
                    'Fixed work was not exactly the requested native count')
            require(window['ticks']==status['ticks']-before['ticks'],'Window tick accounting differs')
            return dict(before=before,ack=ack,end=status,polls=polls)
        time.sleep(poll_seconds)
    raise TimeoutError('Fixed-work instruction window did not settle')


def envelope(path):
    raw=path.read_bytes();require(raw[:8]==b'PCEDEVCP','Invalid checkpoint magic')
    version,abi=struct.unpack_from('<II',raw,8)
    require(version in (1,2) and abi==29,'Unknown benchmark checkpoint version')
    require(struct.unpack_from('<I',raw,16)[0]==64 and struct.unpack_from('<I',raw,84)[0]==64,'Invalid checkpoint header strings')
    body=raw[160:]
    require(struct.unpack_from('<Q',raw,152)[0]==len(body) and sha(body)==raw[88:152].decode('ascii'),'Checkpoint length/digest differs')
    offset=60;extension=b''
    if version==2:
        require(body[60:68]==b'PCETITLE' and struct.unpack_from('<II',body,68)==(1,64),'Unknown enhanced envelope')
        size=struct.unpack_from('<I',body,140)[0];require(size<=4160,'Unbounded adapter state')
        offset+=84+size;extension=body[60:offset]
    require(body[offset:offset+8]==b'PCECORE\0','Missing complete CORE')
    return dict(file_sha256=sha(raw),host_sha256=sha(body[:60]),adapter_sha256=sha(extension),
                core_sha256=sha(body[offset:]),body_sha256=sha(body),schema=version)


def aggregate_cells(rows, segments):
    """Sum explicit separate windows, never pretend their clocks are continuous."""
    buckets={}
    for row in rows:
        key=(row['mode'],row['group'],row['index'],row['side'])
        buckets.setdefault(key,[]).append(row)
    result=[]
    for (mode,group,index,side),members in sorted(buckets.items()):
        require(sorted(row['segment'] for row in members)==list(range(segments)),
                'Logical cell has duplicate/missing segments')
        result.append(dict(mode=mode,group=group,index=index,side=side,segments=segments,
            cpu_100ns=sum(row['cpu_100ns'] for row in members),
            wall_ns=sum(row['wall_ns'] for row in members),
            actual_native=sum(row['actual_native'] for row in members),
            polls=sum(row['polls'] for row in members),
            labels=[row['label'] for row in sorted(members,key=lambda row:row['segment'])]))
    return result


def run_cell(row, output, label, warmup, instructions, poll_seconds, mode):
    prefix=output/label;observations={};clock=None;process=None
    env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_RENDER_DRIVER='software',SDL_AUDIODRIVER='dummy')
    with prefix.with_suffix('.stdout').open('xb') as stdout,prefix.with_suffix('.stderr').open('xb') as stderr:
        try:
            process=subprocess.Popen(row['plan']['command'],env=env,stdin=subprocess.DEVNULL,
                stdout=stdout,stderr=stderr,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            deadline=time.monotonic()+15
            while True:
                text=prefix.with_suffix('.stderr').read_text(encoding='utf-8',errors='replace')
                match=re.search(r'PCE_DEV_PORT=(\d+)',text)
                if match:break
                require(process.poll() is None and time.monotonic()<deadline,'Benchmark child did not start')
                time.sleep(.02)
            clock=ProcessClock(process.pid)
            with DevClient(int(match[1]),timeout=60) as client:
                observations['warmup']=fixed_work(client,warmup,poll_seconds)
                # No fsync, media inspection, checkpoint/capture or build work in
                # this interval. CPU includes all child threads and RPC servicing.
                cpu0=clock.read();wall0=time.perf_counter_ns()
                measured=fixed_work(client,instructions,poll_seconds)
                wall1=time.perf_counter_ns();cpu1=clock.read()
                observations['measured']=measured
                host=measured['end']['host'];policy=host['execution_policy']
                span=8 if mode.endswith('span8') else 1
                require(policy['effective_native_span']==span and policy['configured_tier']=='native'
                        and policy['effective_policy']=='native' and policy['selected'] is False,
                        'Observed execution tier/span differs from mode label')
                adapter=host.get('title_adapter')
                if mode=='plain-scalar':require(adapter is None,'Plain host unexpectedly compiled an adapter')
                else:require(adapter and adapter['compiled'] is True
                    and adapter['mode']==('enhanced' if mode.startswith('enhanced') else 'pristine'),
                    'Observed adapter mode differs from benchmark label')
                require(process.poll() is None and cpu1>cpu0,'Missing live-child CPU interval')
                ram=client.read_memory_block(0x1F0000,8192);rgb_meta,rgb=client.capture('guest')
                name=label+'.pcec';checkpoint=client.call('save_checkpoint',name=name)['checkpoint']
                ending=client.call('status')
                require(ending['host']['native_steps']==measured['end']['host']['native_steps']
                        and ending['host']['interpreter_steps']==0,'Post-timing inspection retired guest work')
                client.call('quit')
            require(process.wait(timeout=15)==0,'Benchmark child refused/faulted')
            final=json.loads(prefix.with_suffix('.stdout').read_bytes())
            require(final['stop']=='dev_quit' and final['guard_misses']==0 and final['interpreter_steps']==0,
                    'Benchmark had fallback, guards or non-natural exit')
            require(final['native_steps']==warmup+instructions,'Global instruction allowance or foreign work affected endpoint')
            if span==8:
                dispatch=final['native_dispatch']
                require(dispatch['supported'] is True and dispatch['limit']==8
                        and dispatch['local_continuations']>0 and 1<dispatch['max_completed']<=8
                        and dispatch['interpreted_completed']==0,'No actual native-span local continuations')
            cp=envelope(output/'checkpoints'/name)
            warm=observations['warmup']['end']
            warm_cut=dict(ticks=warm['ticks'],frame=warm['frame'],cpu=warm['host']['cpu'],
                          native_steps=warm['host']['native_steps'],interpreter_steps=warm['host']['interpreter_steps'])
            result=dict(passed=True,pid=process.pid,cpu_100ns=cpu1-cpu0,wall_ns=wall1-wall0,
                cpu_before_100ns=cpu0,cpu_after_100ns=cpu1,wall_before_ns=wall0,wall_after_ns=wall1,
                requested_native=instructions,actual_native=measured['end']['host']['native_steps']-measured['before']['host']['native_steps'],
                interpreted=0,guard_misses=0,polls=len(measured['polls']),
                guest_ticks=measured['end']['ticks']-measured['before']['ticks'],
                ram_sha256=sha(ram),rgb_sha256=sha(rgb),rgb_dimensions=[rgb_meta['width'],rgb_meta['height']],
                checkpoint=cp,checkpoint_metadata=checkpoint,native_dispatch=final.get('native_dispatch'),
                warm_cut=warm_cut,execution_policy=policy,adapter_mode=adapter['mode'] if adapter else None)
            write(prefix.with_suffix('.observations.json'),observations)
            write(prefix.with_suffix('.result.json'),result)
            return result
        except BaseException as error:
            write(prefix.with_suffix('.failed.json'),dict(passed=False,error_type=type(error).__name__,error=str(error),observations=observations))
            raise
        finally:
            if clock:clock.close()
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


def benchmark(args):
    output=args.out.absolute();output.mkdir(parents=True,exist_ok=False);(output/'checkpoints').mkdir()
    report=dict(schema=1,format='pce-inactive-adapter-fixed-work-1',passed=False,
        scope='Interleaved authored desktop-host fixed native work; expected budget exhaustion, not a reached-target route or retail/hardware claim',
        timing='Windows GetProcessTimes kernel+user, all child threads; wall includes TCP request/polls/scheduling; no timed durable journal',
        cpu_api='https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes',
        warmup=args.warmup,instructions=args.instructions,rounds=args.rounds,segments=args.segments,poll_seconds=args.poll_seconds,
        aggregation='Each logical ABBA cell sums separate fresh-process segment CPU/wall intervals; not one continuous window or end-to-end elapsed',
        ambient_note=args.ambient_note,benchmark_sha256=sha(Path(__file__).read_bytes()),
        transport_sha256=sha((ROOT/'scripts/dev_client.py').read_bytes()),rows=[])
    started=time.monotonic()
    try:
        sides={name:dict(sdk=sdk.resolve(strict=True),qualification=qualification.resolve(strict=True))
            for name,sdk,qualification in (('baseline',args.baseline_sdk,args.baseline_qualification),('candidate',args.candidate_sdk,args.candidate_qualification))}
        proof={side:unreachable_fixture(value['qualification']) for side,value in sides.items()}
        require(proof['baseline']==proof['candidate'],'Source fixture identity/CFG differs')
        report['unreachable_target_proof']=proof
        admitted={side:plans(value['sdk'],value['qualification'],output) for side,value in sides.items()}
        report['cross_side_equivalence']=cross_side_equivalence(admitted,sides)
        report['plans']=admitted;write(output/'admission.json',admitted)
        modes=args.modes.split(',');require(modes and len(set(modes))==len(modes) and set(modes)<=MODES.keys(),'Unknown/duplicate modes')
        for mode in modes:
            for group in range(args.rounds):
                for segment in range(args.segments):
                    for index,side in enumerate(('baseline','candidate','candidate','baseline')):
                        label=f'{mode}-g{group:02d}-s{segment:02d}-{index}-{side}'
                        result=run_cell(admitted[side][mode],output,label,args.warmup,args.instructions,args.poll_seconds,mode)
                        report['rows'].append(dict(mode=mode,group=group,segment=segment,index=index,side=side,label=label,**result))
        report['logical_cells']=aggregate_cells(report['rows'],args.segments)
        cpu_values=[row['cpu_100ns'] for row in report['rows']]
        report['cpu_accounting']=dict(raw_delta_gcd_100ns=math.gcd(*cpu_values),
            all_raw_deltas_on_15_625ms_grid=all(value%156250==0 for value in cpu_values),
            caveat='100ns units are not 100ns resolution. Pilot exposed 15.625ms multiples; retain every raw interval and do not infer a finer timer.')
        report['comparisons']={}
        for mode in modes:
            rows=[row for row in report['rows'] if row['mode']==mode]
            expected=rows[0]
            for row in rows:
                for field in ('actual_native','interpreted','guard_misses','guest_ticks','ram_sha256','rgb_sha256','rgb_dimensions','warm_cut','execution_policy','adapter_mode'):
                    require(row[field]==expected[field],mode+' same-work state differs: '+field)
                require(row['checkpoint']['body_sha256']==expected['checkpoint']['body_sha256'],mode+' complete HOST/adapter/CORE differs')
            cells=[row for row in report['logical_cells'] if row['mode']==mode]
            old=[row for row in cells if row['side']=='baseline'];new=[row for row in cells if row['side']=='candidate']
            summary={}
            for field,scale in (('cpu_100ns',1e-7),('wall_ns',1e-9)):
                a=[row[field]*scale for row in old];b=[row[field]*scale for row in new]
                summary[field]=dict(baseline_seconds=a,candidate_seconds=b,
                    baseline_median=statistics.median(a),candidate_median=statistics.median(b),
                    median_ratio=statistics.median(b)/statistics.median(a),
                    ranges_overlap=not(max(b)<min(a) or max(a)<min(b)),
                    paired_group_ratios=[statistics.mean(row[field] for row in new if row['group']==g)/
                                         statistics.mean(row[field] for row in old if row['group']==g) for g in range(args.rounds)])
            report['comparisons'][mode]=summary
        # Re-admit every package/source after all timing; no timestamp cache.
        after={side:plans(value['sdk'],value['qualification'],output) for side,value in sides.items()}
        require(admitted==after,'Pinned controller/package/source changed across benchmark')
        require(report['cross_side_equivalence']==cross_side_equivalence(after,sides),'Comparison policy changed across benchmark')
        report.update(passed=True,source_hit_evidence='No timed code capture; declared source CFG admitted, actual native totals/guards and complete endpoint state checked')
    except BaseException as error:
        report['error']=dict(type=type(error).__name__,message=str(error));raise
    finally:
        report['elapsed_seconds']=time.monotonic()-started;write(output/'receipt.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for side in ('baseline','candidate'):
        parser.add_argument('--'+side+'-sdk',type=Path,required=True)
        parser.add_argument('--'+side+'-qualification',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--instructions',type=int,default=6000000)
    parser.add_argument('--warmup',type=int,default=250000)
    parser.add_argument('--rounds',type=int,default=3)
    parser.add_argument('--segments',type=int,default=3)
    parser.add_argument('--modes',default=','.join(MODES))
    parser.add_argument('--poll-seconds',type=float,default=.02)
    parser.add_argument('--ambient-note',required=True)
    args=parser.parse_args()
    require(1<=args.instructions<=6000000 and 1<=args.warmup<=250000,'Work must fit unchanged authored recipe limits')
    require(1<=args.rounds<=10 and 1<=args.segments<=4 and .001<=args.poll_seconds<=.1,'Finite rounds/segments and consistent polling required')
    result=benchmark(args)
    print(json.dumps(dict(passed=result['passed'],elapsed_seconds=result['elapsed_seconds'],comparisons=result['comparisons']),indent=2))
