"""Authored cold-boot fixtures compared with an unchanged external Geargrafx.

Zero/FF/A5 seeds select otherwise unspecified startup contents. The probe uses
real vector reads, public media/reset APIs and the original scheduler; it does
not certify electrical power-on values, warm reset, firmware or retail games.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts import filtered_audio_reference as reference
sha=reference.sha

CPU_FIELDS=('pc','a','x','y','sp','p','divisor','ticks',
            *('mpr'+str(i) for i in range(8)),'mpr_latch','io_latch',
            'timer_enabled','timer_reload','timer_counter','irq_mask','irq_request')
DEVICE_FIELDS=('vdc_selected','vdc_status','vdc_read_buffer',
               *('vdc_reg'+str(i) for i in range(20)),
               'vce_control','vce_address','palette_hash','joypad_latch',
               'cd_reset','bram_unlocked','cd_irq_active','cd_irq_enable','cd_fader',
               'scsi_data','scsi_signals','scsi_phase','cdda_state','cdda_start','cdda_stop','cdda_lba','cdda_frame',
               'adpcm_control','adpcm_dma','adpcm_rate','adpcm_address','adpcm_read_address','adpcm_write_address','adpcm_length',
               'adpcm_playing','adpcm_end_irq','adpcm_half_irq','psg_selected','psg_main_volume','psg_lfo_frequency','psg_lfo_control',
               *(f'psg_ch{i}_{field}' for i in range(6) for field in ('frequency','control','balance','index','noise','dda','noise_seed','wave_hash')),
               'wram_hash','cd_ram_hash','card_ram_hash','bram_hash','vram_hash','sat_hash','adpcm_ram_hash')

def authored_rom():
    image=bytearray((bank*29+offset*17+11)&255 for bank in range(32) for offset in range(8192))
    # Ordinary machine setup followed by isolated ROM/card/CD/WRAM accesses.
    # It depends on neither an extracted IPL nor System Card service code.
    code=bytes.fromhex('78 D8 A9 FF 53 01 A9 F8 53 02 A2 FF 9A D4 A9 00 8D 02 14 8D 01 0C '
                       '43 00 8D 00 20 A9 68 53 04 A9 A5 8D 00 40 AD 00 40 8D 01 20 '
                       'A9 80 53 08 A9 5A 8D 00 60 AD 00 60 8D 02 20 A9 F9 53 10 '
                       'A9 C3 8D 03 80 AD 03 20 80 FE')
    for offset in (0,256,4096):image[offset:offset+len(code)]=code
    image[8190:8192]=bytes((0,224))
    return bytes(image)

def plans():
    cases=[]
    for profile in (0,1):
        for region in (0,1):
            for fill in (0,255,165):
                for vector in (0xE000,0xE100,0xF000):
                    ops=[('r',profile,region,vector,fill,fill,fill),('s',),('d',),('i',34)]
                    cases.append(dict(id=f'boot-{profile}-{region}-{fill:02x}-{vector:04x}',operations=ops))
        # Exhaust all physical bank selections, boundaries and representative
        # byte offsets; write tests use independently patterned RAM contents.
        ops=[('r',profile,0,0xE000,0,0,0)]
        offsets=sorted({0,1,13,2047,2048,4095,4096,8190,8191,*range(0,8192,257)})
        for bank in range(128):
            for offset in offsets:ops.extend((('q',bank,offset),('p',bank,offset)))
            for offset in (0,4095,8191):ops.extend((('w',bank,offset,0xDE),('q',bank,offset),('p',bank,offset)))
        for bank in range(0x80,0x88):
            for offset in offsets:ops.extend((('w',bank,offset,(bank*31+offset*7)&255),('q',bank,offset),('p',bank,offset)))
        for bank in range(0x68,0x80):
            for offset in offsets:ops.extend((('w',bank,offset,(bank*11+offset*19)&255),('q',bank,offset),('p',bank,offset)))
        for bank in range(0xF8,0xFC):
            for offset in offsets:
                ops.append(('w',bank,offset,(bank*23+offset*3)&255))
                ops.extend(('q',alias,offset) for alias in range(0xF8,0xFC))
        for bank in (0x88,0xA0,0xEF,0xF6,0xFC,0xFE):
            for offset in (0,4095,8191):ops.extend((('q',bank,offset),('w',bank,offset,23),('q',bank,offset)))
        for port in range(0xC0,0xC4):ops.extend((('a',port),('c',port,0xF0),('a',port)))
        for offset in (0,1,7,8,2047,2048,8191):ops.append(('q',0xF7,offset))
        ops.extend((('c',7,0),('q',0xF7,0),('w',0xF7,0,0xA4),('q',0xF7,0),('c',7,128),('q',0xF7,0),('w',0xF7,0,0xA4),('q',0xF7,0),('w',0xF7,2048,0xA4),('q',0xF7,2048)))
        cases.append(dict(id=f'memory-{profile}',operations=ops))
    return cases

def serialize(cases):
    lines=[];spans=[];count=0
    for case in cases:
        start=count
        for op in case['operations']:
            lines.append(' '.join(map(str,op)))
            count+=op[1] if op[0]=='i' else op[0] in ('s','d','q','p','a')
        spans.append(dict(id=case['id'],start=start,records=count-start))
    return '\n'.join(lines)+'\n',spans

def validate(records,spans):
    count=sum(row['records'] for row in spans)
    if not isinstance(records,list) or len(records)!=count:raise ValueError('Reset record count changed')
    lengths={'cpu':len(CPU_FIELDS),'devices':len(DEVICE_FIELDS),'memory':3,'peek':3,'port':2}
    for row in records:
        if not isinstance(row,dict) or set(row)!={'kind','values'} or row['kind'] not in lengths:raise ValueError('Malformed reset record')
        values=row['values']
        if not isinstance(values,list) or len(values)!=lengths[row['kind']] or any(type(value)is not int or not 0<=value<=0xFFFFFFFFFFFFFFFF for value in values):raise ValueError('Malformed reset record values')
        if row['kind'] in ('memory','peek') and (values[0]>254 or values[1]>8191 or values[2]>255):raise ValueError('Invalid reset memory record range')
        if row['kind']=='port' and (values[0]>1023 or values[1]>255):raise ValueError('Invalid reset port record range')
        if row['kind']=='cpu':
            if values[0]>65535 or any(values[i]>255 for i in (*range(1,6),*range(8,18),*range(19,23))) or values[6] not in (3,12) or values[18]>1:raise ValueError('Invalid reset CPU record range')
    return records

def compare(actual,expected,spans):
    validate(actual,spans);validate(expected,spans)
    transitions=[]
    for span in spans:
        previous_divisor=None;tick_offset=0
        for i in range(span['start'],span['start']+span['records']):
            adjusted=expected[i]
            if adjusted['kind']=='cpu':
                # Existing explicitly documented split-cycle CSL/CSH profile:
                # Gear changes the divisor for the entire instruction. The
                # toolkit keeps its first two cycles at the entry divisor.
                divisor=adjusted['values'][6]
                if previous_divisor is not None and divisor!=previous_divisor:
                    delta=2*(previous_divisor-divisor);tick_offset+=delta
                    transitions.append(dict(case=span['id'],record=i-span['start'],entry_divisor=previous_divisor,next_divisor=divisor,tool_minus_gear_ticks=delta,cumulative_difference=tick_offset))
                previous_divisor=divisor
                adjusted=dict(kind=adjusted['kind'],values=list(adjusted['values']))
                adjusted['values'][7]+=tick_offset
            if actual[i]!=adjusted:
                record=actual[i];fields=CPU_FIELDS if record['kind']=='cpu' else DEVICE_FIELDS if record['kind']=='devices' else ()
                differences=[fields[j] if fields else str(j) for j,(a,b) in enumerate(zip(record['values'],adjusted['values'])) if a!=b]
                return dict(case=span['id'],record=i-span['start'],fields=differences,actual=actual[i],expected=expected[i],selected_timing_expected=adjusted),transitions
    return None,transitions

def authored_expectations(records,cases):
    """Independent fixture expectations in addition to emulator agreement."""
    _,spans=serialize(cases);validate(records,spans);checks=0
    image=authored_rom()
    for case,span in zip(cases,spans):
        index=span['start'];profile=0;ram={};unlocked=True
        for op in case['operations']:
            code=op[0]
            if code=='r':
                _,profile,region,vector,fill,mpr,ramfill=op;ram={};unlocked=True
                rom=bytearray(image);rom[8190:8192]=bytes((vector&255,vector>>8))
            elif code=='s':
                value=records[index]['values'];index+=1
                expected=[vector,fill,fill,fill,fill,(fill&~0x38)|4,12,0,*([mpr]*7),0,0,255,0,0,0,0,0]
                if value!=expected:raise ValueError('Independent reset CPU seed/vector expectation: '+case['id'])
                checks+=len(expected)
            elif code=='d':index+=1
            elif code=='i':index+=op[1]
            elif code in ('q','p','w'):
                bank,offset=op[1:3]
                key=(248 if 248<=bank<=251 else bank,offset)
                writable=(128<=bank<=135 or 248<=bank<=251 or profile==1 and 104<=bank<=127)
                if bank==247:writable=unlocked and offset<2048
                if code=='w':
                    if writable:ram[key]=op[3]
                else:
                    if key in ram:value=ram[key]
                    elif bank==247:value=0x5A if unlocked and offset<2048 else 255
                    elif writable:value=ramfill
                    elif bank<128:value=rom[(bank%32)*8192+offset]
                    else:value=255
                    if records[index]['values']!=[bank,offset,value]:raise ValueError('Independent authored memory expectation: '+case['id']+' '+str(op))
                    index+=1;checks+=1
            elif code=='c':
                if op[1]==7:unlocked=bool(op[2]&128)
            elif code=='a':
                value=(0,170,85,3)[op[1]-192] if profile else 255
                if records[index]['values']!=[op[1],value]:raise ValueError('Independent hardware signature expectation')
                index+=1;checks+=1
        if index!=span['start']+span['records']:raise ValueError('Fixture span accounting changed')
    return checks

def run(args):
    checkout,out,probe=args.gear_source.resolve(),args.out.resolve(),args.probe.resolve()
    compiler_name=shutil.which(str(args.compiler))
    libraries=[p.resolve() for p in args.library]
    if out.exists() or not compiler_name or not probe.is_file() or not libraries or any(not p.is_file() for p in libraries):raise ValueError('Require fresh output, compiler, actual built probe and external libraries')
    compiler=Path(compiler_name).resolve();source=reference.source_binding(checkout);cpp,c=reference.compile_sources(checkout,source)
    wrapper=ROOT/'tests/geargrafx_reset_probe.cpp';cpp.append(wrapper)
    authored=[Path(__file__).resolve(),ROOT/'scripts/filtered_audio_reference.py',ROOT/'scripts/psg_reference.py',wrapper,ROOT/'tests/reset_oracle_probe.cpp',ROOT/'tests/reset_probe_support.hpp']
    authored.extend(sorted((ROOT/'runtime').rglob('*.cpp')));authored.extend(sorted((ROOT/'runtime/include').rglob('*.hpp')))
    bindings=dict(reference_sources={str(checkout/name):value for name,value in source.items()},external_libraries={str(p):sha(p) for p in libraries},
                  tools={str(compiler):sha(compiler),str(probe):sha(probe)},authored_sources={str(p):sha(p) for p in authored})
    report=dict(schema=1,result='incomplete',oracle_commit=reference.COMMIT,bindings=bindings,commands=[],scope='Selected deterministic cold-boot seeds, explicit SystemCard hardware and authored early instruction/memory fixtures; actual external unchanged Gear core.',
                not_checked=['Electrical power-on values','Warm/live reset','Retail firmware or game boot','Native translation coverage','CPU bus-phase or physical VRAM contention'])
    out.mkdir(parents=True);objects=out/'objects';objects.mkdir();archive=out/'authored';archive.mkdir();epochs=[]
    for path in authored:
        name=path.relative_to(ROOT);saved=archive/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,saved)
        epochs.append(dict(original=str(path),sha256=sha(path),preserved=str(saved)))
    report['source_epoch_mappings']=epochs
    oracle=out/('gear-reset.exe' if os.name=='nt' else 'gear-reset');deps=checkout/'platforms/shared/dependencies'
    common=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_DISASSEMBLER','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for include in (checkout/'src',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):common+=['-I',str(include)]
    jobs=[]
    for i,path in enumerate(cpp+c):
        target=objects/(f'{i:02}-'+path.stem+'.o')
        command=[str(compiler),*common,'-x','c++' if path.suffix=='.cpp' else 'c',*(['-std=c++20','-include','cerrno'] if path.suffix=='.cpp' else ['-std=c11']),'-c',str(path),'-o',str(target)]
        jobs.append((command,target))
    report['commands']=[command for command,_ in jobs]
    try:
        def compile_one(item):
            command,target=item;result=subprocess.run(command,capture_output=True,text=True,timeout=180)
            target.with_suffix('.log').write_text(result.stdout+result.stderr,encoding='utf-8');result.check_returncode()
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(compile_one,jobs))
        link=[str(compiler),*[str(p) for _,p in jobs],*map(str,libraries),'-Wl,--gc-sections','-o',str(oracle)]
        report['commands'].append(link);result=subprocess.run(link,capture_output=True,text=True,timeout=90)
        (out/'link.log').write_text(result.stdout+result.stderr,encoding='utf-8');result.check_returncode()
        bindings['oracle_binary']={str(oracle):sha(oracle)};bindings['compiled_objects']={str(p):sha(p) for _,p in jobs}
        cases=plans();text,spans=serialize(cases);plan=out/'reset.plan';plan.write_text(text,encoding='ascii')
        rom=out/'authored-system-card.pce';rom.write_bytes(authored_rom())
        sectors=out/'authored-sectors.bin';sectors.write_bytes(bytes(2048*16))
        cue=out/'authored.cue';cue.write_text('FILE "authored-sectors.bin" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n',encoding='ascii')
        casepath=out/'cases.json';casepath.write_text(json.dumps(spans,indent=2)+'\n',encoding='utf-8')
        bindings['authored_fixtures']={str(p):sha(p) for p in (plan,rom,sectors,cue,casepath)};outputs={}
        for label,binary in (('gear',oracle),('tool',probe)):
            command=list(map(str,(binary,plan,rom,cue)));report['commands'].append(command)
            result=subprocess.run(command,capture_output=True,text=True,timeout=180)
            err=out/(label+'.stderr');err.write_text(result.stderr,encoding='utf-8');bindings.setdefault('raw_outputs',{})[str(err)]=sha(err)
            result.check_returncode();path=out/(label+'.json');path.write_text(result.stdout,encoding='ascii');bindings['raw_outputs'][str(path)]=sha(path)
            outputs[label]=validate(json.loads(result.stdout),spans)
        mismatch,transitions=compare(outputs['tool'],outputs['gear'],spans)
        report.update(cases=len(cases),checkpoints=len(outputs['gear']),mismatch=mismatch,
                      established_split_cycle_speed_differences=transitions,
                      independent_expected_checks={label:authored_expectations(records,cases) for label,records in outputs.items()},result='fail' if mismatch else 'pass')
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:
        reference.record_preservation(report,bindings)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('bindings','commands','source_epoch_mappings')},indent=2))
    if report['result']!='pass':raise ValueError('Independent reset comparison failed')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--gear-source',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--compiler',default='g++');parser.add_argument('--library',type=Path,action='append',default=[])
    try:run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:print(error,file=sys.stderr);raise SystemExit(1)
