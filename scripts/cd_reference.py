"""Independent idle CD-control/BRAM checks using authored CD media and RAM."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'tests'))
from generate_io_fixture import make_fixture


def prepare_media(out,setup,*,profile='single'):
    if len(setup)>8190:
        raise ValueError('Synthetic bootstrap exceeds its reset-vector bank')
    if profile not in ('single','toc'):
        raise ValueError('Unknown authored CD media profile')
    out.mkdir(parents=True,exist_ok=True)
    bios=bytearray([0xEA]*262144);bios[:len(setup)]=setup;bios[8190:8192]=bytes((0,0xE0))
    cue='FILE "synthetic-disc.bin" BINARY\n'
    for i in range(12 if profile=='toc' else 1):
        frame=i*86
        kind='MODE1/2352' if profile=='single' or i in (0,11) else 'AUDIO'
        cue+=f'  TRACK {i+1:02} {kind}\n    INDEX 01 {frame//4500:02}:{frame//75%60:02}:{frame%75:02}\n'
    files={'synthetic-syscard.pce':bytes(bios),'synthetic-disc.bin':bytes(2352*(1032 if profile=='toc' else 300)),
           'synthetic-disc.cue':cue.encode('ascii')}
    for name,data in files.items():
        path=out/name
        if path.exists():
            if path.stat().st_size!=len(data) or path.read_bytes()!=data:
                raise ValueError("Existing synthetic CD input differs; choose a new output folder")
        else:
            path.write_bytes(data)
    return out/'synthetic-disc.cue',out/'synthetic-syscard.pce'


def plans():
    _,cases=make_fixture();sites={(op,address):pc for pc,op,address in cases}
    result=[]
    def step(op,address,value=-1):return (sites[op,address],value)
    for value in (0,1,0x7F,0x80,0xFF,0x55,0xAA,2):
        for flags in (0,255):
            sequences={
                'gating':[(0x8D,0x1807,value),(0x8D,0x8000,value^0xA5),(0xAD,0xC000,-1),
                          (0x8D,0xC7FF,value),(0xAD,0x87FF,-1),(0x8D,0x8800,value),
                          (0xAD,0xC800,-1),(0x8D,0x9FFF,value),(0xAD,0xDFFF,-1),
                          (0x8D,0x1807,128),(0x8D,0xC000,value),(0xAD,0x8000,-1),
                          (0x8D,0x1803,value),(0xAD,0x1803,-1),(0x8D,0x8000,value^255),
                          (0xAD,0x8000,-1),(0x8D,0xB807,128),(0xAD,0xC000,-1),(0xAD,0xC7FF,-1)],
                'control':[(0x8D,0x1802,value),(0xAD,0xB802,-1),(0x8D,0xB804,value),(0xAD,0x1804,-1),
                           (0x8D,0xB802,value^255),(0xAD,0x1802,-1),(0x8D,0x1804,2),
                           (0xAD,0xB804,-1),(0x8D,0x1804,0),(0xAD,0x1804,-1),
                           (0x8D,0xB807,value),(0xAD,0x1803,-1),(0xAD,0xB803,-1)],
                'rmw-index':[(0x8D,0x1807,128),(0x0C,0x1803,value),(0x8D,0xB807,128),
                             (0x1C,0x1803,value),(0x8D,0xB807,128),(0x9D,0x87FF,value),
                             (0xBD,0x87FF,-1),(0xAD,0x87FF,-1),(0x8D,0xB807,value),(0xAD,0xB803,-1)]}
            for name,operations in sequences.items():
                i=len(result)
                result.append({'id':f'{name}-{value:02x}-{flags:02x}','seed':i,'a':value,'x':1,'y':(i*67)&255,
                               'sp':(0,1,254,255)[i%4],'p':flags,
                               'steps':[step(*op) for op in operations]+[step(0x43,0)]})
    return result


def run_cd_matrix(client,areas,args,started,info):
    from scripts.reference_geargrafx import state
    snapshot,cases=make_fixture();sites={(op,address):pc for pc,op,address in cases}
    ram_area=next(a['id'] for a in areas if a['name']=='SYSTEM RAM' and a['byte_size']==8192)
    bram_area=next(a['id'] for a in areas if a['name']=='BRAM' and a['byte_size']==2048)
    media=client.call('get_media_info')
    if not media['is_cdrom'] or not media['is_cdrom_hardware_enabled'] or not media['loaded_bios']:
        raise RuntimeError('Reference CD hardware was not enabled by the authored synthetic media')
    selected=plans()[args.shard_index::args.shard_count]
    if not selected:raise ValueError('Selected CD shard has no sequences')
    counts={tier:{'states':0,'ram_bram':0,'native_steps':0,'interpreter_steps':0} for tier in ('native','interpreter')}
    plan_path=args.out/'sequence.txt'
    for plan in selected:
        if time.monotonic()-started>180:raise RuntimeError('Reference check exceeded its 180-second work budget')
        ram=bytearray((i*37+plan['seed']*17)&255 for i in range(8192))
        for pa,value in snapshot.memory.items():ram[pa-0x1F0000]=value
        client.call('write_memory',area=ram_area,offset='0000',bytes=ram.hex(' '))
        client.call('write_huc6280_register',name='PC',value='2700')
        for _ in range(16):client.call('debug_step_into')
        # Idle device reset/control setup, performed as real CPU writes.
        for address,value in ((0x1807,128),(0x1804,2),(0x1804,0),(0x1802,0)):
            client.call('write_huc6280_register',name='PC',value=f'{sites[0x8D,address]:X}')
            client.call('write_huc6280_register',name='A',value=f'{value:X}')
            client.call('debug_step_into')
        bram=bytes((i*13+plan['seed']*7)&255 for i in range(2048))
        client.call('write_memory',area=bram_area,offset='0000',bytes=bram.hex(' '))
        registers={'PC':plan['steps'][0][0],'A':plan['a'],'X':plan['x'],'Y':plan['y'],'S':plan['sp'],'P':plan['p']}
        for name,value in registers.items():client.call('write_huc6280_register',name=name,value=f'{value:X}')
        status=client.call('get_huc6280_status');before=state(status)
        if before['mpr']!=list(snapshot.mpr) or status['SPEED']!='7.16 MHz' or status['TIMER'] or any(status[k] for k in ('IRQ1_asserted','IRQ2_asserted','TIQ_asserted')):
            raise RuntimeError('Reference CPU mapping/speed/interrupt setup failed')
        if any(before[k]!=registers[v] for k,v in (('pc','PC'),('a','A'),('x','X'),('y','Y'),('sp','S'),('p','P'))):
            raise RuntimeError('Reference register setup was not applied exactly')
        expected=[]
        for pc,value in plan['steps']:
            client.call('write_huc6280_register',name='PC',value=f'{pc:X}')
            if value>=0:client.call('write_huc6280_register',name='A',value=f'{value:X}')
            client.call('debug_step_into')
            status=client.call('get_huc6280_status');cd=client.call('get_cdrom_status')
            expected.append({'cpu':state(status),'cd':{'bram_unlocked':cd['bram_enabled'],'ack':cd['scsi_ack'],
                'irq_enable':int(cd['enabled_irqs'],16),'irq_active':int(cd['active_irqs'],16),
                'reset':cd['reset'],'irq2':status['IRQ2_asserted']}})
        memory={'ram':bytes.fromhex(client.call('read_memory',area=ram_area,offset='0000',size=8192)['data']).hex(),
                'bram':bytes.fromhex(client.call('read_memory',area=bram_area,offset='0000',size=2048)['data']).hex()}
        header=[plan[k] for k in ('seed','a','x','y','sp','p')]+[len(plan['steps'])]
        plan_path.write_text(' '.join(map(str,header))+'\n'+''.join(f'{pc} {value}\n' for pc,value in plan['steps']),encoding='ascii')
        wanted={'states':expected}|memory
        for tier in counts:
            process=subprocess.run([str(args.probe.resolve()),'--probe',str(plan_path.resolve()),tier],capture_output=True,text=True,check=True,timeout=5)
            actual=json.loads(process.stdout)
            mismatch={k:{'actual':actual.get(k),'expected':v} for k,v in wanted.items() if actual.get(k)!=v}
            n,i=actual['native_steps'],actual['interpreter_steps']
            if (n,i)!=((len(expected),0) if tier=='native' else (0,len(expected))):mismatch['counters']=actual
            if mismatch:
                (args.out/'failure.json').write_text(json.dumps({'plan':plan['id'],'tier':tier,'mismatch':mismatch},indent=2)+'\n')
                raise RuntimeError(f'Reference CD-control mismatch: {plan["id"]}, {tier}')
            counts[tier]['states']+=len(expected);counts[tier]['ram_bram']+=1
            counts[tier]['native_steps']+=n;counts[tier]['interpreter_steps']+=i
    report={'schema':1,'result':'pass','suite':'cd-control','oracle':info['serverInfo'],
            'oracle_exe_sha256':hashlib.sha256(args.exe.read_bytes()).hexdigest(),'probe_sha256':hashlib.sha256(args.probe.read_bytes()).hexdigest(),
            'shard':{'index':args.shard_index,'count':args.shard_count},'checked_sequences':[p['id'] for p in selected],
            'comparisons':counts,'inputs':'authored 256 KiB bootstrap, 300-sector blank CUE/BIN and synthetic RAM; no retail firmware/disc/save',
            'scope':'CPU state, CD-control observable state after each instruction, full 8 KiB RAM and 2 KiB BRAM; stable mapping in both tiers',
            'not_checked':['CD transport/subcode/audio','nonzero device IRQ sources live','IRQ delivery','bus phases/device waits','hardware qualification','gameplay']}
    (args.out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='checked_sequences'},indent=2))
