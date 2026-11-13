"""Original stack/status and banked-call fixture, independent literal endpoints."""
M0 = (0,)*8
M1 = (0,248,0,0,0,0,0,0)
M2 = (0,249,0,0,0,0,0,0)
M3 = (0,249,0,0,0,0,0,3)
M4 = (0,249,2,0,0,0,0,3)


def physical(pc,mpr): return (mpr[pc>>13]<<13)|(pc&8191)


def rows(start,specs):
    result=[];pc=start
    for label,mpr,text,cycles in specs:
        code=bytes.fromhex(text)
        result.append(dict(label=label,pc=pc,mpr=mpr,code=code,cycles=cycles));pc+=len(code)
    return result


PREFIX=rows(0xE000,[('wram-value',M0,'A9 F8',2),('wram',M0,'53 02',5),
 ('sp',M1,'A2 FF',2),('rebase',M1,'9A',2),('bank',M1,'A9 02',2),('save-a',M1,'48',3),
 ('x',M1,'A2 07',2),('save-x',M1,'DA',3),('y',M1,'A0 80',2),('save-y',M1,'5A',3),
 ('irq',M1,'78',2),('decimal',M1,'D8',2),('carry',M1,'18',2),('overflow',M1,'B8',2),
 ('zero',M1,'A9 00',2),('save-p',M1,'08',3),('call',M1,'20 00 E2',7)])
RESUME=PREFIX[-1]['pc']+3
SUFFIX=rows(RESUME,[('restore-p',M3,'28',4),('condition',M3,'D0 63',2),
 ('restore-y',M3,'7A',4),('restore-x',M3,'FA',4),('restore-a',M3,'68',4),
 ('map-bank',M3,'53 04',5),('store-a',M4,'8D 00 20',5),
 ('store-x',M4,'8E 01 20',5),('store-y',M4,'8C 02 20',5),('end',M4,'80 FE',4)])
CALLEE=rows(0xE200,[('alias-value',M1,'A9 F9',2),('alias',M1,'53 02',5),
 ('code-value',M2,'A9 03',2),('code-bank',M2,'53 80',5),
 ('clobber-a',M3,'A9 99',2),('clobber-x',M3,'A2 55',2),('clobber-y',M3,'A0 33',2),
 ('bsr',M3,'44 30',8),('return',M3,'60',7)])
SUB=rows(0xE240,[('value',M3,'A9 42',2),('store',M3,'8D 03 20',5),('return',M3,'60',7)])
assert CALLEE[-2]['pc']+2+0x30==0xE240
MAIN=PREFIX+CALLEE[:-1]+SUB+[CALLEE[-1]]+SUFFIX
END=SUFFIX[-1]['pc']
BAD=SUFFIX[1]['pc']+2+0x63
MAIN_CYCLES=sum(r['cycles'] for r in MAIN)
MAIN_STEPS=len(MAIN)


def fixture():
    rom=bytearray([0xEA]*32768)
    for row in PREFIX+SUFFIX+CALLEE+SUB:
        off=physical(row['pc'],row['mpr']);rom[off:off+len(row['code'])]=row['code']
    rom[0x1FFE:0x2000]=bytes.fromhex('00 E0')
    cases=[]
    for load,push,pop,store,register in ((0xA9,0x48,0x68,0x8D,0),(0xA2,0xDA,0xFA,0x8E,1),(0xA0,0x5A,0x7A,0x8C,2)):
        for byte in (0,1,2,127,128,129,254,255):
            parts=[bytes([load,byte]),bytes([push]),bytes([load,byte^255]),bytes([pop]),bytes([store,0,32]),bytes.fromhex('80 FE')]
            registers=[0,0,0];registers[register]=byte
            cases.append(dict(parts=parts,a=registers[0],x=registers[1],y=registers[2],
                p=4|(128 if byte>=128 else 0)|(2 if byte==0 else 0),
                stored=byte,cycles=20,register=register,status=False))
    for byte in range(256):
        stored=(byte|16)&~32
        parts=[bytes([0xA9,byte]),b'\x48',b'\x28',b'\x08',b'\x68',bytes.fromhex('8D 00 20'),bytes.fromhex('80 FE')]
        cases.append(dict(parts=parts,a=stored,x=0,y=0,p=byte&0xCD,
            stored=stored,cycles=25,register=0,status=True))
    cases.append(dict(parts=[b'\x08', b'\x68', bytes.fromhex('8D 00 20'), bytes.fromhex('80 FE')],
        a=0x14,x=0,y=0,p=4,stored=0x14,cycles=16,register=0,status=False))
    for index,case in enumerate(cases):
        pc=0xE800+index*16;plan=[]
        for code in case.pop('parts'):
            plan.append((pc,M1,code));pc+=len(code)
        case.update(pc=plan[0][0],end=plan[-1][0],steps=len(plan),mpr=M1,plan=plan)
        code=b''.join(row[2] for row in plan);assert len(code)<=16
        off=case['pc']&8191;rom[off:off+len(code)]=code
    return bytes(rom),cases


def plan(): return [(r['pc'],r['mpr'],r['code']) for r in MAIN]+[r for c in fixture()[1] for r in c['plan']]


def code_ranges(): return [(physical(r['pc'],r['mpr']),len(r['code'])) for r in PREFIX+SUFFIX+CALLEE+SUB]+[(0x800,281*16)]


def main_ram():
    ram=bytearray(8192);ram[:4]=bytes([2,7,128,66])
    ram[0x1FA:0x200]=bytes([(RESUME-1)&255,0xE0,0x16,0x80,7,2])
    ram[0x1F8:0x1FA]=bytes([(CALLEE[-1]['pc']-1)&255,0xE2])
    return bytes(ram)
