"""Original SF2 latch fixture; closed-form expectations, no runtime helpers."""
M0=(0,)*8
M1=(0,248,0,0,0,0,0,0)
M2=(0,248,251,0,0,0,0,0)
M3=(0,248,251,0,0,64,0,0)
MW=(*M3[:7],64)
WRAM_RANGES=((0,8),)
ROM_RANGES=((0x1FF0,16),*[(0x80000+window*0x80000,1) for window in range(4)],
    *[(0x80080+window*0x80000,16) for window in range(4)],
    *[(0x800C0+window*0x80000,1) for window in range(4)])
OPS=(('TII',0x73),('TDD',0xC3),('TIA',0xE3),('TAI',0xF3),('TIN',0xD3))

def physical(pc,mpr):return (mpr[pc>>13]<<13)|(pc&8191)
def rom_offset(pc,mpr,selector):
    address=physical(pc,mpr)
    return address+(selector%4)*0x80000 if 0x80000<=address<0x100000 else address

def rows(pc,specs):
    result=[]
    for label,mpr,selector,code,cycles in specs:
        code=bytes.fromhex(code) if isinstance(code,str) else code
        result.append(dict(label=label,pc=pc,mpr=mpr,selector=selector,code=code,cycles=cycles));pc+=len(code)
    return result

PREFIX=rows(0xE200,[('wram-value',M0,0,'A9 F8',2),('wram',M0,0,'53 02',5),
    ('alias-value',M1,0,'A9 FB',2),('alias',M1,0,'53 04',5),
    ('window-value',M2,0,'A9 40',2),('window',M2,0,'53 20',5),
    ('index',M3,0,'A2 01',2),('select',M3,0,'9D F0 1F',5),
    ('load-window',M3,1,'AD 00 A0',5),('code-window',M3,1,'53 80',5)])
PREFIX+=rows(PREFIX[-1]['pc']+2,[('jump',MW,1,'4C 00 E3',4)])
COPY=rows(0xE300,[('copy',MW,1,'73 80 A0 FE 1F 04 00',41)])
MIDDLE=rows(0xE307,[('copied-value',MW,15,'AD 00 20',5),('select-zero',MW,15,'8D F0 1F',5)])
SUFFIX=rows(0xE30D,[('result',MW,0,'A9 42',2),('store',MW,0,'8D 02 20',5),('end',MW,0,'80 FE',4)])
MAIN=PREFIX+COPY+MIDDLE+SUFFIX
END=SUFFIX[-1]['pc'];MAIN_STEPS=len(MAIN);MAIN_CYCLES=sum(r['cycles'] for r in MAIN)
NEGATIVE_STEPS=len(PREFIX)-1;WRITE_PC=next(r['pc'] for r in PREFIX if r['label']=='select')
NEGATIVE_PC=PREFIX[-1]['pc']

def main_ram():
    ram=bytearray(8192);ram[:3]=bytes([42,43,66]);ram[0x1FF]=64;ram[0x1FE]=1
    return bytes(ram)

def block(op,source,dest,count):return bytes([op])+source.to_bytes(2,'little')+dest.to_bytes(2,'little')+count.to_bytes(2,'little')

def fixture():
    rom=bytearray([0xEA]*0x280000)
    rom[0x1FFE:0x2000]=bytes.fromhex('00 E2')
    for window in range(4):
        rom[0x80000+window*0x80000]=64
        rom[0x800C0+window*0x80000]=10*(window+1)
        rom[0x80080+window*0x80000:0x80090+window*0x80000]=bytes(range(10*(window+1),10*(window+1)+16))
    for row in MAIN:
        off=rom_offset(row['pc'],row['mpr'],row['selector']);rom[off:off+len(row['code'])]=row['code']
    cases=[]
    def add(specs,ram,a,x,y,p,selector,name):
        index=len(cases);mpr=(0,248,251,3,0,64,0,index//48)
        specs=specs[:-1]+[('save-status',selector,'08',3),('status-byte',selector,'68',4),
            ('status-store',selector,'8D 06 20',5),('window-witness',selector,'AD C0 A0',5),
            ('witness-store',selector,'8D 07 20',5),specs[-1]]
        ram=bytearray(ram);ram[6]=p|16;ram[7]=10*(selector%4+1);ram[0x100]=p|16
        a=ram[7];p &= 0x7D  # LDA witness clears N/Z; carry/V/D/I survive.
        plan=rows(0xE400+(index%48)*128,[(label,mpr,latch,code,cycles) for label,latch,code,cycles in specs])
        for row in plan:
            off=rom_offset(row['pc'],mpr,row['selector']);rom[off:off+len(row['code'])]=row['code']
        cases.append(dict(name=name,pc=plan[0]['pc'],end=plan[-1]['pc'],mpr=mpr,a=a,x=x,y=y,p=p,
            selector=selector,cycles=sum(r['cycles'] for r in plan),steps=len(plan),plan=plan,ram=bytes(ram)))
    def setup():return [('a',0,'A9 55',2),('x',0,'A2 33',2),('y',0,'A0 44',2),
        ('carry',0,'18',2),('decimal',0,'D8',2),('overflow',0,'B8',2)]
    scalar=(('STA',0x8D,5),('STX',0x8E,5),('STY',0x8C,5),('STZ',0x9C,5),
        ('ASL',0x0E,7),('LSR',0x4E,7),('ROL',0x2E,7),('ROR',0x6E,7),
        ('INC',0xEE,7),('DEC',0xCE,7),('TSB',0x0C,7),('TRB',0x1C,7))
    for name,op,cost in scalar:
        for selector in range(16):
            old=rom[0x1FF0+selector];c=v=0;n=z=0
            if name in ('ASL','ROL'):result=(old*2)%256;c=old//128
            elif name in ('LSR','ROR'):result=old//2;c=old%2
            elif name=='INC':result=(old+1)%256
            elif name=='DEC':result=(old-1)%256
            elif name=='TSB':result=old|0x55
            elif name=='TRB':result=old&0xAA
            else:result=None
            if name in ('TSB','TRB'):n=old//128;v=(old>>6)%2;z=int(result==0)
            elif result is not None:n=result//128;z=int(result==0)
            specs=setup()+[(name,0,bytes([op,0xF0+selector,0x1F]),cost),('end',selector,'80 FE',4)]
            add(specs,bytes(8192),0x55,0x33,0x44,4|c|z*2|v*64|n*128,selector,name)
    for name,op,cost in (('abx',0x9D,5),('aby',0x99,5),('idx',0x81,7),('idy',0x91,7),('zpi',0x92,7),('stz-abx',0x9E,5)):
        for selector in range(16):
            low=0xF0+selector;ram=bytearray(8192);ram[0]=low-1;ram[1]=0x1F;ram[3]=low;ram[4]=0x1F
            specs=[]
            for offset,value in ((0,low-1),(1,0x1F),(3,low),(4,0x1F)):
                specs += [('pointer',0,bytes([0xA9,value]),2),('pointer-write',0,bytes([0x85,offset]),4)]
            specs += [('a',0,'A9 55',2),('x',0,'A2 01',2),('y',0,'A0 01',2),('carry',0,'18',2),('decimal',0,'D8',2),('overflow',0,'B8',2)]
            code=bytes([op,low-1,0x1F]) if name in ('abx','aby','stz-abx') else bytes([op,2 if name=='idx' else 0 if name=='idy' else 3])
            specs += [(name,0,code,cost),('end',selector,'80 FE',4)]
            add(specs,ram,0x55,1,1,4,selector,name)
    for name,op in OPS:
        for initial in (0,1,2,15):
            for count in (1,2,4,7):
                for base in (0x1FF0,0x1FFE,0x9FF0,0x1FEF):
                    source=0xA080+count-1 if name=='TDD' else 0xA080
                    dest=base+count-1 if name=='TDD' else base
                    ram=bytearray(8192);ram[0x100]=0x44;ram[0x1FF]=0x55;ram[0x1FE]=0x33
                    selector=initial
                    for i in range(count):
                        s=source+(-i if name=='TDD' else i%2 if name=='TAI' else i)
                        d=dest+(-i if name=='TDD' else i%2 if name=='TIA' else 0 if name=='TIN' else i)
                        value=10*(selector%4+1)+(s-0xA080)
                        if d//8192 in (0,4) and d%8192>=0x1FF0:selector=d%16
                        elif d//8192==1:ram[d%8192]=value
                    specs=setup()+[('initial',0,bytes([0x8D,0xF0+initial,0x1F]),5),
                        (name,initial,block(op,source,dest,count),17+6*count),('end',selector,'80 FE',4)]
                    add(specs,ram,0x55,0x33,0x44,4,selector,name)
    return bytes(rom),cases

def plan():return MAIN+[r for case in fixture()[1] for r in case['plan']]
def code_ranges():
    # Explicit per-bank envelopes include authored padding, never whole-image
    # guessing. No control path traverses that padding in this fixture.
    spans={}
    for row in plan():
        start=rom_offset(row['pc'],row['mpr'],row['selector']);end=start+len(row['code']);bank=start//8192
        if bank in spans:spans[bank]=[min(spans[bank][0],start),max(spans[bank][1],end)]
        else:spans[bank]=[start,end]
    return [(start,end-start) for start,end in sorted(spans.values())]
