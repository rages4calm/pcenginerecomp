"""Original CD fixture with a public A=group loader entry at synthetic E700."""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('original_cd_fixture',Path(__file__).resolve().parents[1]/'live-overlays/fixture.py');f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
MPR=f.MPR;TAGS=f.TAGS
disc=f.disc;sector=f.sector;expected_cd=f.expected_cd;expected_wram=f.expected_wram;code_plan=f.code_plan;cpu_ledger=f.cpu_ledger
def firmware():
    original,labels=f.firmware();data=bytearray(original);target=labels['load']
    data[0x700:0x706]=bytes((0x85,0x27,0x20,target&255,target>>8,0x60));return bytes(data),labels|dict(public_loader=0xE700)
def loader_plan():
    return dict(format='pce-loader-sweep-1',schema=1,groups=[1,2],passes=['independent','cumulative'],
        loader=dict(pc=0xE700,mpr=MPR.copy(),a='group',x=0,y=0,p=4,return_pc=0x3F00,return_mpr_mask=255),
        snapshot=dict(ranges=[[0x100000,65536],[0x1F0000,8192]],code_ranges=[[0x100000,20]],entries=[0x4000]),
        limits=dict(instructions=2000000,ticks=20000000,seconds=60,states=10000,contexts=256))
def setup_profile():
    import hashlib
    return dict(format='pce-port-setup-1',schema=1,
        recipe=dict(schema=1,format='pce-consumer-prepare-1',name='authored-loader-port',module=dict(kind='declared',path='bootstrap.json'),
            boot=dict(mode='system-card-reset',profile='standard'),bios=dict(path='$bios'),disc=dict(path='$disc'),
            runtime=dict(tier='hybrid',video='continuous',audio='off',cd_unknown_status='fault',joypad=2,region='usa',multitap='off'),
            limits=dict(steps=50000000,ticks=100000000,wall_seconds=120)),
        bootstrap=dict(format='pce-declared-boot-roots-1',schema=1,kind='declared',execution_evidence=False,
            image=dict(kind='system-card',profile='standard',sha256=hashlib.sha256(firmware()[0]).hexdigest()),roots=[dict(pc=0xE200,mpr=[0]*8,selector=0,source_offsets=[512])]),
        assets=dict(bios=[hashlib.sha256(firmware()[0]).hexdigest()],disc=[hashlib.sha256(disc()).hexdigest()]),loader=loader_plan(),
        route=[dict(frames=12,buttons=0),dict(frames=12,buttons=0,writes=[dict(address=0x1F0001,data='01',expected='00')]),dict(frames=12,buttons=0,writes=[dict(address=0x1F0001,data='02',expected='01')])])
