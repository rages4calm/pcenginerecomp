"""Original authored ROM data, control flow and addressing expectations."""
M0=(0,)*8
M1=(0,248,0,0,0,0,0,0)
M2=(0,248,1,0,0,0,0,0)
M3=(0,248,1,0,0,0,0,2)
MM=(0,1,3,0,0,0,0,0)
MAIN=((0xE000,M0,'A9 F8'),(0xE002,M0,'53 02'),(0xE004,M1,'AD 00 E1'),
      (0xE007,M1,'53 04'),(0xE009,M2,'AE 80 40'),(0xE00C,M2,'AC 01 40'),
      (0xE00F,M2,'B9 02 E1'),(0xE012,M2,'53 80'),(0xE014,M3,'AD 80 40'),
      (0xE017,M3,'20 00 E2'),(0xE200,M3,'BD FD E2'),(0xE203,M3,'6C FF E3'),
      (0xE240,M3,'8D 00 20'),(0xE243,M3,'8E 01 20'),(0xE246,M3,'8C 02 20'),
      (0xE249,M3,'60'),(0xE01A,M3,'80 FE'))
# Explicit byte-index and zero-page addressing cases. No decoder/runtime outputs
# generate expected load values, effective addresses or instruction costs.
MODES=((0xA5,'LDA','zpg',4),(0xB5,'LDA','zpx',4),(0xAD,'LDA','abs',5),
       (0xBD,'LDA','abx',5),(0xB9,'LDA','aby',5),(0xA1,'LDA','idx',7),
       (0xB1,'LDA','idy',7),(0xB2,'LDA','zpi',7),
       (0xA6,'LDX','zpg',4),(0xB6,'LDX','zpy',4),(0xAE,'LDX','abs',5),(0xBE,'LDX','aby',5),
       (0xA4,'LDY','zpg',4),(0xB4,'LDY','zpx',4),(0xAC,'LDY','abs',5),(0xBC,'LDY','abx',5))
DATA_RANGES=((0x100,6),(0x2000,256),(0x42FF,1),(0x6000,4096))
VECTOR_RANGES=((0x43FF,2),)

def physical(pc,mpr):return (mpr[pc>>13]<<13)|(pc&8191)

def fixture():
    rom=bytearray([0xEA]*32768)
    for pc,mpr,text in MAIN:
        data=bytes.fromhex(text);offset=physical(pc,mpr);rom[offset:offset+len(data)]=data
    rom[0x100]=1;rom[0x105]=2;rom[0x2080]=2;rom[0x2001]=3;rom[0x42FF]=42
    rom[0x43FF:0x4401]=bytes([0x40,0xE2]);rom[0x1FFE:0x2000]=bytes.fromhex('00 E0')
    cases=[];scalar=pointer=0
    for opcode,name,mode,cycles in MODES:
        for variant,value in enumerate((0,0x7F,0x80,0xFF)):
            number=len(cases);x=(0,1,254,255)[variant];y=(255,254,1,0)[variant]
            target=0x4080+number*4
            if mode in ('zpg','zpx','zpy'):
                direct=0x40+scalar;scalar+=1
                operand=(direct-(x if mode=='zpx' else y if mode=='zpy' else 0))&255
                operands=[operand];source=0x2000+direct;reads=[(0x2000+direct,source,value)]
            elif mode in ('idx','idy','zpi'):
                direct=255 if pointer==0 else 0x10+pointer*2;pointer+=1
                operand=(direct-(x if mode=='idx' else 0))&255
                word=(target-(y if mode=='idy' else 0))&65535
                lo,hi=word&255,word>>8
                rom[0x2000+direct]=lo;rom[0x2000+((direct+1)&255)]=hi
                operands=[operand];source=0x6000+(target&8191)
                reads=[(0x2000+direct,0x2000+direct,lo),
                       (0x2000+((direct+1)&255),0x2000+((direct+1)&255),hi),(target,source,value)]
            else:
                base=(target-(x if mode=='abx' else y if mode=='aby' else 0))&65535
                operands=[base&255,base>>8];source=0x6000+(target&8191);reads=[(target,source,value)]
            rom[source]=value;pc=0xE800+number*16
            code=bytes([0xA2,x,0xA0,y,opcode,*operands,0x80,0xFE])
            rom[pc&8191:(pc&8191)+len(code)]=code
            cases.append(dict(pc=pc,x=x,y=y,opcode=opcode,name=name,mode=mode,value=value,
                code=list(code),reads=reads,cycles=cycles+8,end=pc+len(code)-2))
    return bytes(rom),cases

def plan():
    _,cases=fixture();rows=list(MAIN)
    for case in cases:
        pc=case['pc'];code=case['code'];size=len(code)-6
        rows.extend(((pc,MM,bytes(code[:2])),(pc+2,MM,bytes(code[2:4])),
                     (pc+4,MM,bytes(code[4:4+size])),(case['end'],MM,b'\x80\xFE')))
    return [(pc,mpr,bytes.fromhex(code) if isinstance(code,str) else code) for pc,mpr,code in rows]

def code_ranges():
    return [(0,20),(0x4014,8),(0x4200,6),(0x4240,10)]+[(c['pc']&8191,len(c['code'])) for c in fixture()[1]]
