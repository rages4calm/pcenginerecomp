"""Original source-qualified conditional routes; no game/firmware bytes."""
M0=(0,)*8
M1=(0,248,0,0,0,0,0,0)
M2=(0,248,1,0,0,0,0,0)
M3=(0,248,1,0,0,0,0,2)
MB=(0,0,0,248,0,0,0,0)
DATA_RANGES=((0x80,32),(0x100,2),(0x2080,1),(0x4180,1),(0x600,64))

def physical(pc,mpr):return (mpr[pc>>13]<<13)|(pc&8191)

def assemble(rows,start):
    labels={};pc=start
    for label,mpr,text,cycles,dest in rows:labels[label]=pc;pc+=len(bytes.fromhex(text))
    result=[]
    for label,mpr,text,cycles,dest in rows:
        code=bytearray.fromhex(text)
        if dest:
            delta=labels[dest]-(labels[label]+len(code));assert -128<=delta<=127;code[-1]=delta&255
        result.append(dict(label=label,pc=labels[label],mpr=mpr,code=bytes(code),cycles=cycles))
    return result,labels

MAIN_ROWS=[('a',M0,'A9 F8',2,None),('wram',M0,'53 02',5,None),
 ('bank',M1,'AD 00 E1',5,None),('cmp',M1,'C9 02',2,None),('bc',M1,'90 00',2,'badbank'),
 ('bank1',M1,'A9 01',2,None),('skipbank',M1,'80 00',4,'map2'),('badbank',M1,'A9 03',2,None),
 ('map2',M1,'53 04',5,None),('x',M2,'AE 80 40',5,None),('decimal',M2,'D8',2,None),('carry',M2,'18',2,None),
 ('sign',M2,'AD 01 E1',5,None),('add',M2,'69 01',2,None),('bv',M2,'70 00',4,'bank2'),
 ('badcodebank',M2,'A9 03',2,None),('skipcodebank',M2,'80 00',4,'map7'),('bank2',M2,'A9 02',2,None),
 ('map7',M2,'53 80',5,None),('y',M3,'A0 03',2,None),('call',M3,'20 00 E2',7,None),('end',M3,'80 FE',4,None)]
BODY_ROWS=[('load',M3,'AD 80 E1',5,None),('xor',M3,'49 FF',2,None),('dynamic',M3,'8D 03 20',5,None),
 ('bn',M3,'30 00',4,'yes'),('badresult',M3,'A9 01',2,None),('skipresult',M3,'80 00',4,'store'),
 ('yes',M3,'A9 42',2,None),('store',M3,'8D 00 20',5,None),('storex',M3,'8E 01 20',5,None),
 ('storey',M3,'8C 02 20',5,None),('return',M3,'60',7,None)]
MAIN_ALL,LABELS=assemble(MAIN_ROWS,0xE000)
BODY_ALL,BODY_LABELS=assemble(BODY_ROWS,0xE200)
_main=[r for r in MAIN_ALL if r['label'] not in ('badbank','badcodebank','skipcodebank','end')]
_body=[r for r in BODY_ALL if r['label'] not in ('badresult','skipresult')]
MAIN=_main+_body+[MAIN_ALL[-1]]
assert len(MAIN)==28 and sum(r['cycles'] for r in MAIN)==107

def fixture():
    rom=bytearray([0xEA]*32768)
    for r in MAIN_ALL+BODY_ALL:
        off=physical(r['pc'],r['mpr']);rom[off:off+len(r['code'])]=r['code']
    rom[0x100:0x102]=bytes([2,0x7F]);rom[0x2080]=2;rom[0x4180]=0x41;rom[0x1FFE:0x2000]=bytes.fromhex('00 E0')
    specs=[]
    for name,opcode,flag,expected in (('BCC',0x90,'c',0),('BCS',0xB0,'c',1),('BEQ',0xF0,'z',1),('BNE',0xD0,'z',0),('BMI',0x30,'n',1),('BPL',0x10,'n',0),('BVS',0x70,'v',1),('BVC',0x50,'v',0)):
        for variant in range(8):specs.append((name,opcode,flag,expected,variant))
    for bit in range(8):
        for expected in (0,1):
            for value in (0,1):specs.append((f'BBS{bit}' if expected else f'BBR{bit}',(0x8F if expected else 0x0F)+bit*16,'bit',expected,value))
    cases=[]
    for index,(name,opcode,flag,expected,variant) in enumerate(specs):
        pc=0xE800+index*32;bit=flag=='bit';mpr=MB if bit else M1
        parts=[bytes.fromhex('A2 07'),bytes.fromhex('A0 03'),b'\xD8',b'\x18',b'\xB8'];costs=[2]*5
        c=v=0;extra=None
        if bit:
            a=0x55;data=(variant<<int(name[-1]));direct=0x80+index-64;rom[direct]=data
            value=variant;parts.append(bytes([0xA9,a]));costs.append(2)
        else:
            value=variant%2;choice=variant//2
            if flag=='c':a=(0,1,128,255)[choice] if value else (0,1,127,254)[choice];right=a if value else a+1;extra=bytes([0xC9,right])
            elif flag=='n':a=(128,129,254,255)[choice] if value else (0,1,2,127)[choice]
            elif flag=='z':a=0 if value else (1,127,128,255)[choice]
            else:
                a,right=(((127,1),(64,64),(128,128),(255,128)) if value else ((0,0),(0,1),(255,1),(128,127)))[choice]
                extra=bytes([0x69,right])
            if variant&2:rom[0x600+index]=a;parts.append(bytes([0xAD,index,0xE6]));costs.append(5)
            else:parts.append(bytes([0xA9,a]));costs.append(2)
        n=int(a>=128);z=int(a==0)
        if extra:
            parts.append(extra);costs.append(2)
            if extra[0]==0xC9:diff=(a-right)%256;c=int(a>=right);n=int(diff>=128);z=int(diff==0)
            else:
                total=a+right;byte=total%256;c=int(total>255);v=int(bool(~(a^right)&(a^byte)&128));a=byte;n=int(a>=128);z=int(a==0)
        taken=value==expected;condition_pc=pc+sum(map(len,parts));flags=4|c|v*64|n*128|z*2
        parts.append(bytes([opcode,direct,4]) if bit else bytes([opcode,4]))
        fall=condition_pc+len(parts[-1]);target=fall+4;store=target+2
        parts.extend([bytes.fromhex('A2 11'),bytes.fromhex('80 02'),bytes.fromhex('A2 22'),bytes([0x8E,0,0x60 if bit else 0x20]),bytes.fromhex('80 FE')])
        code=b''.join(parts);assert len(code)<=32;rom[pc&8191:(pc&8191)+len(code)]=code
        branch_cost=(8 if taken else 6) if bit else (4 if taken else 2)
        cycles=sum(costs)+branch_cost+2+(0 if taken else 4)+5+4
        # Literal selected operation plan; no runtime/decoder/discovery functions.
        selected=[];cursor=pc
        for part in parts[:len(costs)]:selected.append((cursor,mpr,part));cursor+=len(part)
        selected.append((condition_pc,mpr,parts[len(costs)]))
        if taken:selected.append((target,mpr,bytes.fromhex('A2 22')))
        else:selected.extend([(fall,mpr,bytes.fromhex('A2 11')),(fall+2,mpr,bytes.fromhex('80 02'))])
        selected.extend([(store,mpr,parts[-2]),(store+3,mpr,parts[-1])])
        cases.append(dict(pc=pc,mpr=mpr,code=list(code),a=a,x=0x22 if taken else 0x11,y=3,p=flags&~130,
            flags=flags,condition_pc=condition_pc,after_branch=target if taken else fall,taken=taken,
            cycles=cycles,steps=len(selected),prefix=len(costs),end=store+3,name=name,bit=bit,plan=selected))
    assert len(cases)==96
    return bytes(rom),cases

def plan():
    return [(r['pc'],r['mpr'],r['code']) for r in MAIN]+[r for c in fixture()[1] for r in c['plan']]

def code_ranges():
    ranges=[]
    for r in MAIN_ALL+BODY_ALL:ranges.append((physical(r['pc'],r['mpr']),len(r['code'])))
    return ranges+[(0x800,96*32)]
