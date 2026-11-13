"""Original mutable-data and pointer fixture; no game or firmware bytes.

Expected values use literal byte/decimal arithmetic, not the toolkit decoder,
abstract evaluator or runtime. Matrix cases are separate declared reset windows.
"""
M0=(0,)*8
M1=(0,248,0,0,0,0,0,0)
M2=(0,248,251,0,0,0,0,0)
M3=(0,248,251,3,0,0,0,0)
M4=(0,248,2,3,0,0,0,0)
M5=(0,248,2,3,0,0,0,2)
WRAM_RANGES=((0,7),(0x10,2),(0x20,1),(0x30,2),(255,1))
ROM_RANGES=((0x6080,1),)

def physical(pc,mpr):return (mpr[pc>>13]<<13)|(pc&8191)

def rows(start,specs):
    result=[];pc=start
    for label,mpr,text,cycles in specs:
        code=bytes.fromhex(text);result.append(dict(label=label,pc=pc,mpr=mpr,code=code,cycles=cycles));pc+=len(code)
    return result

PREFIX=rows(0xE000,[('wram-value',M0,'A9 F8',2),('wram',M0,'53 02',5),
 ('alias-value',M1,'A9 FB',2),('alias',M1,'53 04',5),('rom-value',M2,'A9 03',2),('rom',M2,'53 08',5),
 ('jump-low',M3,'A9 40',2),('pointer-low',M3,'8D 00 40',5),('jump-high',M3,'A9 E2',2),('pointer-high',M3,'8D 01 40',5),
 ('store-low',M3,'A9 30',2),('store-pointer-low',M3,'85 02',4),('store-high',M3,'A9 20',2),('store-pointer-high',M3,'85 03',4),
 ('left',M3,'AD 80 60',5),('variable',M3,'85 20',4),('a',M3,'A9 55',2),('x',M3,'A2 20',2),
 ('decimal',M3,'D8',2),('carry',M3,'18',2),('overflow',M3,'B8',2),('transfer',M3,'F4',2),('memory-add',M3,'69 01',5),
 ('load-bank',M3,'A5 20',4),('map-data',M3,'53 04',5),('map-code',M4,'53 80',5),('call',M5,'20 00 E2',7),('jump',M5,'6C 00 20',7)])
BODY=rows(0xE200,[('value',M5,'A9 7F',2),('indirect-store',M5,'92 02',7),('increment',M5,'E6 30',6),
 ('test',M5,'24 30',4),('condition',M5,'10 72',2),('rotate',M5,'66 30',6),('load',M5,'A5 30',4),
 ('xor',M5,'49 02',2),('store',M5,'85 31',4),('return',M5,'60',7)])
SUFFIX=rows(0xE240,[('result',M5,'A5 31',4),('store-a',M5,'85 04',4),('load-x',M5,'A6 20',4),
 ('store-x',M5,'86 05',4),('load-y',M5,'A4 30',4),('store-y',M5,'84 06',4),('end',M5,'80 FE',4)])
MAIN=PREFIX[:-1]+BODY+[PREFIX[-1]]+SUFFIX
LABELS={r['label']:r['pc'] for r in PREFIX}
END=SUFFIX[-1]['pc'];MAIN_STEPS=len(MAIN);MAIN_CYCLES=sum(r['cycles'] for r in MAIN)
POINTER_STEPS=MAIN_STEPS-len(SUFFIX)
TRANSFER_STEPS=next(i+1 for i,r in enumerate(MAIN) if r['label']=='map-data')

def main_ram():
    ram=bytearray(8192);ram[:7]=bytes([0x40,0xE2,0x30,0x20,0x42,2,0x40]);ram[0x20]=2
    ram[0x30:0x32]=bytes([0x40,0x42]);ram[0x100]=0xE0;ram[0x1FF]=(LABELS['jump']-1)&255
    return bytes(ram)

def fixture():
    rom=bytearray([0xEA]*32768)
    for r in PREFIX+BODY+SUFFIX:
        off=physical(r['pc'],r['mpr']);rom[off:off+len(r['code'])]=r['code']
    rom[0x1FFE:0x2000]=bytes.fromhex('00 E0');rom[0x6080]=1
    cases=[]
    boundaries=(0,1,2,127,128,129,254,255)
    specs=[('ASL',6),('LSR',0x46),('ROL',0x26),('ROR',0x66),('INC',0xE6),('DEC',0xC6),('TSB',4),('TRB',0x14)]
    specs += [('RMB'+str(b),7+16*b) for b in range(8)]+[('SMB'+str(b),0x87+16*b) for b in range(8)]
    def add(name,parts,costs,a,x,y,p,writes):
        cases.append(dict(name=name,parts=parts,costs=costs,a=a,x=x,y=y,p=p,writes=writes))
    for name,opcode in specs:
        for byte in boundaries:
            for carry in ((0,1) if name in ('ROL','ROR') else (0,)):
                # A=0x55 and X/Y=0 at the operation, all C/D/V are authored.
                parts=[bytes([0xA9,byte]),bytes.fromhex('85 10'),bytes.fromhex('A9 55'),bytes.fromhex('A2 00'),bytes.fromhex('A0 00'),b'\xD8',bytes([0x38 if carry else 0x18]),b'\xB8',bytes([opcode,0x10]),bytes.fromhex('80 FE')]
                c=carry;v=0;n=0;z=1  # LDY #0 last sets N/Z.
                if name in ('ASL','ROL'):result=(byte*2+(carry if name=='ROL' else 0))%256;c=int(byte>=128)
                elif name in ('LSR','ROR'):result=byte//2+(carry*128 if name=='ROR' else 0);c=byte%2
                elif name=='INC':result=(byte+1)%256
                elif name=='DEC':result=(byte-1)%256
                elif name=='TSB':result=byte|0x55
                elif name=='TRB':result=byte&0xAA
                elif name.startswith('RMB'):result=byte&~(1<<int(name[-1]))
                else:result=byte|(1<<int(name[-1]))
                if name in ('TSB','TRB'):n=int(byte>=128);v=(byte>>6)&1;z=int(result==0)
                elif not name.startswith(('RMB','SMB')):n=int(result>=128);z=int(result==0)
                add(name,parts,[2,4,2,2,2,2,2,2,7 if name.startswith(('RMB','SMB')) else 6,4],0x55,0,0,4|c|z*2|v*64|n*128,{16:result})
    for name,opcode in (('AND',0x29),('ORA',9),('EOR',0x49),('ADC',0x69),('BCD-ADC',0x69)):
        for i,byte in enumerate(boundaries):
            decimal=name=='BCD-ADC';left=(0,1,9,0x10,0x49,0x50,0x98,0x99)[i] if decimal else byte
            right=1 if name in ('ADC','BCD-ADC') else 0x81
            if name=='AND':result=left&right;c=v=0
            elif name=='ORA':result=left|right;c=v=0
            elif name=='EOR':result=left^right;c=v=0
            elif decimal:
                total=(left>>4)*10+(left&15)+1;c=int(total>=100);total%=100;result=(total//10)*16+total%10;v=0
            else:
                result=(left+1)%256;c=int(left==255);v=int(left==127)
            parts=[bytes([0xA9,left]),bytes.fromhex('85 10'),bytes.fromhex('A9 55'),bytes.fromhex('A2 10'),bytes.fromhex('A0 00'),bytes([0xF8 if decimal else 0xD8]),b'\x18',b'\xB8',b'\xF4',bytes([opcode,right]),bytes.fromhex('80 FE')]
            add(name,parts,[2,4,2,2,2,2,2,2,2,6 if decimal else 5,4],0x55,16,0,4|c|int(decimal)*8|v*64|int(result>=128)*128|int(result==0)*2,{16:result})
    for opcode,encoded,cost in ((0x24,'24 10',4),(0x34,'34 10',4),(0x2C,'2C 10 20',5),(0x3C,'3C 10 20',5),
        (0x83,'83 40 10',7),(0xA3,'A3 40 10',7),(0x93,'93 40 10 20',8),(0xB3,'B3 40 10 20',8),(0x89,'89 C0',2)):
        for byte in boundaries:
            parts=[bytes([0xA9,byte]),bytes.fromhex('85 10'),bytes.fromhex('A9 40'),bytes.fromhex('A2 00'),bytes.fromhex('A0 00'),b'\xD8',b'\x18',b'\xB8',bytes.fromhex(encoded),bytes.fromhex('80 FE')]
            old=0xC0 if opcode==0x89 else byte;p=4|(old&0xC0)|(2 if old&0x40==0 else 0)
            add('BIT/TST',parts,[2,4,2,2,2,2,2,2,cost,4],0x40,0,0,p,{16:byte})
    # Every supported scalar store/load addressing form, including RAM pointers.
    modes=[('zpg','10',4),('zpx','0F',4),('zpy','0F',4),('abs','10 20',5),('abx','0F 20',5),('aby','0F 20',5),('idx','FF',7),('idy','00',7),('zpi','00',7)]
    families=[('STA',{'zpg':0x85,'zpx':0x95,'abs':0x8D,'abx':0x9D,'aby':0x99,'idx':0x81,'idy':0x91,'zpi':0x92}),
      ('STX',{'zpg':0x86,'zpy':0x96,'abs':0x8E}),('STY',{'zpg':0x84,'zpx':0x94,'abs':0x8C}),
      ('STZ',{'zpg':0x64,'zpx':0x74,'abs':0x9C,'abx':0x9E}),
      ('LDA',{'zpg':0xA5,'zpx':0xB5,'abs':0xAD,'abx':0xBD,'aby':0xB9,'idx':0xA1,'idy':0xB1,'zpi':0xB2}),
      ('LDX',{'zpg':0xA6,'zpy':0xB6,'abs':0xAE,'aby':0xBE}),('LDY',{'zpg':0xA4,'zpx':0xB4,'abs':0xAC,'abx':0xBC})]
    for name,forms in families:
        for mode,text,cost in modes:
            if mode not in forms:continue
            # Pointer at $2000 targets $2010, or $200F for (zp),Y.
            low=15 if mode=='idy' else 16
            parts=[bytes([0xA9,low]),bytes.fromhex('85 00'),bytes.fromhex('A9 20'),bytes.fromhex('85 01'),bytes.fromhex('A9 42'),bytes.fromhex('85 10'),bytes.fromhex('A9 55'),bytes.fromhex('A2 01'),bytes.fromhex('A0 01'),b'\xD8',b'\x18',b'\xB8']
            a,x,y=0x55,1,1;stored=0x42
            if name.startswith('ST'):
                stored={'STA':a,'STX':x,'STY':y,'STZ':0}[name]
            else:
                if name=='LDA':a=stored
                elif name=='LDX':x=stored
                else:y=stored
            parts.extend([bytes([forms[mode]])+bytes.fromhex(text),bytes.fromhex('80 FE')])
            add(name+'-'+mode,parts,[2,4,2,4,2,4,2,2,2,2,2,2,cost,4],a,x,y,4,{0:low,1:0x20,16:stored})
    for index,c in enumerate(cases):
        # 64-byte slots in four source banks; fetch context stays explicit.
        bank=index//112;pc=0xE400+(index%112)*64
        mpr=(0,248,251,3,0,0,0,bank)
        plan=[]
        for code in c.pop('parts'):plan.append((pc,mpr,code));pc+=len(code)
        code=b''.join(row[2] for row in plan);assert len(code)<=64
        off=physical(plan[0][0],mpr);assert off+len(code)<=len(rom)
        rom[off:off+len(code)]=code
        c.update(pc=plan[0][0],end=plan[-1][0],mpr=mpr,steps=len(plan),cycles=sum(c.pop('costs')),plan=plan)
    # Fixture setup/data and main source must never be overwritten by a matrix.
    for r in PREFIX+BODY+SUFFIX:
        assert bytes(rom[physical(r['pc'],r['mpr']):physical(r['pc'],r['mpr'])+len(r['code'])])==r['code']
    assert rom[0x6080]==1
    return bytes(rom),cases

def plan():return [(r['pc'],r['mpr'],r['code']) for r in MAIN]+[row for c in fixture()[1] for row in c['plan']]

def code_ranges():
    count=len(fixture()[1])
    return [(physical(r['pc'],r['mpr']),len(r['code'])) for r in MAIN]+[(bank*8192+0x400,min(112,count-bank*112)*64) for bank in range((count+111)//112)]
