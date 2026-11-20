"""Generate the original walkable HuCard and its exact, unobserved ROM roots."""
import json


PROGRAM = """
    78              # SEI
    D4              # CSH
    A9 FF           # map I/O into $0000
    53 01           # TAM #$01
    A9 F8           # map work RAM into $2000
    53 02           # TAM #$02
    A9 80           # player starts at world x=256
    85 40           # STA $40
    A9 A5           # renderer state is now ready
    85 41           # STA $41
    A9 80           # initialize the VCE backdrop at palette entry zero
    8D 04 04
    9C 05 04
    03 05           # ST0 #$05, VDC control
    13 88           # ST1 #$88, background and VBlank flag
    23 00           # ST2 #$00
wait:
    AD 00 00        # read/acknowledge VDC status
    29 20           # wait for VBlank
    F0 @wait
    A9 03           # latch the directional nibble
    8D 00 10
    A9 01
    8D 00 10
    AD 00 10
    85 42
    29 02           # Right is active low
    F0 @right
    A5 42
    29 08           # Left is active low
    D0 @wait
    A5 40
    F0 @wait        # stop at world x=0
    C6 40
    80 @color
right:
    A5 40
    C9 FF
    F0 @wait        # stop at world x=510
    E6 40
color:
    9C 02 04        # reset VCE palette address and update the backdrop
    9C 03 04
    A5 40
    8D 04 04
    9C 05 04
    80 @wait
"""


def emit_fixture(output):
    from pcerecomp.emitter import emit_declarations
    from pcerecomp.project import sha256

    output.mkdir(parents=True, exist_ok=False)
    card = bytearray([0xEA] * 8192)
    roots, branches, labels = [], [], {}
    mprs = [0] * 8
    offset = 0
    for line in PROGRAM.splitlines():
        src = line.partition("#")[0].strip()
        if not src:
            continue
        if src.endswith(":"):
            labels[src[:-1]] = offset
            continue
        opcode, _, label = src.partition("@")
        code = bytes.fromhex(opcode)
        if label:
            branches.append((offset + 1, label))
            code += b"\0"
        end = offset + len(code)
        roots.append(dict(pc=0xE000 + offset, mpr=mprs.copy(), selector=0,
                          rom_offsets=list(range(offset, end))))
        card[offset:end] = code
        if code == b"\x53\x01":
            mprs[0] = 255
        elif code == b"\x53\x02":
            mprs[1] = 248
        offset = end
    for operand, label in branches:
        card[operand] = (labels[label] - operand - 1).to_bytes(1, "little", signed=True)[0]
    card[-2:] = b"\x00\xe0"
    image = output / "authored-card.pce"
    image.write_bytes(card)
    declarations = output / "roots.json"
    declarations.write_text(json.dumps(dict(
        format="pce-declared-roots-1", schema=1, kind="declared", execution_evidence=False,
        image=dict(sha256=sha256(image), profile="base", header="none", encoding="linear"),
        roots=roots,
    ), indent=2) + "\n", encoding="utf-8")
    emit_declarations(declarations, image, output / "module", single_unit=True)
