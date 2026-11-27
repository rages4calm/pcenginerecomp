"""Authored late-entry program: one added declaration removes one fallback."""
import json
from pathlib import Path

from pcerecomp import prepare, project
from pcerecomp.boot_sources import FORMAT


def prepare_fixture(output):
    output=Path(output).absolute();output.mkdir(parents=True,exist_ok=False)
    mapping=[255]+[248]*7
    # Initialize two counters, spin until the high byte reaches FF, then write
    # a marker and stop in a guest loop. No debugger edits or firmware are used.
    code=bytes.fromhex('78 64 00 64 01 E6 00 A5 00 D0 FA E6 01 A5 01 C9 FF D0 F2 A9 77 85 02 80 FE')
    image=output/'authored.bin';image.write_bytes(code)
    offsets=[(0,1)]+[(offset,2) for offset in range(1,len(code),2)]
    result={}
    for name,missing in (('source',19),('destination',None)):
        roots=[dict(pc=0x2800+offset,mpr=mapping,selector=0,
                    source_offsets=list(range(offset,offset+size)))
               for offset,size in offsets if offset!=missing]
        declarations=output/(name+'-roots.json')
        declarations.write_text(json.dumps(dict(format=FORMAT,schema=1,kind='declared',execution_evidence=False,
            image=dict(kind='payload',sha256=project.sha256(image),physical_load=0x1f0800),roots=roots)),encoding='utf-8')
        spec=dict(schema=1,format=prepare.FORMAT,name='continuation-'+name,
            module=dict(kind='declared',path=str(declarations),partition_layout='stable'),
            payload=dict(path=str(image),physical_load=0x1f0800,pc=0x2800,mpr=mapping),
            runtime=dict(tier='hybrid',video='continuous',cd_unknown_status='fault',joypad=2,
                         region='usa',multitap='off',audio='on',audio_profile='filtered',audio_rate=48000),
            limits=dict(steps=10000000,ticks=100000000,wall_seconds=120))
        recipe=output/(name+'.toml');recipe.write_text(prepare._toml(spec),encoding='utf-8')
        directory=output/name;prepare.prepare_project(recipe,directory)
        result[name]=dict(descriptor=directory/'project.toml',observations=directory/'declarations/roots.json')
    return result
