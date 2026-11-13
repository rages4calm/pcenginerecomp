"""Source-qualified boot declarations, without observed work or live RAM guesses.

Raw System Card ROM and explicitly loaded standard-RAM payloads have distinct
source contracts. A declaration authenticates source bytes, not their continued
presence in writable memory; generated code retains normal live fetch guards.
"""
from .capture import integer
from .isa import decode, physical

FORMAT = 'pce-declared-boot-roots-1'


def metadata(image, size):
    from .declarations import _fields, _digest, _choice
    if type(image) is not dict:
        raise ValueError('Boot source requires an explicit image contract')
    kind = image.get('kind')
    if kind == 'system-card':
        _fields(image, {'kind','sha256','profile'}, 'System Card declaration image')
        _choice(image['profile'], ('standard','super'), 'System Card profile')
        if size != 262144:
            raise ValueError('System Card declarations require raw 256 KiB firmware')
        result = dict(kind=kind, profile=image['profile'])
    elif kind == 'bios':
        _fields(image,{'kind','sha256'},'sandbox BIOS declaration image')
        if size!=262144:raise ValueError('Sandbox BIOS declarations require raw 256 KiB firmware')
        result=dict(kind=kind)
    elif kind == 'payload':
        _fields(image, {'kind','sha256','physical_load'}, 'payload declaration image')
        load = integer(image['physical_load'], 0x1FFFFF, 'payload physical load')
        if not 1 <= size <= 0x200000-load or any(
                bank not in {*range(0x80,0x88),0xF8}
                for bank in range(load//8192,(load+size-1)//8192+1)):
            raise ValueError('Declared payload must fit standard CD/work RAM')
        result = dict(kind=kind, physical_load=load)
    else:
        raise ValueError('Unsupported boot declaration source kind')
    _digest(image['sha256'])
    return result | dict(image_sha256=image['sha256'], file_bytes=size)


def source_offset(address, source):
    bank = address//8192
    if source['kind']=='bios':
        if bank>=32:raise ValueError('Declared fetch is outside the sandbox BIOS window')
        return address
    if source['kind'] == 'system-card':
        if bank >= 0x80 or source['profile']=='super' and bank >= 0x68:
            raise ValueError('Declared fetch is not driven System Card ROM')
        return address & 0x3FFFF
    # Only a supported loaded range is authenticated, never zero-fill or other
    # device memory. Standard WRAM mirrors share one backing page.
    if 0xF8 <= bank <= 0xFB:
        address = 0x1F0000+(address & 8191)
    result = address-source['physical_load']
    if not 0 <= result < source['file_bytes']:
        raise ValueError('Declared fetch lies outside the authenticated payload')
    return result


def admit(path, image_path, store, snapshot):
    import hashlib
    from .declarations import (AdmittedDeclarations, MAX_ROOTS, MAX_IMAGE_BYTES,
        _fields, _ordinary, _binding, _diagnostics, instruction_key, _sort_key)
    document=snapshot.value
    if (document['format'] != FORMAT or type(document['schema']) is not int
            or document['schema'] != 1 or document['kind'] != 'declared'
            or document['execution_evidence'] is not False):
        raise ValueError('Unsupported boot declaration schema/kind/evidence')
    _ordinary(image_path, MAX_IMAGE_BYTES)
    source=metadata(document['image'],image_path.stat().st_size)
    bound=store.bind(image_path,expected_sha256=source['image_sha256'])
    if bound.size_bytes != source['file_bytes']:
        raise ValueError('Boot source size changed during admission')
    with image_path.open('rb') as stream:
        raw=stream.read(bound.size_bytes+1)
    if len(raw)!=bound.size_bytes or hashlib.sha256(raw).hexdigest()!=bound.sha256:
        raise ValueError('Boot source changed during decoding')
    roots=document['roots']
    if type(roots) is not list or not 1<=len(roots)<=MAX_ROOTS:
        raise ValueError('Boot declarations require a bounded nonempty root list')
    seen=set();union={};diagnostics=[]
    for root in roots:
        _fields(root,{'pc','mpr','selector','source_offsets'},'boot declaration root')
        pc=integer(root['pc'],65535,'declared logical PC')
        if type(root['mpr']) is not list or len(root['mpr'])!=8:
            raise ValueError('Declared roots require all eight MPR bytes')
        mpr=tuple(integer(n,255,'declared MPR') for n in root['mpr'])
        integer(root['selector'],0,'boot source selector')
        offsets=root['source_offsets']
        if type(offsets) is not list or not 1<=len(offsets)<=7:
            raise ValueError('Boot source offsets require one to seven bytes')
        for offset in offsets:integer(offset,len(raw)-1,'declared source offset')
        identity=(pc,mpr,tuple(offsets))
        if identity in seen:raise ValueError('Duplicate identical boot declaration')
        seen.add(identity)
        offset=lambda logical:source_offset(physical(logical,mpr),source)
        instruction=decode(lambda logical:raw[offset(logical)],pc,mpr)
        if offsets!=[offset((pc+i)&65535) for i in range(len(instruction.data))]:
            raise ValueError('Boot source offsets disagree with decoded length or mapping')
        report=instruction.report()|{'mpr':mpr}
        union[instruction_key(report)]=report
        diagnostics.extend(_diagnostics(root,report,None))
    admitted=AdmittedDeclarations(path,image_path,snapshot.sha256,
        sorted(union.values(),key=_sort_key),
        sorted(roots,key=lambda row:(row['mpr'],row['pc'],row['selector'],row['source_offsets'])),
        source,dict(declarations=_binding(snapshot),source_image=_binding(bound)),
        diagnostics,store,FORMAT,1)
    admitted.revalidate()
    return admitted
