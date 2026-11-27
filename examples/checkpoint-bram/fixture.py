"""Authored guest CD-port writes and cold-seed readback, without firmware."""
import json
from pathlib import Path

from pcerecomp import prepare, project
from pcerecomp.boot_sources import FORMAT
from pcerecomp.isa import decode

PC = 0x2800
LOAD = 0x1F0800
MPR = [255, 248, 247, 248, 248, 248, 248, 248]
READBACK = 0x1F1000


def expected():
    """Independent complete 2 KiB expectation, not a runtime decoder."""
    return bytes((offset & 255) ^ ((0x35 + 17 * (offset >> 8)) & 255)
                 for offset in range(2048))


def program():
    code = bytearray(bytes.fromhex('78 D8 D4 A2 FF 9A A9 80 8D 07 18'))
    # Eight separately addressed page loops avoid changing MPR/source identity.
    # Read the original seed before any write, through the ordinary guest bus.
    for page in range(8):
        code.extend(bytes.fromhex('A2 00'))
        code.extend((0xBD, 0, 0x40 + page, 0x9D, 0, 0x30 + page,
                     0xE8, 0xD0, 0xF7))
    for page in range(8):
        code.extend(bytes.fromhex('A2 00'))
        code.extend((0x8A, 0x49, (0x35 + 17 * page) & 255,
                     0x9D, 0, 0x40 + page, 0xE8, 0xD0, 0xF7))
    # A real read of $1803 locks BRAM. Leave it locked during extraction.
    code.extend(bytes.fromhex('AD 03 18 A9 A5 85 00'))
    ready = PC + len(code)
    code.extend(bytes.fromhex('80 FE'))
    return bytes(code), ready


def create(output, *, seed=None, name='authored-bram'):
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    initial = bytes(2048) if seed is None else Path(seed).read_bytes()
    if len(initial) != 2048:
        raise ValueError('Authored initial BRAM must contain exactly 2048 bytes')
    seed_path = output / 'initial-bram.bin'
    seed_path.write_bytes(initial)
    code, ready = program()
    image = output / 'authored.bin'
    image.write_bytes(code)
    roots = []
    offset = 0
    while offset < len(code):
        instruction = decode(lambda address: code[address-PC], PC+offset, tuple(MPR))
        if not instruction.native:
            raise ValueError('Authored BRAM fixture needs native translated operations')
        roots.append(dict(pc=PC+offset, mpr=MPR, selector=0,
                          source_offsets=list(range(offset, offset+len(instruction.data)))))
        offset += len(instruction.data)
    declarations = output / 'roots.json'
    declarations.write_text(json.dumps(dict(format=FORMAT, schema=1, kind='declared',
        execution_evidence=False, image=dict(kind='payload', sha256=project.sha256(image),
        physical_load=LOAD), roots=roots), indent=2)+'\n', encoding='utf-8')
    spec = dict(schema=1, format=prepare.FORMAT, name=name,
        module=dict(kind='declared', path=str(declarations), partition_layout='stable'),
        payload=dict(path=str(image), physical_load=LOAD, pc=PC, mpr=MPR),
        bram=dict(path=str(seed_path)),
        runtime=dict(tier='native', video='continuous', cd_unknown_status='fault',
                     joypad=2, region='usa', multitap='off', audio='off'),
        limits=dict(steps=1000000, ticks=100000000, wall_seconds=60))
    recipe = output / 'recipe.toml'
    recipe.write_text(prepare._toml(spec), encoding='utf-8')
    prepared = output / 'consumer'
    prepare.prepare_project(recipe, prepared)
    return dict(descriptor=prepared/'project.toml', recipe=recipe, ready=ready,
                initial_sha256=project.sha256(seed_path), declared_instructions=len(roots))
