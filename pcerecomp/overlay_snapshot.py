"""Closed paused RAM observations, separate from retired-code evidence.

Two reported memory reads and equal typed status bracket each snapshot. Package
bindings are caller supplied: this proves neither remote-process authenticity
nor the disc sector/loader that produced RAM. No guest state is restored here.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import re
from pathlib import Path

from .capture import integer
from .declarations import _ordinary, _path, _fields, _digest, _binding
from .discovery import _canonical, _directory
from .snapshots import SnapshotStore

FORMAT = 'pce-paused-ram-snapshot-1'
MACHINE_FORMAT = 'pce-overlay-machine-1'
MAX_JSON = 2 * 1024 * 1024
MAX_RAM = 270336
MAX_REGIONS = 32
U64 = (1 << 64) - 1


def machine_for(config, identities):
    boot = deepcopy(config.get('boot'))
    if boot is None:
        boot = dict(mode='payload', **{k: config['payload'][k] for k in ('physical_load', 'pc', 'mpr')})
    value = dict(format=MACHINE_FORMAT, schema=1, runtime_abi=29, boot=boot,
                 assets={k: identities[k] for k in sorted(identities)
                         if k in {'cartridge','bios','payload','disc','toc','bram'}})
    validate_machine(value)
    return value


def package_binding(descriptor,build_dir,*,allow_revision_override=False):
    """Admit local package bytes; this does not authenticate a TCP peer."""
    from .project import _verified_package
    checked,built,binary,receipt_sha=_verified_package(descriptor,build_dir,allow_revision_override=allow_revision_override)
    identities={k:checked['config'][k]['sha256'] for k in ('cartridge','bios','payload','disc','toc','bram') if k in checked['config']}
    origin=dict(tool=checked['tool_identity'],descriptor_sha256=checked['descriptor_sha256'],
                build_receipt_sha256=receipt_sha,binary_sha256=built['binary_sha256'])
    validate_origin(origin)
    return machine_for(checked['config'],identities),origin


def validate_machine(value):
    _fields(value, {'format','schema','runtime_abi','boot','assets'}, 'overlay machine')
    if (value['format'] != MACHINE_FORMAT or type(value['schema']) is not int or value['schema'] != 1
            or type(value['runtime_abi']) is not int or value['runtime_abi'] != 29):
        raise ValueError('Unsupported overlay machine contract')
    assets = value['assets']
    if type(assets) is not dict or not assets or set(assets)-{'cartridge','bios','payload','disc','toc','bram'}:
        raise ValueError('Overlay machine requires explicit asset hashes')
    for sha in assets.values(): _digest(sha)
    boot = value['boot']
    if type(boot) is not dict: raise ValueError('Overlay boot must be an object')
    mode = boot.get('mode')
    if mode == 'hucard-reset':
        from .cartridge import PROFILES, HEADERS, ENCODINGS
        _fields(boot, {'mode','profile','header','encoding'}, 'overlay HuCard boot')
        if (any(type(boot[k]) is not str for k in ('profile','header','encoding'))
                or boot['profile'] not in PROFILES or boot['header'] not in HEADERS or boot['encoding'] not in ENCODINGS
                or 'cartridge' not in assets or set(assets)-{'cartridge'}):
            raise ValueError('Invalid overlay HuCard source contract')
    elif mode == 'system-card-reset':
        fields = {'mode','profile'} | ({'arcade_card'} if 'arcade_card' in boot else set())
        _fields(boot, fields, 'overlay System Card boot')
        if (type(boot['profile']) is not str or boot['profile'] not in ('standard','super') or 'bios' not in assets
                or {'cartridge','payload'} & assets.keys()
                or 'arcade_card' in boot and (boot['arcade_card'] != 'duo' or boot['profile'] != 'super')):
            raise ValueError('Invalid overlay System Card source contract')
    elif mode == 'payload':
        _fields(boot, {'mode','physical_load','pc','mpr'}, 'overlay payload boot')
        integer(boot['physical_load'], 0x1FFFFF, 'overlay payload load')
        integer(boot['pc'], 65535, 'overlay initial PC'); mpr(boot['mpr'])
        if 'payload' not in assets or 'cartridge' in assets: raise ValueError('Invalid overlay payload source contract')
    else: raise ValueError('Unsupported overlay boot mode')


def mpr(value):
    if type(value) is not list or len(value) != 8: raise ValueError('Overlay requires all eight MPR bytes')
    return tuple(integer(x, 255, 'overlay MPR') for x in value)


def canonical(address):
    return 0x1F0000 + (address & 8191) if 0xF8 <= address >> 13 <= 0xFB else address


def ram_ranges(machine, ranges):
    validate_machine(machine)
    if type(ranges) not in (list, tuple) or not 1 <= len(ranges) <= MAX_REGIONS:
        raise ValueError('Overlay requires one to 32 explicit RAM ranges')
    mode = machine['boot']['mode']; banks = {0xF8}
    if mode != 'hucard-reset': banks.update(range(0x80, 0x88))
    if mode == 'system-card-reset' and machine['boot']['profile'] == 'super': banks.update(range(0x68, 0x80))
    result = []
    for row in ranges:
        if type(row) not in (list, tuple) or len(row) != 2: raise ValueError('RAM range requires physical start and length')
        start = integer(row[0], 0x1FFFFF, 'RAM start'); size = integer(row[1], min(65536, 0x200000-start), 'RAM length', 1)
        if any(bank not in banks for bank in range(start >> 13, ((start+size-1) >> 13)+1)):
            raise ValueError('Overlay range is not canonical supported RAM in this machine')
        result.append((start, size))
    if result != sorted(result) or any(a+n > b for (a,n),(b,_) in zip(result,result[1:])) or sum(n for _,n in result)>MAX_RAM:
        raise ValueError('Overlay RAM ranges must be sorted, disjoint and bounded')
    return result


def validate_origin(value):
    _fields(value, {'tool','descriptor_sha256','build_receipt_sha256','binary_sha256'}, 'overlay caller package binding')
    tool = value['tool']; _fields(tool, {'revision','source_sha256','source_files'}, 'overlay producer SDK')
    if type(tool['revision']) is not str or re.fullmatch('[0-9a-f]{40}',tool['revision']) is None:
        raise ValueError('Overlay producer requires an exact Git revision')
    _digest(tool['source_sha256']); integer(tool['source_files'], 1000000, 'SDK files', 1)
    for key in ('descriptor_sha256','build_receipt_sha256','binary_sha256'): _digest(value[key])


def status(value):
    if type(value) is not dict or value.get('ok') is not True or value.get('paused') is not True or value.get('local_paused') is not False:
        raise ValueError('Overlay capture requires a settled network pause')
    integer(value.get('id'), (1<<53)-1, 'status ID', 1)
    for key in ('ticks','frame'): integer(value.get(key), U64, 'status '+key)
    host = value.get('host')
    if type(host) is not dict or type(host.get('cpu')) is not dict: raise ValueError('Overlay requires complete CPU source status')
    pc = integer(host.get('pc'),65535,'paused PC'); cpu=host['cpu']; mapping=mpr(cpu.get('mpr'))
    for key in ('a','x','y','sp','p'): integer(cpu.get(key),255,'paused '+key)
    for key in ('native_steps','interpreter_steps'): integer(host.get(key),U64,'paused '+key)
    expected=[(mapping[((pc+i)&65535)>>13]<<13)|((pc+i)&8191) for i in range(7)]
    integer(cpu.get('physical_pc'),0x1FFFFF,'reported physical PC')
    addresses=cpu.get('instruction_physical')
    if type(addresses) is not list or len(addresses)!=7:raise ValueError('Overlay requires seven physical fetch addresses')
    for address in addresses:integer(address,0x1FFFFF,'reported fetch address')
    if cpu['physical_pc'] != expected[0] or addresses != expected:
        raise ValueError('Overlay reported instruction mapping disagrees with PC/MPR')
    data=cpu.get('instruction_bytes')
    if type(data) is not list or len(data)!=7: raise ValueError('Overlay requires seven reported source bytes')
    for byte in data:
        if byte is not None: integer(byte,255,'reported source byte')
    return pc,mapping


def exact(left,right):
    if type(left) is not type(right): return False
    if type(left) is dict: return left.keys()==right.keys() and all(exact(left[k],right[k]) for k in left)
    if type(left) is list: return len(left)==len(right) and all(exact(a,b) for a,b in zip(left,right))
    return left==right


def paused_pair(before,after):
    status(before); status(after)
    a=deepcopy(before); b=deepcopy(after); del a['id']; del b['id']
    if not exact(a,b): raise ValueError('Guest or reported host state changed during overlay snapshot')


def memory_reply(value,start,size):
    _fields(value, {'id','ok','address','length','data'}, 'overlay memory reply')
    integer(value['id'], (1<<53)-1,'memory response ID',1)
    if value['ok'] is not True or type(value['address']) is not int or value['address']!=start or type(value['length']) is not int or value['length']!=size:
        raise ValueError('Overlay memory response range differs from request')
    text=value['data']
    if type(text) is not str or len(text)!=size*2 or re.fullmatch('[0-9a-f]+',text) is None:
        raise ValueError('Overlay memory reply is not exact lowercase hex')
    return bytes.fromhex(text)


@dataclass(frozen=True)
class PausedRam:
    path: Path
    sha256: str
    _document: dict
    _before: dict
    regions: tuple
    _bindings: dict
    _store: SnapshotStore

    @property
    def document(self): return deepcopy(self._document)
    @property
    def before(self): return deepcopy(self._before)
    @property
    def artifact_bindings(self): return deepcopy(self._bindings)
    def revalidate(self):
        _closed(self.path.parent,self._bindings)
        self._store.revalidate()
        _closed(self.path.parent,self._bindings)


def _closed(root,bindings):
    _directory(root)
    if {p.name for p in root.iterdir()} != set(bindings): raise ValueError('Paused RAM snapshot is not closed')
    for name,row in bindings.items(): _ordinary(root/name,MAX_RAM if name.endswith('.bin') else MAX_JSON)


def load_snapshot(path):
    path=_path(path)
    if path.is_dir(): path=path/'snapshot.json'
    if path.name!='snapshot.json': raise ValueError('Paused RAM manifest must be snapshot.json')
    _ordinary(path,MAX_JSON); store=SnapshotStore(); snap=store.read_json(path,max_bytes=MAX_JSON); doc=snap.value
    _fields(doc, {'format','schema','execution_evidence','machine','origin','regions','artifacts'},'paused RAM snapshot')
    if doc['format']!=FORMAT or type(doc['schema']) is not int or doc['schema']!=1 or doc['execution_evidence'] is not False:
        raise ValueError('Unsupported paused RAM snapshot contract')
    validate_machine(doc['machine']); validate_origin(doc['origin'])
    rows=doc['regions']
    if type(rows) is not list: raise ValueError('Overlay snapshot requires RAM ranges')
    for row in rows: _fields(row,{'physical','length'},'RAM region')
    spans=ram_ranges(doc['machine'],[(row['physical'],row['length']) for row in rows])
    names={'before.json','after.json'}|{f'{kind}-{i:03d}.{suffix}' for i in range(len(rows)) for kind,suffix in (('ram','bin'),('read','json'),('verify','json'))}
    artifacts=doc['artifacts']
    if type(artifacts) is not dict or set(artifacts)!=names: raise ValueError('Invalid paused RAM artifact closure')
    bindings={'snapshot.json':_binding(snap)}; objects={}
    for name,row in artifacts.items():
        _fields(row,{'sha256','size_bytes'},'RAM artifact'); _digest(row['sha256']); integer(row['size_bytes'],MAX_JSON,'RAM artifact bytes',1)
        file=path.parent/name; _ordinary(file,MAX_RAM if name.endswith('.bin') else MAX_JSON)
        bound=(store.bind(file,expected_sha256=row['sha256']) if name.endswith('.bin') else store.read_json(file,expected_sha256=row['sha256'],max_bytes=MAX_JSON))
        if bound.size_bytes!=row['size_bytes']: raise ValueError('RAM artifact size disagrees with binding')
        bindings[name]=_binding(bound)
        if not name.endswith('.bin'): objects[name]=bound.value
    before,after=objects['before.json'],objects['after.json']; paused_pair(before,after); identity=before['id']; regions=[]
    for i,(start,size) in enumerate(spans):
        raw=memory_reply(objects[f'read-{i:03d}.json'],start,size)
        if objects[f'read-{i:03d}.json']['id']!=identity+1: raise ValueError('Overlay read IDs are not contiguous')
        identity+=1
        if hashlib.sha256(raw).hexdigest()!=artifacts[f'ram-{i:03d}.bin']['sha256'] or size!=artifacts[f'ram-{i:03d}.bin']['size_bytes']:
            raise ValueError('RAM bytes disagree with original read response')
        regions.append((start,raw))
    for i,(start,size) in enumerate(spans):
        raw=memory_reply(objects[f'verify-{i:03d}.json'],start,size)
        if objects[f'verify-{i:03d}.json']['id']!=identity+1 or raw!=regions[i][1]: raise ValueError('Paused RAM readback changed or response IDs differ')
        identity+=1
    if after['id']!=identity+1: raise ValueError('Overlay final status ID differs')
    for address,byte in zip(before['host']['cpu']['instruction_physical'],before['host']['cpu']['instruction_bytes']):
        address=canonical(address)
        for start,data in regions:
            if start<=address<start+len(data) and byte!=data[address-start]:
                raise ValueError('Reported CPU fetch bytes disagree with captured RAM')
    result=PausedRam(path,snap.sha256,doc,before,tuple(regions),bindings,store); result.revalidate(); return result


def capture_snapshot(client,output,*,machine,origin,regions):
    """Read only; caller owns the paused host/connection and package authenticity."""
    spans=ram_ranges(machine,regions); validate_origin(origin); output=_path(output)
    if output.exists() or output.is_symlink(): raise ValueError('RAM snapshot requires a new directory')
    _directory(output.parent); files={}; before=client.call('status'); status(before)
    files['before.json']=_canonical(before,MAX_JSON); reads=[]
    for i,(start,size) in enumerate(spans):
        response=client.call('read_memory_block',address=start,length=size); raw=memory_reply(response,start,size)
        reads.append(raw); files[f'read-{i:03d}.json']=_canonical(response,MAX_JSON); files[f'ram-{i:03d}.bin']=raw
    for i,(start,size) in enumerate(spans):
        response=client.call('read_memory_block',address=start,length=size)
        if memory_reply(response,start,size)!=reads[i]: raise ValueError('RAM changed between paused reads')
        files[f'verify-{i:03d}.json']=_canonical(response,MAX_JSON)
    after=client.call('status'); paused_pair(before,after); files['after.json']=_canonical(after,MAX_JSON)
    doc=dict(format=FORMAT,schema=1,execution_evidence=False,machine=deepcopy(machine),origin=deepcopy(origin),
             regions=[dict(physical=a,length=n) for a,n in spans],artifacts={name:dict(sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw)) for name,raw in files.items()})
    output.mkdir()
    for name,raw in files.items():
        with (output/name).open('xb') as stream: stream.write(raw)
    with (output/'snapshot.json').open('xb') as stream: stream.write(_canonical(doc,MAX_JSON))
    return load_snapshot(output)
