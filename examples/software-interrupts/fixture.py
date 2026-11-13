"""Original nested BRK/RTI fixture and all-byte saved-status expectations."""
M0=(0,)*8
M1=(0,248,0,0,0,0,0,0)
M2=(0,248,251,0,0,0,0,0)
M3=(*M2[:7],248)
M4=(0,251,251,0,0,0,0,248)
M5=(0,251,2,0,0,0,0,248)
MX=(0,248,251,0,0,0,0,3)
WRAM_RANGES=((0,3),(0x1FF6,2))
ROM_RANGES=((0x4080,1),)
VECTOR_RANGES=((0x1FF6,2),(0x7FF6,2))
SP_VALUES=(0,1,254,255)

def physical(pc,mpr):return (mpr[pc//8192]<<13)|(pc%8192)
def rows(pc,specs):
    result=[]
    for label,mpr,text,cycles in specs:
        code=bytes.fromhex(text);result.append(dict(label=label,pc=pc,mpr=mpr,code=code,cycles=cycles));pc+=len(code)
    return result

PREFIX=rows(0xC200,[('ram-value',M0,'A9 F8',2),('ram',M0,'53 02',5),
    ('alias-value',M1,'A9 FB',2),('alias',M1,'53 04',5),('status-value',M2,'A9 0D',2),
    ('status-push',M2,'48',3),('status',M2,'28',4),('x',M2,'A2 03',2),('y',M2,'A0 04',2),
    ('a',M2,'A9 42',2),('save-a',M2,'48',3),('call',M2,'20 80 C0',7)])
SUB=rows(0xC080,[('transfer',M2,'F4',2),('outer-brk',M2,'00 EA',8)])
HANDLER=rows(0xC300,[('save-a',M2,'48',3),('save-x',M2,'DA',3),('save-y',M2,'5A',3),('save-p',M2,'08',3),
    ('vector-low',M2,'A9 00',2),('write-low',M2,'8D F6 3F',5),('vector-high',M2,'A9 C4',2),('write-high',M2,'8D F7 3F',5),
    ('vector-bank',M2,'A9 F8',2),('map-vector',M2,'53 80',5),('stack-alias',M3,'A9 FB',2),('map-alias',M3,'53 02',5),
    ('transfer',M4,'F4',2),('nested-brk',M4,'00 EA',8)])
NESTED=rows(0xC400,[('data',M4,'A9 09',2),('store',M4,'8D 01 20',5),('change-x',M4,'A2 07',2),('change-y',M4,'A0 08',2),
    ('data-bank',M4,'A9 02',2),('map-data',M4,'53 04',5),('clear-c',M5,'18',2),('clear-d',M5,'D8',2),('nested-rti',M5,'40',7)])
RESTORE=rows(HANDLER[-1]['pc']+2,[('restore-p',M5,'28',4),('restore-y',M5,'7A',4),('restore-x',M5,'FA',4),('restore-a',M5,'68',4),('outer-rti',M5,'40',7)])
RETURN=rows(SUB[-1]['pc']+2,[('return',M5,'60',7)])
SUFFIX=rows(PREFIX[-1]['pc']+3,[('restore-a',M5,'68',4),('store-a',M5,'8D 00 20',5),('load-data',M5,'AD 80 40',5),
    ('decimal-add',M5,'69 00',3),('store-result',M5,'8D 02 20',5),('end',M5,'80 FE',4)])
MAIN=PREFIX+SUB+HANDLER+NESTED+RESTORE+RETURN+SUFFIX
END=SUFFIX[-1]['pc'];MAIN_STEPS=len(MAIN);MAIN_CYCLES=sum(r['cycles'] for r in MAIN)
NEGATIVE_STEPS=len(PREFIX)+len(SUB)+len(HANDLER)
WRITE_PC=HANDLER[-1]['pc']

def main_ram(changed=False):
    # Literal stack ledger follows real high/low/status push order. Values are
    # authored program constants; no toolkit CPU/evaluator/decoder is used.
    ram=bytearray(8192);sp=0
    def push(value):
        nonlocal sp
        ram[256+sp]=value;sp=(sp-1)%256
    def pop(count):
        nonlocal sp
        sp=(sp+count)%256
    push(0x0D);pop(1);push(0x42)
    resume=SUFFIX[0]['pc'];push((resume-1)//256);push((resume-1)%256)
    resume=RETURN[0]['pc'];push(resume//256);push(resume%256);push(0x1D)
    for value in (0x42,3,4,0x15):push(value)
    ram[0x1FF6]=0x80 if changed else 0;ram[0x1FF7]=0xC4
    resume=RESTORE[0]['pc'];push(resume//256);push(resume%256);push(0x95)
    if not changed:
        ram[1]=9;pop(3);pop(4);pop(3);pop(2);pop(1);assert sp==0
        ram[0]=0x42;ram[2]=0x10
    return bytes(ram)

def fixture():
    rom=bytearray([0xEA]*32768);rom[0x1FFE:0x2000]=bytes.fromhex('00 C2')
    rom[0x1FF6:0x1FF8]=bytes.fromhex('00 C3');rom[0x7FF6:0x7FF8]=bytes.fromhex('00 C7');rom[0x4080]=9
    for row in MAIN:
        off=physical(row['pc'],row['mpr']);rom[off:off+len(row['code'])]=row['code']
    handler=rows(0xC700,[('inx',MX,'E8',2),('iny',MX,'C8',2),('cld',MX,'D8',2),('clc',MX,'18',2),('clv',MX,'B8',2),('sei',MX,'78',2),('rti',MX,'40',7)])
    for row in handler:
        off=physical(row['pc'],MX);rom[off:off+len(row['code'])]=row['code']
    cases=[]
    for status in range(256):
        pc=0xC800+16*status
        prefix=rows(pc,[('x',MX,'A2 00',2),('y',MX,'A0 00',2),('status-value',MX,f'A9 {status:02X}',2),
            ('push',MX,'48',3),('status',MX,'28',4),('brk',MX,'00 EA',8),('condition',MX,'B0 02',4 if status&1 else 2)])
        ends=rows(pc+12,[('clear-end',MX,'80 FE',4),('set-end',MX,'80 FE',4)])
        plan=prefix[:-1]+handler+[prefix[-1],ends[status&1]]
        for row in prefix+ends:
            off=physical(row['pc'],MX);rom[off:off+len(row['code'])]=row['code']
        cases.append(dict(status=status,pc=pc,end=ends[status&1]['pc'],mpr=MX,a=status,x=1,y=1,p=status&0xCF,
            cycles=sum(row['cycles'] for row in plan),steps=len(plan),plan=plan))
    return bytes(rom),cases

def case_ram(case,sp):
    ram=bytearray(8192);resume=case['pc']+10
    for value in (resume//256,resume%256,(case['status']|16)&~32):
        ram[256+sp]=value;sp=(sp-1)%256
    return bytes(ram)

def plan():return MAIN+[row for case in fixture()[1] for row in case['plan']]
def code_ranges():
    spans={}
    for row in plan():
        start=physical(row['pc'],row['mpr']);end=start+len(row['code']);bank=start//8192
        if bank in spans:spans[bank]=[min(start,spans[bank][0]),max(end,spans[bank][1])]
        else:spans[bank]=[start,end]
    # Include both authored branch endpoints, though only the proven arm is
    # derived for a given saved status. A live changed status must remain dynamic.
    spans[0][1]=max(spans[0][1],0x1800)
    return [(start,end-start) for start,end in sorted(spans.values())]
