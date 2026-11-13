"""Authored RAM payload / System Card source bytes and literal execution plans."""
VARIANTS=('cd-ram','work-ram','system-standard','system-super')
DEFAULT=(255,248,128,129,130,131,132,0)


def case(variant,bank=None):
    bios=variant.startswith('system-');work=variant=='work-ram'
    bank=(0 if bios else 248 if work else 128) if bank is None else bank
    pc=0xE200 if bios else 0x2800 if work else 0x4000
    mpr=list((0,)*8 if bios else DEFAULT);mpr[7 if bios else 1 if work else 2]=bank
    initial=tuple(mpr);mapped=tuple(248 if i==1 else v for i,v in enumerate(mpr))
    tag=9+(bank%32 if bios else 0 if work else bank-128)
    rows=[]
    def add(start,specs):
        result=[]
        for text,cost in specs:
            code=bytes.fromhex(text);result.append(dict(pc=start,mpr=initial if len(rows)+len(result)<5 else mapped,code=code,cycles=cost));start+=len(code)
        rows.extend(result);return start
    sub=pc+64
    resume=add(pc,[('54',3),('A2 FF',2),('9A',2),('A9 F8',2),('53 02',5),('A9 42',2),('8D 00 20',5),('A2 03',2),('A0 04',2),('48',3),('DA',3),('5A',3),(f'20 {sub&255:02X} {sub>>8:02X}',7)])
    add(sub,[(f'A9 {tag:02X}',2),('8D 01 20',5),('18',2),('60',7)])
    add(resume,[('7A',4),('FA',4),('68',4),('69 01',2),('8D 02 20',5),('80 FE',4)])
    cycles=sum(row['cycles'] for row in rows)
    return dict(bank=bank,pc=pc,initial_mpr=initial,final_mpr=mapped,plan=rows,end=rows[-1]['pc'],
        steps=len(rows),cycles=cycles,ticks=12*cycles-(0 if bios else 18),resume=resume,
        initial_sp=0 if bios else 255,clock_divisor=12 if bios else 3,tag=tag)


def banks(variant):
    return list(range(128 if variant=='system-standard' else 104)) if variant.startswith('system-') else list(range(248,252) if variant=='work-ram' else range(128,136))


def fixture(variant):
    if variant not in VARIANTS:raise ValueError('Unknown authored boot source')
    bios=variant.startswith('system-');work=variant=='work-ram';cases=[case(variant,bank) for bank in banks(variant)]
    raw=bytearray(262144 if bios else 128 if work else 65536)
    for c in cases:
        for row in c['plan']:
            for i,value in enumerate(row['code']):
                address=(row['pc']+i)&65535;physical=row['mpr'][address//8192]*8192+(address%8192)
                offset=physical&0x3FFFF if bios else (physical%8192)-0x800 if work else physical-0x100000
                raw[offset]=value
    if bios:raw[8190:8192]=bytes.fromhex('00 E2')
    source=dict(kind='system-card',profile=variant.split('-')[1]) if bios else dict(kind='payload',physical_load=0x1F0800 if work else 0x100000)
    return bytes(raw),source,cases


def expected_ram(variant,c):
    raw,_,_=fixture(variant);ram=bytearray(8192)
    if variant=='work-ram':ram[0x800:0x800+len(raw)]=raw
    ram[:3]=bytes((0x42,c['tag'],0x43));resume=c['resume']-1
    ram[0x1FB:0x200]=bytes((resume&255,resume>>8,4,3,0x42))
    return bytes(ram)


def cpu_states(c):
    """Literal per-position ledger; no decoder, evaluator or CPU implementation."""
    values=dict(a=0,x=0,y=0,sp=c['initial_sp'],p=4);states=[]
    updates={1:dict(x=255,p=0x84),2:dict(sp=255),3:dict(a=248,p=0x84),
        5:dict(a=0x42,p=4),7:dict(x=3),8:dict(y=4),9:dict(sp=254),10:dict(sp=253),
        11:dict(sp=252),12:dict(sp=250),13:dict(a=c['tag']),16:dict(sp=252),
        17:dict(sp=253),18:dict(sp=254),19:dict(sp=255,a=0x42),20:dict(a=0x43)}
    for i,row in enumerate(c['plan']):
        states.append(dict(pc=row['pc'],mpr=list(row['mpr']),**values));values.update(updates.get(i,{}))
    states.append(dict(pc=c['end'],mpr=list(c['final_mpr']),**values));return states
