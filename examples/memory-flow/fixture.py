"""Authored copy/table fixture; expectations do not use toolkit semantics.

Each matrix case is a separately declared reset/preset window. Address pairs
use closed-form byte indices and expected RAM applies writes in byte order.
"""
M0=(0,)*8
M1=(0,248,0,0,0,0,0,0)
M2=(0,248,251,0,0,0,0,0)
M3=(0,248,251,3,0,0,0,0)
M4=(*M3[:7],2)
ROM_RANGES=((0,2),(0x180,2),(0x1FFE,2),(0x6080,16))
WRAM_RANGES=((0,256),)
OPS=(('TII',0x73),('TDD',0xC3),('TIA',0xE3),('TAI',0xF3),('TIN',0xD3))

def physical(pc,mpr):return (mpr[pc>>13]<<13)|(pc&8191)

def rows(pc,specs):
    result=[]
    for label,mpr,code,cycles in specs:
        code=bytes.fromhex(code) if isinstance(code,str) else code
        result.append(dict(label=label,pc=pc,mpr=mpr,code=code,cycles=cycles));pc+=len(code)
    return result

PREFIX=rows(0xE200,[('wram-value',M0,'A9 F8',2),('wram',M0,'53 02',5),
    ('alias-value',M1,'A9 FB',2),('alias',M1,'53 04',5),('rom-value',M2,'A9 03',2),('rom',M2,'53 08',5),
    ('save-x',M3,'DA',3),('index',M3,'A2 00',2),('value',M3,'A9 E2',2),
    ('safe-indexed-write',M3,'9D 00 40',5),('copy',M3,'F3 80 E1 00 20 00 01',1553),
    ('restore-x',M3,'FA',4),('jump',M3,'7C FF 1F',7)])
HANDLER=rows(0xE2E2,[('bank',M3,'A9 02',2),('map',M3,'53 80',5)])
SUFFIX=rows(0xE2E6,[('result',M4,'A9 42',2),('store',M4,'8D 01 20',5),('end',M4,'80 FE',4)])
MAIN=PREFIX+HANDLER+SUFFIX
END=SUFFIX[-1]['pc'];MAIN_STEPS=len(MAIN);MAIN_CYCLES=sum(r['cycles'] for r in MAIN)
POINTER_STEPS=len(PREFIX);JUMP_PC=PREFIX[-1]['pc']

def main_ram(index=0,changed=False):
    ram=bytearray(8192);ram[:256]=bytes([0xE2])*256
    ram[0x100]=index;ram[0x1FE]=0xE2
    if changed:ram[0]=0xE3
    else:ram[1]=0x42
    return bytes(ram)

def copy_bytes(op,source,destination,count):
    return bytes([op])+source.to_bytes(2,'little')+destination.to_bytes(2,'little')+count.to_bytes(2,'little')

def fixture(profile='base'):
    if profile not in ('base','sf2'):raise ValueError('profile')
    rom=bytearray([0xEA]*(0x280000 if profile=='sf2' else 32768))
    for row in MAIN:
        off=physical(row['pc'],row['mpr']);rom[off:off+len(row['code'])]=row['code']
    rom[0x1FFE:0x2000]=bytes.fromhex('00 E2');rom[0x180:0x182]=b'\xE2\xE2'
    rom[0x6080:0x6090]=bytes(range(1,17))
    geometries=[]
    for name,op in OPS:
        for count in (1,2,3,7,8,16):
            geometries.append((name,op,0x6080+count-1 if name=='TDD' else 0x6080,
                0x2040+count-1 if name=='TDD' else 0x2040,count,'disjoint'))
        for source,destination in ((0x2020,0x2021),(0x2021,0x2020)):
            geometries.append((name,op,source+6 if name=='TDD' else source,
                destination+6 if name=='TDD' else destination,7,'overlap'))
        geometries.append((name,op,0x4020+6 if name=='TDD' else 0x4020,
            0x2021+6 if name=='TDD' else 0x2021,7,'alias'))
        geometries.append((name,op,0 if name=='TDD' else 0xFFFF,
            0x2046 if name=='TDD' else 0x2040,3,'word-wrap'))
    cases=[]
    for i,(name,op,source,destination,count,kind) in enumerate(geometries):
        specs=[('a',M3,'A9 55',2),('x',M3,'A2 33',2),('y',M3,'A0 44',2),
            ('decimal',M3,'D8',2),('carry',M3,'18',2),('overflow',M3,'B8',2),
            ('initialize',M3,copy_bytes(0x73,0x6080,0x2020,16),113),
            (name,M3,copy_bytes(op,source,destination,count),17+6*count),('end',M3,'80 FE',4)]
        plan=rows(0xE400+64*i,specs)
        for row in plan:
            off=physical(row['pc'],row['mpr']);rom[off:off+len(row['code'])]=row['code']
        cases.append(dict(name=name,kind=kind,source=source,destination=destination,length=count,
            pc=plan[0]['pc'],end=plan[-1]['pc'],mpr=M3,a=0x55,x=0x33,y=0x44,p=4,
            cycles=sum(r['cycles'] for r in plan),steps=len(plan),plan=plan))
    # Literal closed-form sequences, independent of discovery/runtime helpers.
    for case in cases:
        ram=bytearray(8192);ram[0x20:0x30]=bytes(range(1,17))
        ram[0x100]=0x44;ram[0x1FF]=0x55;ram[0x1FE]=0x33
        for i in range(case['length']):
            name=case['name']
            s=(case['source']+(-i if name=='TDD' else i%2 if name=='TAI' else i))%65536
            d=(case['destination']+(-i if name=='TDD' else i%2 if name=='TIA' else 0 if name=='TIN' else i))%65536
            bank=M3[s//8192];offset=s%8192
            value=ram[offset] if bank in (248,249,250,251) else rom[bank*8192+offset]
            if M3[d//8192] in (248,249,250,251):ram[d%8192]=value
        case['ram']=bytes(ram)
    return bytes(rom),cases

def plan():
    return [(r['pc'],r['mpr'],r['code']) for r in MAIN]+[
        (r['pc'],r['mpr'],r['code']) for case in fixture()[1] for r in case['plan']]

def code_ranges():
    result=[]
    for start,end in sorted((physical(pc,mpr),physical(pc,mpr)+len(code)) for pc,mpr,code in plan()):
        if result and start<=result[-1][1]:result[-1][1]=max(end,result[-1][1])
        else:result.append([start,end])
    return [(start,end-start) for start,end in result]
