"""Author a native HuCard scene with real BG, sprites, palette and PSG writes."""
import json
from pathlib import Path

from pcerecomp.emitter import emit_declarations
from pcerecomp.project import sha256


def emit_fixture(output):
    output=Path(output).absolute();output.mkdir(parents=True,exist_ok=False)
    data=bytearray();roots=[];labels={};branches=[];mpr=[0]*8
    def emit(code):
        nonlocal mpr
        raw=bytes.fromhex(code);offset=len(data);data.extend(raw)
        roots.append(dict(pc=0xE000+offset,mpr=mpr.copy(),selector=0,rom_offsets=list(range(offset,offset+len(raw)))))
        if raw==b'\x53\x01':mpr[0]=255
        if raw==b'\x53\x02':mpr[1]=248
    def label(name):labels[name]=len(data)
    def branch(op,name):
        offset=len(data);emit(f'{op:02X} 00');branches.append((offset+1,name))
    def reg(index,value):emit(f'03 {index:02X}');emit(f'13 {value&255:02X}');emit(f'23 {value>>8:02X}')
    def word(value):emit(f'13 {value&255:02X}');emit(f'23 {value>>8:02X}')
    def address(value):reg(0,value);emit('03 02')
    def palette(index,color):
        for port,value in ((0x402,index&255),(0x403,index>>8),(0x404,color&255),(0x405,color>>8)):
            emit(f'A9 {value:02X}');emit(f'8D {port&255:02X} {port>>8:02X}')
    for code in ('78','D8','D4','A2 FF','9A','A9 FF','53 01','A9 F8','53 02','64 40','64 41'):emit(code)
    # The entire 32x32 BAT selects tile64; the tile pattern is outside the BAT.
    address(0);emit('A0 04');label('page');emit('A2 00');label('bat');word(64)
    emit('E8');branch(0xD0,'bat');emit('88');branch(0xD0,'page')
    address(0x400)
    for row in range(8):word(0xAA if row<4 else 0x55)
    for _ in range(8):word(0)
    # One opaque16x16 sprite pattern in plane0, all other planes transparent.
    address(0x1000)
    for row in range(64):word(0xFFFF if row<16 else 0)
    address(0x2000)
    for value in (144,112,128,128,144,152,128,1):word(value)
    for _ in range(248):word(0)
    for index,color in ((0,0x007),(1,0x038),(256,0x1F8),(257,0x1C0),(273,0x1FF)):
        palette(index,color)
    for index,value in ((10,0x0202),(11,0x041F),(12,0x0F02),(13,239),(14,2),
                        (7,0),(8,0),(9,0),(15,0x10),(19,0x2000),(5,0x00C8)):
        reg(index,value)
    for port,value in ((0,0),(1,255),(4,223),(5,240),(6,31)):
        emit(f'A9 {value:02X}');emit(f'8D {port:02X} 08')
    emit('A9 A5');emit('85 41');label('wait')
    emit('AD 00 00');emit('29 20');branch(0xF0,'wait');emit('E6 40');branch(0x80,'wait')
    for offset,name in branches:
        distance=labels[name]-offset-1
        if not -128<=distance<=127:raise ValueError('Authored branch exceeds range')
        data[offset]=distance&255
    if len(data)>8190:raise ValueError('Authored scene exceeds one HuCard bank')
    card=bytearray([0xEA]*8192);card[:len(data)]=data;card[-2:]=bytes((0,224))
    image=output/'authored-card.pce';image.write_bytes(card)
    declared=output/'roots.json'
    declared.write_text(json.dumps(dict(format='pce-declared-roots-1',schema=1,kind='declared',execution_evidence=False,
        image=dict(sha256=sha256(image),profile='base',header='none',encoding='linear'),roots=roots),indent=2)+'\n',encoding='utf-8')
    emit_declarations(declared,image,output/'module',single_unit=True)
    result=dict(program_bytes=len(data),declared_instructions=len(roots),card_sha256=sha256(image),
        scope='Original static BG/two-sprite scene; no retail data or inferred raster history')
    (output/'fixture.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result
