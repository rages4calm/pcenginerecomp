"""Original banked arithmetic route and directed register matrix."""
M0=(0,)*8
M1=(0,248,0,0,0,0,0,0)
M2=(0,248,1,0,0,0,0,0)
M3=(0,248,1,0,0,0,0,2)
MAIN=((0xE000,M0,'A9 F8'),(0xE002,M0,'53 02'),(0xE004,M1,'AD 00 E1'),
 (0xE007,M1,'29 0F'),(0xE009,M1,'0A'),(0xE00A,M1,'4A'),(0xE00B,M1,'53 04'),
 (0xE00D,M2,'AE 80 40'),(0xE010,M2,'D8'),(0xE011,M2,'18'),(0xE012,M2,'69 01'),
 (0xE014,M2,'53 80'),(0xE016,M3,'A0 03'),(0xE018,M3,'20 00 E2'),
 (0xE200,M3,'A9 50'),(0xE202,M3,'F8'),(0xE203,M3,'38'),(0xE204,M3,'ED 80 E1'),
 (0xE207,M3,'D8'),(0xE208,M3,'8D 00 20'),(0xE20B,M3,'8E 01 20'),
 (0xE20E,M3,'8C 02 20'),(0xE211,M3,'60'),(0xE01B,M3,'80 FE'))
DATA_RANGES=((0x100,1),(0x2080,1),(0x4180,1),(0x1A00,280))

def physical(pc,mpr):return (mpr[pc>>13]<<13)|(pc&8191)

def expected(name,a,b,c,d,t):
    """Separate integer/BCD expectations for actual CPU flags and T RAM writes."""
    left=0 if t and name in ('ADC','AND','ORA','EOR') else a
    flags=0x44|d*8|c;value=left
    if name in ('ADC','SBC'):
        lhs,rhs=(int(f'{left:02X}'),int(f'{b:02X}')) if d else (left,b)
        value=lhs+rhs+c if name=='ADC' else lhs-rhs-(1-c)
        carry=int(value>=(100 if d else 256)) if name=='ADC' else int(value>=0)
        byte=int(f'{value%100:02}',16) if d else value%256
        overflow=bool((left^byte)&(left^b if name=='SBC' else ~(left^b))&128)
        flags=(flags&~1)|carry
        if not d:flags=(flags&~64)|(64 if overflow else 0)
    elif name in ('AND','ORA','EOR'):
        byte=left&b if name=='AND' else left|b if name=='ORA' else left^b
    elif name in ('CMP','CPX','CPY'):
        lhs={'CMP':a,'CPX':7,'CPY':0}[name];byte=(lhs-b)%256
        flags=(flags&~1)|int(lhs>=b)
    else:
        byte={'ASL':a*2,'LSR':a//2,'ROL':a*2+c,'ROR':a//2+128*c}[name]%256
        flags=(flags&~1)|(int(a>=128) if name in ('ASL','ROL') else a%2)
    flags=(flags&~130)|(128 if byte>=128 else 0)|(2 if byte==0 else 0)
    routed=t and name in ('ADC','AND','ORA','EOR')
    return (a if routed or name in ('CMP','CPX','CPY') else byte),flags,(byte if routed else 0)

def fixture():
    rom=bytearray([0xEA]*32768)
    for pc,mpr,text in MAIN:
        code=bytes.fromhex(text);offset=physical(pc,mpr);rom[offset:offset+len(code)]=code
    rom[0x100]=0xF1;rom[0x2080]=2;rom[0x4180]=9;rom[0x1FFE:0x2000]=bytes.fromhex('00 E0')
    binary=((0,0),(0,1),(127,1),(128,128),(255,1),(255,255),(1,255),(85,170))
    bcd=((0,0),(1,9),(9,1),(0x49,0x50),(0x50,1),(0x99,1),(0x80,0x90),(0x99,0x99))
    specs=[]
    for name,opcode in (('ADC',0x69),('SBC',0xE9),('AND',0x29),('ORA',0x09),('EOR',0x49)):
        for decimal in (0,1):
            for a,b in bcd if decimal else binary:
                for carry in (0,1):specs.append((name,opcode,a,b,carry,decimal,0))
    for name,opcode in (('ADC',0x69),('AND',0x29),('ORA',0x09),('EOR',0x49)):
        for i,(a,b) in enumerate(bcd):specs.append((name,opcode,a,b,i%2,(i//2)%2,1))
    for name,opcode in (('ASL',0x0A),('LSR',0x4A),('ROL',0x2A),('ROR',0x6A)):
        for a in (0,1,127,128,255,85,170,9):
            for carry in (0,1):specs.append((name,opcode,a,0,carry,0,0))
    for name,opcode in (('CMP',0xC9),('CPX',0xE0),('CPY',0xC0)):
        for i,b in enumerate((0,1,7,9,127,128,254,255)):specs.append((name,opcode,0x80,b,i%2,i%2,0))
    cases=[]
    for index,(name,opcode,a,b,c,d,t) in enumerate(specs):
        pc=0xE400+index*16;memory=index%2==1 and name not in ('ASL','LSR','ROL','ROR')
        prefix=bytes([0xA9,a,0xA2,7,0xA0,0,0xF8 if d else 0xD8,0x38 if c else 0x18]+([0xF4] if t else []))
        address=0xFA00+index
        if memory:
            opcode={'ADC':0x6D,'SBC':0xED,'AND':0x2D,'ORA':0x0D,'EOR':0x4D,'CMP':0xCD,'CPX':0xEC,'CPY':0xCC}[name]
            op=bytes([opcode,address&255,address>>8]);rom[address&8191]=b
        else:op=bytes([opcode]) if name in ('ASL','LSR','ROL','ROR') else bytes([opcode,b])
        code=prefix+op+bytes.fromhex('80 FE');assert len(code)<=16
        offset=pc&8191;rom[offset:offset+len(code)]=code
        value,p,ram=expected(name,a,b,c,d,t)
        cycles=10+2*t+(5 if memory else 2)+4+(d if name in ('ADC','SBC') else 0)+(3 if t else 0)
        cases.append(dict(pc=pc,code=list(code),end=pc+len(code)-2,a=value,p=p,ram=ram,cycles=cycles,steps=7+t,
            name=name,input_a=a,b=b,c=c,d=d,t=t,operation_pc=pc+len(prefix),memory=memory))
    assert len(cases)==280
    return bytes(rom),cases

def plan():
    rows=[(pc,mpr,bytes.fromhex(code)) for pc,mpr,code in MAIN]
    for case in fixture()[1]:
        code=case['code'];pc=case['pc'];sizes=[2,2,2,1,1]+([1] if case['t'] else [])+[3 if case['memory'] else 1 if case['name'] in ('ASL','LSR','ROL','ROR') else 2,2]
        offset=0
        for size in sizes:rows.append((pc+offset,M1,bytes(code[offset:offset+size])));offset+=size
        assert offset==len(code)
    return rows

def code_ranges():return [(0,22),(0x4016,7),(0x4200,18),(0x400,280*16)]
