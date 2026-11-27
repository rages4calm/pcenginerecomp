"""Create an authored native program and source-qualified consumer adapter."""
from pathlib import Path
import json

from pcerecomp import prepare,project
from pcerecomp.boot_sources import FORMAT
from pcerecomp.isa import decode

MPR=[255,248,248,248,248,248,248,248]
PC=0x2800
LOAD=0x1F0800


class Assembler:
    def __init__(self):self.data=bytearray();self.labels={};self.fixups=[]
    @property
    def pc(self):return PC+len(self.data)
    def label(self,name):self.labels[name]=self.pc
    def emit(self,text):self.data.extend(bytes.fromhex(text))
    def branch(self,opcode,label):
        self.data.extend((opcode,0));self.fixups.append((len(self.data)-1,label,True))
    def call(self,label):
        self.data.extend((0x20,0,0));self.fixups.append((len(self.data)-2,label,False))
    def finish(self):
        for offset,label,relative in self.fixups:
            target=self.labels[label]
            if relative:
                value=target-(PC+offset+1)
                if not -128<=value<=127:raise ValueError('Authored relative branch exceeds range')
                self.data[offset]=value&255
            else:self.data[offset:offset+2]=target.to_bytes(2,'little')
        return bytes(self.data)


def program():
    a=Assembler()
    a.emit('78 D8 D4 A2 FF 9A')  # SEI, CLD, CSH, explicit stack.
    # Nonzero blue guest backdrop; VBlank acknowledgement drives the timer.
    a.emit('A9 07 8D 04 04 9C 05 04')
    # Explicit horizontal/vertical timing: one VDC VBlank event per output
    # frame. Sandbox power-on register zeros are not a game timing recipe.
    for register,value in ((10,0x0202),(11,0x041F),(12,0x0F02),(13,239),(14,2),(5,0x0088)):
        a.emit(f'03 {register:02X} 13 {value&255:02X} 23 {value>>8:02X}')
    # Original guest PSG writes produce literal nonzero stereo PCM.
    for port,value in ((0,0),(1,255),(4,223),(5,240),(6,31)):
        a.emit(f'A9 {value:02X} 8D {port:02X} 08')
    # Settle the newly programmed VDC latches in the original guest. The first
    # power-on frame is not used as a gameplay timing reference.
    a.emit('A2 08')
    a.label('warmup');a.emit('AD 00 00 29 20');a.branch(0xF0,'warmup')
    a.emit('CA');a.branch(0xD0,'warmup')
    # EXP=100, gold=200, health=10; timer/frame/diagnostic bytes begin at zero.
    a.emit('A9 64 85 00 64 01 A9 C8 85 02 64 03')
    a.emit('64 04 64 05 64 06 64 07 A9 0A 85 08')
    a.label('earned_exp');a.emit('A9 03 18 65 00 85 00')
    a.label('earned_gold');a.emit('A9 05 18 65 02 85 02')
    # Spend two gold independently. No periodic balance/delta multiplier exists.
    a.label('spend');a.emit('38 A5 02 E9 02 85 02')
    a.call('damage')
    a.emit('A9 A5 85 09')
    a.label('game_ready')
    a.label('wait');a.emit('AD 00 00 29 20');a.branch(0xF0,'wait')
    a.label('vblank');a.emit('E6 05 A5 04');a.branch(0xF0,'hurt')
    a.emit('C6 04');a.branch(0x80,'wait')
    a.label('hurt');a.call('damage');a.branch(0x80,'wait')
    a.label('damage');a.emit('C6 08 E6 06')
    a.label('hit');a.emit('A9 02 85 04 60')
    return a.finish(),a.labels


def expected(frame,*,exp=1,gold=1,protection=0):
    """Independent literal toy-game rules, not a copy of the callback."""
    if type(frame) is not int or not 0<=frame<=6:raise ValueError('Bounded authored frame expectation')
    # One initial hit then one incoming attack at each guest VBlank. Every hit
    # starts a 2-frame original countdown, or the enabled 4-frame countdown.
    ordinary=((9,2),(9,1),(9,0),(8,2),(8,1),(8,0),(7,2))
    protected=((9,4),(9,3),(9,2),(9,1),(9,0),(8,4),(8,3))
    health,timer=(protected if protection else ordinary)[frame]
    return dict(exp=100+3*exp,gold=200+5*gold-2,health=health,timer=timer,vblanks=frame)


def create(output):
    output=Path(output).absolute();output.mkdir(parents=True,exist_ok=False)
    code,labels=program();image=output/'authored.bin';image.write_bytes(code)
    roots=[];offset=0
    while offset<len(code):
        instruction=decode(lambda address:code[address-PC],PC+offset,tuple(MPR))
        if not instruction.native:raise ValueError('Fixture uses an unsupported native operation')
        roots.append(dict(pc=PC+offset,mpr=MPR,selector=0,
            source_offsets=list(range(offset,offset+len(instruction.data)))))
        offset+=len(instruction.data)
    declarations=output/'roots.json'
    declarations.write_text(json.dumps(dict(format=FORMAT,schema=1,kind='declared',execution_evidence=False,
        image=dict(kind='payload',sha256=project.sha256(image),physical_load=LOAD),roots=roots),indent=2)+'\n',encoding='utf-8')
    manifest=dict(format='pce-title-adapter-1',schema=1,id='authored-qol',state_bytes=48,
        settings=[dict(name='exp',min=1,max=8,default=1),dict(name='gold',min=1,max=8,default=1),
                  dict(name='protection',min=0,max=1,default=0)],
        events=[dict(name=name,pc=labels[name],mpr=MPR,selector=0,
                     data=code[labels[name]-PC:labels[name]-PC+2].hex())
                for name in ('earned_exp','earned_gold','hit','vblank')])
    adapter_folder=output/'title-source';adapter_folder.mkdir()
    manifest_path=adapter_folder/'adapter.json';manifest_path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    source=adapter_folder/'adapter.cpp';source.write_bytes(Path(__file__).with_name('fixture.cpp').read_bytes())
    results={}
    for name,adapter,span in (('original',False,False),('adapted',True,False),('span',True,True)):
        spec=dict(schema=1,format=prepare.FORMAT,name='title-'+name,
            module=dict(kind='declared',path=str(declarations),partition_layout='stable'),
            payload=dict(path=str(image),physical_load=LOAD,pc=PC,mpr=MPR),
            runtime=dict(tier='native',video='continuous',cd_unknown_status='fault',joypad=2,
                         region='usa',multitap='off',audio='on',audio_profile='raw',audio_rate=44100),
            limits=dict(steps=10000000,ticks=100000000,wall_seconds=120))
        if adapter:spec['title_adapter']=dict(source=str(source),manifest=str(manifest_path))
        if span:spec['module']['native_span']=True;spec['runtime']['native_span']=8
        recipe=output/(name+'.toml');recipe.write_text(prepare._toml(spec),encoding='utf-8')
        prepared=output/name;prepare.prepare_project(recipe,prepared)
        results[name]=dict(descriptor=prepared/'project.toml',recipe=recipe)
    (output/'fixture.json').write_text(json.dumps(dict(labels=labels,program_sha256=project.sha256(image),
        declared_instructions=len(roots),scope='Authored earned-reward and guest-VBlank timer rules; no retail-game timing claim'),indent=2)+'\n',encoding='utf-8')
    return results
