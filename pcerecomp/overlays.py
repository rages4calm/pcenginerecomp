"""Rederived RAM-source candidates and closed multi-epoch overlay libraries.

Snapshots establish reported bytes at a paused epoch, not immutable RAM, loader
attribution, routine closure or retired work. Normal native fetch guards remain.
"""
from bisect import bisect_right
from collections import Counter, deque
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import Path

from .analysis import _register_facts
from .capture import integer
from .declarations import _ordinary, _path, _fields, _digest, _binding, instruction_key, _sort_key
from .discovery import _canonical, _directory
from .isa import BRANCHES, decode, physical
from .overlay_snapshot import (load_snapshot, canonical, ram_ranges, exact, MAX_RAM,
                               MAX_JSON, validate_machine, _ram_geometry)
from .snapshots import SnapshotStore

FORMAT='pce-live-overlay-discovery-1'
ORIGIN_FORMAT='pce-disc-origin-overlay-discovery-1'
ORIGIN_POLICY='observed-disc-offset-candidates-v1'
LIBRARY_FORMAT='pce-overlay-library-1'
MAX_GRAPH=64*1024*1024
MAX_EPOCHS=256
MAX_LIBRARY=256*1024*1024
MAX_STATES=100000
MAX_CONTEXTS=4096
POLICY='paused-ram-candidates-v1'
ANALYSIS_POLICY='bounded-ram-cd-candidates-v1'
FAR_CALL_POLICY='bounded-ram-cd-stack-values-v1'
ORIGIN_ANALYSIS_POLICY='observed-disc-offset-bounded-candidates-v1'
ORIGIN_FAR_CALL_POLICY='observed-disc-offset-stack-values-v1'
_WRITERS={'STA','STX','STY','STZ','ASL','LSR','ROL','ROR','INC','DEC','TSB','TRB'}


def is_library(path):
    # This probe also sees existing large single-source/source-set declarations.
    # Apply the tighter manifest limit only after recognizing an overlay library.
    path=_path(path);_ordinary(path,MAX_GRAPH)
    value=SnapshotStore().read_json(path,max_bytes=MAX_GRAPH).value
    return type(value) is dict and value.get('format')==LIBRARY_FORMAT


def _bytes(path,binding):
    _ordinary(path,MAX_GRAPH)
    with path.open('rb') as stream: raw=stream.read(binding['size_bytes']+1)
    if len(raw)!=binding['size_bytes'] or hashlib.sha256(raw).hexdigest()!=binding['sha256']:
        raise ValueError('Overlay artifact changed while copying')
    return raw


def _new_directory(path):
    path=_path(path)
    if path.exists() or path.is_symlink(): raise ValueError('Overlay output requires a new directory')
    _directory(path.parent)
    return path


def _copy(bindings,base,output):
    for name,row in bindings.items():
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream: stream.write(_bytes(base/name,row))


def _derive(snapshot,entries,code_ranges,instruction_limit,context_limit):
    integer(instruction_limit,MAX_STATES,'overlay state limit',1)
    integer(context_limit,MAX_CONTEXTS,'overlay context limit',1)
    if type(entries) is not list or not 1<=len(entries)<=256:
        raise ValueError('Overlay entries require one to 256 sorted unique logical PCs')
    for pc in entries: integer(pc,65535,'overlay entry')
    if entries!=sorted(set(entries)):
        raise ValueError('Overlay entries require sorted unique logical PCs')
    machine=snapshot.document['machine'];geometry=_ram_geometry(machine);ranges=geometry.ranges(code_ranges)
    mapping=tuple(snapshot.before['host']['cpu']['mpr']);starts=[a for a,_ in ranges]
    regions=snapshot.regions;region_starts=[a for a,_ in regions]
    def locate(address):
        address=canonical(address);index=bisect_right(region_starts,address)-1
        if index<0 or address>=regions[index][0]+len(regions[index][1]): raise ValueError('bytes_not_in_snapshot')
        return index,address-regions[index][0]
    def permitted(address):
        address=canonical(address);index=bisect_right(starts,address)-1
        return index>=0 and address<ranges[index][0]+ranges[index][1]
    for a,n in ranges:
        for address in (a,a+n-1):locate(address)
        # Gaps between separately captured regions cannot become guessed bytes.
        cursor=a
        while cursor<a+n:
            index,offset=locate(cursor);cursor=min(a+n,regions[index][0]+len(regions[index][1]))
    def fetch(state):
        pc,mpr,_,_=state;locations=[]
        def read(logical):
            pa=physical(logical,mpr)
            if not permitted(pa):raise ValueError('outside_allowed_code')
            index,offset=locate(pa);return regions[index][1][offset]
        ins=decode(read,pc,mpr)
        for i in range(len(ins.data)):
            index,offset=locate(physical((pc+i)&65535,mpr));locations.append(dict(region=index,offset=offset))
        return ins,locations
    def write_barrier(ins,mpr,facts,transfer):
        name,mode=ins.mnemonic,ins.mode
        if mode=='blk':return 'block_transfer_changes_memory'
        if name in ('ST0','ST1','ST2'):return 'opaque_device_write'
        targets=[]
        if name in ('PHA','PHP','PHX','PHY','JSR','BSR'):
            targets.extend(range(0x2100,0x2200))
        elif name in ('ADC','AND','EOR','ORA') and transfer!=0:
            targets.extend(0x2000+i for i in (range(256) if facts[1] is None else (facts[1],)))
        elif (name in _WRITERS or name.startswith(('RMB','SMB'))) and mode!='acc':
            if mode in ('zpg','zpx','zpy'):
                index=None if mode=='zpg' else facts[1 if mode=='zpx' else 2]
                targets.extend(0x2000+((ins.data[1]+i)&255) for i in ((0,) if mode=='zpg' else range(256) if index is None else (index,)))
            elif mode in ('abs','abx','aby'):
                base=ins.data[1]|ins.data[2]<<8;index=None if mode=='abs' else facts[1 if mode=='abx' else 2]
                targets.extend((base+i)&65535 for i in ((0,) if mode=='abs' else range(256) if index is None else (index,)))
            else:return 'unknown_write_target'
        for logical in targets:
            pa=canonical(physical(logical,mpr))
            if not geometry.contains_byte(pa):return 'write_not_proven_ram'
            if permitted(pa):return 'possible_code_write'
        return None
    initial=[(pc,mapping,(None,None,None),None) for pc in entries]
    if len(initial)>instruction_limit:raise ValueError('Overlay seeds exceed state limit')
    for state in initial:
        try:fetch(state)
        except ValueError as error:raise ValueError('Overlay seed is not wholly in authenticated allowed RAM: '+str(error)) from error
    queue=deque(initial);scheduled=set(initial);nodes=[];edges=[];frontiers=[];known={};contexts={mapping};union={};roots={};occupied={};overlaps=[]
    def state_json(state):return dict(pc=state[0],mpr=list(state[1]),registers=list(state[2]),transfer=state[3])
    while queue:
        if len(nodes)>=instruction_limit:
            frontiers.append(dict(reason='state_limit',pending_states=len(queue)));break
        state=queue.popleft();pc,mpr,facts,transfer=state
        try:ins,locations=fetch(state)
        except ValueError as error:
            frontiers.append(dict(state=state_json(state),reason=str(error)));continue
        key=instruction_key(ins.report()|dict(mpr=mpr));union[key]=ins.report()|dict(mpr=mpr)
        roots[key]=dict(pc=pc,mpr=list(mpr),fetch=locations)
        index=len(nodes);known[state]=index
        node=dict(id=index,**state_json(state),fetch=locations,mnemonic=ins.mnemonic,mode=ins.mode)
        nodes.append(node)
        for pa in ins.physical:
            address=canonical(pa)
            if address in occupied and occupied[address]!=pc:overlaps.append(dict(physical=address,pc=pc,other=occupied[address]))
            occupied[address]=pc
        def stop(reason,**detail):frontiers.append(dict(node=index,reason=reason,**detail))
        barrier=write_barrier(ins,mpr,facts,transfer)
        if barrier:stop(barrier);continue
        if not ins.native:stop('unsupported_instruction');continue
        if ins.mnemonic in ('RTS','RTI','BRK'):stop({'RTS':'dynamic_return','RTI':'interrupt_return','BRK':'interrupt_vector'}[ins.mnemonic]);continue
        if ins.mnemonic=='JMP' and ins.target is None:stop('indirect_jump');continue
        updated=tuple(_register_facts(ins,facts,mpr));next_mpr=mpr
        if ins.mnemonic=='TAM' and ins.data[1]:
            if facts[0] is None:stop('unknown_mapping_value');continue
            next_mpr=tuple(facts[0] if ins.data[1]&(1<<i) else bank for i,bank in enumerate(mpr))
        next_t=1 if ins.mnemonic=='SET' else None if ins.mnemonic=='PLP' else 0
        successors=[]
        if ins.mnemonic in BRANCHES or ins.mode=='zrl':successors=[(ins.target,'taken'),(ins.next_pc,'fallthrough')]
        elif ins.mnemonic in ('JSR','BSR'):
            successors=[(ins.target,'call')];stop('return_continuation_unproven',continuation=ins.next_pc)
        elif ins.mnemonic in ('JMP','BRA'):successors=[(ins.target,'jump')]
        else:successors=[(ins.next_pc,'fallthrough')]
        for target,kind in successors:
            successor=(target,next_mpr,updated,next_t)
            if next_mpr not in contexts and len(contexts)>=context_limit:
                stop('context_limit',target=state_json(successor));continue
            contexts.add(next_mpr);edges.append(dict(source=index,target=state_json(successor),kind=kind))
            if successor not in scheduled:scheduled.add(successor);queue.append(successor)
    result = (dict(nodes=nodes,edges=edges,unresolved=frontiers,overlaps=overlaps,
                summary=dict(states=len(nodes),identities=len(union),contexts=len({tuple(n['mpr']) for n in nodes}),unresolved=len(frontiers))),sorted(union.values(),key=_sort_key),list(roots.values()))
    geometry.revalidate(machine)
    return result


def _analysis_options(analysis_policy,call_depth_limit,data_ranges):
    """Keep the original policy closed; new traversal is an explicit opt-in."""
    if analysis_policy is None:
        if call_depth_limit is not None or data_ranges is not None:
            raise ValueError('Call/data options require the bounded RAM/CD analysis policy')
        return None
    if type(analysis_policy) is not str or analysis_policy not in (ANALYSIS_POLICY,FAR_CALL_POLICY):
        raise ValueError('Unsupported bounded RAM/CD analysis policy')
    depth=16 if call_depth_limit is None else call_depth_limit
    integer(depth,64,'RAM/CD call depth limit',1)
    data=[] if data_ranges is None else data_ranges
    if type(data) not in (list,tuple):raise ValueError('Data ranges require an explicit list')
    result=dict(call_depth_limit=depth,data_ranges=data)
    if analysis_policy==FAR_CALL_POLICY:result['far_calls']=True
    return result


def _derive_bounded(snapshot,entries,code_ranges,instruction_limit,context_limit,call_depth_limit,data_ranges,far_calls=False):
    from .ram_cd_analysis import derive
    machine=snapshot.document['machine'];geometry=_ram_geometry(machine)
    ranges=geometry.ranges(code_ranges)
    if type(data_ranges) not in (list,tuple):raise ValueError('Data ranges require an explicit list')
    data=geometry.ranges(data_ranges) if data_ranges else []
    regions=snapshot.regions;region_starts=[a for a,_ in regions]
    def locate(address):
        address=canonical(address);index=bisect_right(region_starts,address)-1
        if index<0 or address>=regions[index][0]+len(regions[index][1]):
            raise ValueError('bytes_not_in_snapshot')
        return index,address-regions[index][0]
    # Both permissions and data declarations refer only to authenticated bytes.
    for a,n in (*ranges,*data):
        cursor=a
        while cursor<a+n:
            index,_=locate(cursor);cursor=min(a+n,regions[index][0]+len(regions[index][1]))
    starts=[a for a,_ in ranges];data_starts=[a for a,_ in data]
    def contains(address,rows,starts):
        index=bisect_right(starts,address)-1
        return index>=0 and address<rows[index][0]+rows[index][1]
    def permitted(address):
        address=canonical(address)
        return contains(address,ranges,starts) and not contains(address,data,data_starts)
    def fetch(pc,mpr):
        def read(logical):
            address=physical(logical,mpr)
            if not permitted(address):raise ValueError('outside_allowed_code')
            index,offset=locate(address);return regions[index][1][offset]
        ins=decode(read,pc,mpr)
        locations=[]
        for i in range(len(ins.data)):
            index,offset=locate(physical((pc+i)&65535,mpr))
            locations.append(dict(region=index,offset=offset))
        return ins,locations
    result=derive(entries,tuple(snapshot.before['host']['cpu']['mpr']),fetch=fetch,
        is_code=permitted,is_ram=geometry.contains_byte,canonical=canonical,
        instruction_limit=instruction_limit,context_limit=context_limit,call_depth_limit=call_depth_limit,
        **(dict(far_calls=True) if far_calls else {}))
    geometry.revalidate(machine)
    return result


def _derive_with_policy(snapshot,entries,ranges,instruction_limit,context_limit,analysis):
    if analysis is None:return _derive(snapshot,entries,ranges,instruction_limit,context_limit)
    return _derive_bounded(snapshot,entries,ranges,instruction_limit,context_limit,**analysis)


@dataclass(frozen=True)
class OverlayEpoch:
    path: Path
    sha256: str
    snapshot: object
    _report: dict
    _instructions: list
    _roots: list
    _bindings: dict
    _store: SnapshotStore
    _origins: object=None
    @property
    def report(self):return deepcopy(self._report)
    @property
    def artifact_bindings(self):return deepcopy(self._bindings)
    def revalidate(self):
        _epoch_closed(self.path.parent);self.snapshot.revalidate();self._store.revalidate();_epoch_closed(self.path.parent)
        if self._origins is not None:self._origins.revalidate()


def _epoch_closed(root):
    _directory(root)
    names={p.name for p in root.iterdir()}
    if names not in ({'overlay.json','snapshot'},{'overlay.json','origins'}):raise ValueError('Overlay epoch is not closed')
    _ordinary(root/'overlay.json',MAX_GRAPH)
    _directory(root/('origins' if 'origins' in names else 'snapshot'))


def discover_overlay(snapshot_path,output,*,code_ranges,entries=None,instruction_limit=10000,context_limit=256,
                     analysis_policy=None,call_depth_limit=None,data_ranges=None):
    analysis=_analysis_options(analysis_policy,call_depth_limit,data_ranges)
    output=_new_directory(output);snapshot=load_snapshot(snapshot_path)
    if output.is_relative_to(snapshot.path.parent):raise ValueError('Overlay discovery cannot modify its original snapshot')
    if entries is None:entries=[snapshot.before['host']['pc']]
    elif type(entries) is list:
        for entry in entries:integer(entry,65535,'overlay entry')
        entries=sorted(set(entries))
    ranges=ram_ranges(snapshot.document['machine'],code_ranges)
    graph,_,_=_derive_with_policy(snapshot,entries,ranges,instruction_limit,context_limit,analysis)
    report=dict(format=FORMAT,schema=1,execution_evidence=False,kind='static_candidates',analysis_policy=POLICY if analysis is None else analysis_policy,
        routine_closure=False,static_reachability='candidates_only',snapshot_sha256=snapshot.sha256,
        options=dict(entries=entries,code_ranges=[list(row) for row in ranges],instruction_limit=instruction_limit,context_limit=context_limit),**graph)
    if analysis is not None:report['options'].update(call_depth_limit=analysis['call_depth_limit'],data_ranges=[list(row) for row in analysis['data_ranges']])
    raw=_canonical(report,MAX_GRAPH);snapshot.revalidate();output.mkdir();(output/'snapshot').mkdir()
    _copy(snapshot.artifact_bindings,snapshot.path.parent,output/'snapshot');snapshot.revalidate()
    with (output/'overlay.json').open('xb') as stream:stream.write(raw)
    return load_overlay(output)


def discover_origin_overlay(snapshot_path,origin_path,output,*,disc_ranges,entries=None,instruction_limit=10000,context_limit=256,
                            analysis_policy=None,call_depth_limit=None,data_ranges=None):
    from .origin_overlay import load_origins,select_ranges
    analysis=_analysis_options(analysis_policy,call_depth_limit,data_ranges)
    output=_new_directory(output)
    admitted=load_origins(origin_path)
    snapshot=load_snapshot(snapshot_path)
    if snapshot.sha256!=admitted.snapshot.sha256:
        raise ValueError('Origin evidence belongs to a different RAM snapshot')
    if output.is_relative_to(admitted.path.parent) or output.is_relative_to(snapshot.path.parent):
        raise ValueError('Origin discovery cannot modify its inputs')
    if entries is None:entries=[snapshot.before['host']['pc']]
    elif type(entries) is list:
        for entry in entries:integer(entry,65535,'overlay entry')
        entries=sorted(set(entries))
    ranges=select_ranges(admitted,disc_ranges)
    graph,_,_=_derive_with_policy(snapshot,entries,ranges,instruction_limit,context_limit,analysis)
    report=dict(format=ORIGIN_FORMAT,schema=1,execution_evidence=False,kind='static_candidates',
        analysis_policy=ORIGIN_POLICY if analysis is None else ORIGIN_FAR_CALL_POLICY if analysis_policy==FAR_CALL_POLICY else ORIGIN_ANALYSIS_POLICY,routine_closure=False,static_reachability='candidates_only',
        snapshot_sha256=snapshot.sha256,origins_sha256=admitted.sha256,
        options=dict(entries=entries,code_ranges=[list(row) for row in ranges],
                     disc_ranges=[list(row) for row in disc_ranges],
                     instruction_limit=instruction_limit,context_limit=context_limit),**graph)
    if analysis is not None:report['options'].update(call_depth_limit=analysis['call_depth_limit'],data_ranges=[list(row) for row in analysis['data_ranges']])
    raw=_canonical(report,MAX_GRAPH)
    admitted.revalidate();snapshot.revalidate()
    output.mkdir();(output/'origins').mkdir()
    _copy(admitted.artifact_bindings,admitted.path.parent,output/'origins')
    admitted.revalidate()
    with (output/'overlay.json').open('xb') as stream:stream.write(raw)
    return load_overlay(output)


def load_overlay(path):
    path=_path(path)
    if path.is_dir():path=path/'overlay.json'
    if path.name!='overlay.json':raise ValueError('Overlay report must be overlay.json')
    _epoch_closed(path.parent);store=SnapshotStore();snap=store.read_json(path,max_bytes=MAX_GRAPH);doc=snap.value
    origin_aware=type(doc) is dict and doc.get('format')==ORIGIN_FORMAT
    fields={'format','schema','execution_evidence','kind','analysis_policy','routine_closure','static_reachability','snapshot_sha256','options','nodes','edges','unresolved','overlaps','summary'}
    if origin_aware:fields.add('origins_sha256')
    _fields(doc,fields,'overlay report')
    legacy_policy=ORIGIN_POLICY if origin_aware else POLICY
    bounded_policy=ORIGIN_ANALYSIS_POLICY if origin_aware else ANALYSIS_POLICY
    far_policy=ORIGIN_FAR_CALL_POLICY if origin_aware else FAR_CALL_POLICY
    bounded=type(doc['analysis_policy']) is str and doc['analysis_policy'] in (bounded_policy,far_policy)
    if (doc['format'] not in (FORMAT,ORIGIN_FORMAT) or type(doc['schema']) is not int or doc['schema']!=1 or doc['execution_evidence'] is not False
            or doc['kind']!='static_candidates' or doc['analysis_policy'] not in (legacy_policy,bounded_policy,far_policy) or doc['routine_closure'] is not False or doc['static_reachability']!='candidates_only'):
        raise ValueError('Unsupported overlay discovery policy')
    origins=None
    if origin_aware:
        from .origin_overlay import load_origins,select_ranges
        if (path.parent/'snapshot').exists():raise ValueError('Origin epoch has unexpected snapshot')
        origins=load_origins(path.parent/'origins')
        _digest(doc['origins_sha256'])
        if origins.sha256!=doc['origins_sha256']:raise ValueError('Overlay origin binding differs')
        snapshot=origins.snapshot
    else:
        snapshot=load_snapshot(path.parent/'snapshot')
    _digest(doc['snapshot_sha256'])
    if snapshot.sha256!=doc['snapshot_sha256']:raise ValueError('Overlay snapshot binding differs')
    options=doc['options']
    option_fields={'entries','code_ranges','instruction_limit','context_limit'}
    if bounded:option_fields.update(('call_depth_limit','data_ranges'))
    if origin_aware:option_fields.add('disc_ranges')
    _fields(options,option_fields,'overlay options')
    if bounded:
        integer(options['call_depth_limit'],64,'RAM/CD call depth limit',1)
        if type(options['data_ranges']) is not list:raise ValueError('Recorded data ranges require an explicit list')
    if origins is not None:
        selected=[list(row) for row in select_ranges(origins,options['disc_ranges'])]
        if not exact(selected,options['code_ranges']):raise ValueError('Overlay ranges differ from observed disc origins')
    analysis=_analysis_options(FAR_CALL_POLICY if doc['analysis_policy']==far_policy else ANALYSIS_POLICY,options['call_depth_limit'],options['data_ranges']) if bounded else None
    graph,instructions,roots=_derive_with_policy(snapshot,options['entries'],options['code_ranges'],options['instruction_limit'],options['context_limit'],analysis)
    if any(not exact(doc[k],v) for k,v in graph.items()):raise ValueError('Overlay graph disagrees with independent source rederivation')
    bindings={'overlay.json':_binding(snap)}
    source=origins if origins is not None else snapshot
    prefix='origins' if origins is not None else 'snapshot'
    for name,row in source.artifact_bindings.items():
        bound=store.bind(path.parent/prefix/name,expected_sha256=row['sha256']);bindings[prefix+'/'+name]=_binding(bound)
    value=OverlayEpoch(path,snap.sha256,snapshot,doc,instructions,roots,bindings,store,origins);value.revalidate();return value


@dataclass(frozen=True)
class OverlayLibrary:
    path: Path
    sha256: str
    _instructions: list
    _roots: list
    _source_metadata: dict
    _artifact_bindings: dict
    _diagnostics: list
    _epochs: tuple
    _store: SnapshotStore
    format: str=LIBRARY_FORMAT
    @property
    def instructions(self):return deepcopy(self._instructions)
    @property
    def roots(self):return deepcopy(self._roots)
    @property
    def source_metadata(self):return deepcopy(self._source_metadata)
    @property
    def artifact_bindings(self):return deepcopy(self._artifact_bindings)
    @property
    def diagnostics(self):return deepcopy(self._diagnostics)
    @property
    def static_reachability(self):return 'candidates_only'
    def revalidate(self):
        _library_closed(self.path.parent,len(self._epochs))
        for e in self._epochs:e.revalidate()
        self._store.revalidate();_library_closed(self.path.parent,len(self._epochs))


def _library_closed(root,count):
    _directory(root/'epochs')
    if {p.name for p in (root/'epochs').iterdir()}!={f'e{i:04d}' for i in range(count)}:raise ValueError('Overlay library epoch namespace is not closed')


def load_library(path):
    path=_path(path)
    if path.is_dir():path=path/'library.json'
    _ordinary(path,MAX_JSON);store=SnapshotStore();snap=store.read_json(path,max_bytes=MAX_JSON);doc=snap.value
    _fields(doc,{'format','schema','kind','execution_evidence','machine','epochs'},'overlay library')
    if doc['format']!=LIBRARY_FORMAT or type(doc['schema']) is not int or doc['schema']!=1 or doc['kind']!='declared' or doc['execution_evidence'] is not False:raise ValueError('Unsupported overlay library contract')
    validate_machine(doc['machine']);rows=doc['epochs']
    if type(rows) is not list or not 1<=len(rows)<=MAX_EPOCHS:raise ValueError('Overlay library requires one to 256 epochs')
    _library_closed(path.parent,len(rows));seen=set();epochs=[];union={};roots=[];diagnostics=[];memberships=Counter();metadata=[];bindings={'declarations':_binding(snap)}
    total=snap.size_bytes
    for i,row in enumerate(rows):
        _fields(row,{'path','sha256'},'overlay epoch binding');_digest(row['sha256'])
        if row['path']!=f'epochs/e{i:04d}/overlay.json' or row['sha256'] in seen:raise ValueError('Invalid or duplicate overlay epoch')
        seen.add(row['sha256']);epoch=load_overlay(path.parent/row['path'])
        if epoch.sha256!=row['sha256'] or not exact(epoch.snapshot.document['machine'],doc['machine']):raise ValueError('Overlay epoch/machine binding differs')
        epochs.append(epoch)
        for name,bound in epoch.artifact_bindings.items():
            relative=f'epochs/e{i:04d}/'+name;pin=store.bind(path.parent/relative,expected_sha256=bound['sha256']);bindings['member:'+relative]=_binding(pin);total+=pin.size_bytes
            if total>MAX_LIBRARY:raise ValueError('Combined overlay library exceeds 256 MiB; no entries dropped')
        for ins in epoch._instructions:union[instruction_key(ins)]=ins
        memberships.update(instruction_key(ins) for ins in epoch._instructions)
        roots.extend(dict(epoch=i,**root) for root in epoch._roots)
        if len(roots)>1048576:raise ValueError('Combined overlay identities exceed their bound')
        diagnostics.extend(dict(epoch=i,**item) for item in epoch.report['unresolved'])
        before=epoch.snapshot.before
        metadata.append(dict(sha256=epoch.sha256,snapshot_sha256=epoch.snapshot.sha256,origin=epoch.snapshot.document['origin'],frame=before['frame'],ticks=before['ticks'],native_steps=before['host']['native_steps'],interpreter_steps=before['host']['interpreter_steps'],identities=len(epoch._instructions)))
    source=dict(format=LIBRARY_FORMAT,machine=doc['machine'],epochs=metadata,memberships=sum(memberships.values()),overlapping_identities=sum(n>1 for n in memberships.values()),loader_attribution='not_inferred')
    value=OverlayLibrary(path,snap.sha256,sorted(union.values(),key=_sort_key),roots,source,bindings,diagnostics,tuple(epochs),store);value.revalidate();return value


def compose_overlays(paths,output):
    output=_new_directory(output)
    if type(paths) not in (list,tuple) or not 1<=len(paths)<=MAX_EPOCHS:raise ValueError('Expected one to 256 overlay epochs')
    epochs=[load_overlay(path) for path in paths];machine=epochs[0].snapshot.document['machine'];seen=set();total=0
    for epoch in epochs:
        if not exact(epoch.snapshot.document['machine'],machine):raise ValueError('Cannot combine overlays from different machines/media')
        if epoch.sha256 in seen:raise ValueError('Duplicate overlay epoch')
        if output.is_relative_to(epoch.path.parent):raise ValueError('Overlay library cannot modify its original epoch')
        seen.add(epoch.sha256);total+=sum(row['size_bytes'] for row in epoch.artifact_bindings.values())
    doc=dict(format=LIBRARY_FORMAT,schema=1,kind='declared',execution_evidence=False,machine=machine,
             epochs=[dict(path=f'epochs/e{i:04d}/overlay.json',sha256=e.sha256) for i,e in enumerate(epochs)])
    raw=_canonical(doc,MAX_JSON)
    if total+len(raw)>MAX_LIBRARY:raise ValueError('Combined overlay library exceeds 256 MiB')
    output.mkdir();(output/'epochs').mkdir()
    for i,epoch in enumerate(epochs):
        root=output/'epochs'/f'e{i:04d}';root.mkdir();_copy(epoch.artifact_bindings,epoch.path.parent,root);epoch.revalidate()
    with (output/'library.json').open('xb') as stream:stream.write(raw)
    return load_library(output)


def copy_library(path,output):
    admitted=load_library(path);output=_new_directory(output)
    if output.is_relative_to(admitted.path.parent/'epochs'):raise ValueError('Overlay copy cannot modify its original epoch namespace')
    output.mkdir();bindings={name.removeprefix('member:'):row for name,row in admitted.artifact_bindings.items() if name.startswith('member:')}
    _copy(bindings,admitted.path.parent,output)
    with (output/'roots.json').open('xb') as stream:stream.write(_bytes(admitted.path,admitted.artifact_bindings['declarations']))
    admitted.revalidate();copied=load_library(output/'roots.json')
    if copied.sha256!=admitted.sha256:raise ValueError('Overlay library copy changed provenance')
    return copied
