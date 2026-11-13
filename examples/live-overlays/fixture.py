"""Original guest firmware, CD sectors and independent literal RAM expectations."""
MPR=[255,248,128,129,0,0,0,0]
TAGS=((0x31,0x32),(0x61,0x62))


class Assembler:
    def __init__(self,start):self.start=start;self.code=bytearray();self.labels={};self.fixups=[]
    @property
    def pc(self):return self.start+len(self.code)
    def label(self,name):self.labels[name]=self.pc
    def emit(self,text):self.code.extend(bytes.fromhex(text))
    def jump(self,opcode,label):
        self.code.extend((opcode,0,0));self.fixups.append((len(self.code)-2,label,False))
    def branch(self,opcode,label):
        self.code.extend((opcode,0));self.fixups.append((len(self.code)-1,label,True))
    def finish(self):
        for index,label,relative in self.fixups:
            address=self.labels[label]
            if relative:
                delta=address-(self.start+index+1)
                if not -128<=delta<=127:raise ValueError('Authored branch outside range')
                self.code[index]=delta&255
            else:self.code[index:index+2]=address.to_bytes(2,'little')
        return bytes(self.code)


def firmware():
    a=Assembler(0xE200)
    a.emit('D4 A9 00 53 F0 A9 FF 53 01 A9 F8 53 02 A9 80 53 04 A9 81 53 08 A2 FF 9A')
    a.emit('9C 00 20 9C 01 20 9C 10 20 9C 11 20 9C 12 20')
    a.emit('64 24 64 25 64 26 64 27 64 28 64 29 A9 08 85 24 A9 01 85 28')
    for phase in (1,2):
        if phase==2:a.label('second')
        a.emit(f'A9 {phase:02X} 85 27');a.jump(0x20,'load');a.labels[f'call_return_{phase}']=a.pc-1
        a.emit(f'A9 {phase:02X} 8D 00 20');a.label(f'gate_{phase}')
        a.emit(f'AD 01 20 C9 {phase:02X}');a.branch(0xD0,f'gate_{phase}');a.emit('4C 00 40')
    a.label('finished');a.emit('A9 03 8D 00 20');a.label('done');a.emit('80 FE')
    a.label('load');a.emit('9C 00 18 A2 00')
    a.label('command');a.emit('AD 00 18 C9 D0');a.branch(0xD0,'command')
    a.emit('B5 24 8D 01 18 A9 80 8D 02 18 9C 02 18 E8 E0 06');a.branch(0xD0,'command')
    a.emit('64 20 A9 40 85 21 A2 08 A0 00')
    a.label('data');a.emit('AD 00 18 C9 C8');a.branch(0xD0,'data')
    a.emit('AD 08 18 91 20 EA EA C8');a.branch(0xD0,'data')
    a.emit('E6 21 CA');a.branch(0xD0,'data')
    for name,value in (('status',0xD8),('message',0xF8)):
        a.label(name);a.emit(f'AD 00 18 C9 {value:02X}');a.branch(0xD0,name)
        a.emit('AD 01 18 A9 80 8D 02 18 9C 02 18')
    a.label('free');a.emit('AD 00 18');a.branch(0xD0,'free');a.emit('60')
    raw=bytearray(262144);code=a.finish();raw[512:512+len(code)]=code;raw[8190:8192]=bytes.fromhex('00 E2')
    return bytes(raw),dict(a.labels)


def sector(phase):
    _,labels=firmware();a,b=TAGS[phase-1];target=labels['second' if phase==1 else 'finished']
    code=bytes.fromhex(f'AD 10 20 F0 04 A9 {b:02X} 80 02 A9 {a:02X} 8D 11 20 EE 12 20 4C {target&255:02X} {target>>8:02X}')
    return code+bytes(2048-len(code))


def disc():return bytes(2048)+sector(1)+sector(2)+bytes(2048*47)


def expected_wram(phase,variant,*,released=True,finished=False):
    _,labels=firmware();ram=bytearray(8192)
    ram[0]=3 if finished else phase;ram[1]=phase if released else phase-1
    ram[0x10]=variant;ram[0x11]=TAGS[phase-1][variant] if released else 0 if phase==1 else TAGS[0][variant]
    ram[0x12]=phase if released else phase-1
    ram[0x20:0x22]=bytes((0,0x48));ram[0x24]=8;ram[0x27]=phase;ram[0x28]=1
    ret=labels[f'call_return_{phase}'];ram[0x1FE:0x200]=ret.to_bytes(2,'little')
    return bytes(ram)


def expected_cd(phase):return sector(phase)+bytes(65536-2048)


def code_plan(phase,variant):
    raw=sector(phase);offsets=(0,3,9,11,14,17) if variant==0 else (0,3,5,7,11,14,17)
    lengths={0:3,3:2,5:2,7:2,9:2,11:3,14:3,17:3}
    return [dict(pc=0x4000+i,mpr=MPR.copy(),data=list(raw[i:i+lengths[i]])) for i in offsets]


def cpu_ledger(phase,variant):
    """Literal per-position states for independently preset isolated RAM windows."""
    plan=code_plan(phase,variant);states=[];a=0;p=4
    for i,row in enumerate(plan):
        states.append(dict(pc=row['pc'],a=a,x=0,y=0,sp=255,p=p,mpr=MPR.copy()))
        if i==0:a=variant;p=6 if not variant else 4
        elif row['pc'] in (0x4005,0x4009):a=TAGS[phase-1][variant];p=4
    _,labels=firmware();states.append(dict(pc=labels['second' if phase==1 else 'finished'],a=a,x=0,y=0,sp=255,p=4,mpr=MPR.copy()))
    return states
