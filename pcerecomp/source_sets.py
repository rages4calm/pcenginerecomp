"""Closed numeric declaration sets; source images remain external fixed assets."""
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib,json,re
from pathlib import Path

from .declarations import (MAX_DECLARATION_BYTES,MAX_IMAGE_BYTES,MAX_ROOTS,
    _ordinary,_path,_fields,_digest,_binding,instruction_key,_sort_key)
from .snapshots import SnapshotStore

FORMAT='pce-declared-source-set-1'
MAX_MEMBERS=64
ASSETS=frozenset(('cartridge','bios','payload'))
MEMBER_DIR='declared-sources'


def is_source_set(path):
    path=_path(path);_ordinary(path,MAX_DECLARATION_BYTES)
    value=SnapshotStore().read_json(path,max_bytes=MAX_DECLARATION_BYTES).value
    return type(value) is dict and value.get('format')==FORMAT


def _id(value):
    if type(value) is not str or re.fullmatch('[a-z][a-z0-9_-]{0,63}',value) is None:
        raise ValueError('Source member ID requires a portable lowercase identifier')
    return value


def _images(value):
    if type(value) is not dict or not value or any(type(k) is not str or k not in ASSETS for k in value):
        raise ValueError('Source sets require an explicit asset-to-image dictionary')
    return {k:_path(v) for k,v in value.items()}


def _numeric_bytes(path,sha):
    _ordinary(path,MAX_DECLARATION_BYTES)
    with path.open('rb') as stream:raw=stream.read(MAX_DECLARATION_BYTES+1)
    if len(raw)>MAX_DECLARATION_BYTES or hashlib.sha256(raw).hexdigest()!=sha:
        raise ValueError('Source member changed while copying')
    return raw


def manifest_members(doc):
    """Validate the portable numeric graph without resolving external images."""
    _fields(doc,{'format','schema','kind','execution_evidence','sources'},'declaration source set')
    if doc['format']!=FORMAT or type(doc['schema']) is not int or doc['schema']!=1 or doc['kind']!='declared' or doc['execution_evidence'] is not False:
        raise ValueError('Unsupported source-set format/schema/kind/evidence')
    rows=doc['sources']
    if type(rows) is not list or not 1<=len(rows)<=MAX_MEMBERS:raise ValueError('Source sets require one to 64 declaration members')
    seen=set()
    for row in rows:
        _fields(row,{'id','asset','path','sha256'},'source-set member');name=_id(row['id'])
        if name in seen:raise ValueError('Duplicate source member ID')
        seen.add(name)
        if type(row['asset']) is not str or row['asset'] not in ASSETS:raise ValueError('Invalid source member asset')
        if row['path']!=f'{MEMBER_DIR}/{name}.json':raise ValueError('Invalid source member path')
        _digest(row['sha256'])
    return rows


@dataclass(frozen=True)
class AdmittedSourceSet:
    path: Path
    sha256: str
    _instructions: list
    _roots: list
    _source_metadata: dict
    _artifact_bindings: dict
    _diagnostics: list
    _store: SnapshotStore
    _members: tuple
    _images: dict
    format: str=FORMAT

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
    def members(self):return [dict(id=i,asset=a,format=d.format,sha256=d.sha256,source=d.source_metadata) for i,a,d in self._members]
    @property
    def static_reachability(self):return 'not_inferred'

    def revalidate(self):
        _ordinary(self.path,MAX_DECLARATION_BYTES)
        for _,_,d in self._members:_ordinary(d.path,MAX_DECLARATION_BYTES)
        for p in self._images.values():_ordinary(p,MAX_IMAGE_BYTES)
        expected={d.path.name for _,_,d in self._members}
        if {p.name for p in (self.path.parent/MEMBER_DIR).iterdir()}!=expected:
            raise ValueError('Source-set member namespace is not closed')
        self._store.revalidate()
        _ordinary(self.path,MAX_DECLARATION_BYTES)
        for _,_,d in self._members:_ordinary(d.path,MAX_DECLARATION_BYTES)
        for p in self._images.values():_ordinary(p,MAX_IMAGE_BYTES)
        if {p.name for p in (self.path.parent/MEMBER_DIR).iterdir()}!=expected:
            raise ValueError('Source-set member namespace is not closed')


def admit(path,source_images,store,snapshot):
    from .declarations import load_declarations
    rows=manifest_members(snapshot.value);images=_images(source_images);numeric_bytes=snapshot.size_bytes
    for row in rows:
        if row['asset'] not in images:
            raise ValueError('Source member requires an available explicit boot asset')
        member=path.parent/row['path'];_ordinary(member,MAX_DECLARATION_BYTES)
        numeric_bytes+=member.stat().st_size
    if numeric_bytes>MAX_DECLARATION_BYTES:raise ValueError('Combined source-set numeric inputs exceed 64 MiB')
    members=[];union={};roots=[];diagnostics=[];membership=Counter();metadata=[];bindings={'declarations':_binding(snapshot)};used={};asset_sha={}
    for row in rows:
        member=path.parent/row['path'];bound=store.read_json(member,expected_sha256=row['sha256'],max_bytes=MAX_DECLARATION_BYTES)
        d=load_declarations(member,images[row['asset']])
        if d.sha256!=bound.sha256:raise ValueError('Source member changed during admission')
        source=d.source_metadata;asset=row['asset'];sha=source['image_sha256']
        if asset in asset_sha and asset_sha[asset]!=sha:raise ValueError('Source members disagree on one asset image')
        asset_sha[asset]=sha;used[asset]=images[asset]
        image_bound=store.bind(images[asset],expected_sha256=sha)
        instructions=d.instructions
        for ins in instructions:union[instruction_key(ins)]=ins
        membership.update(instruction_key(ins) for ins in instructions)
        roots.extend(dict(source_id=row['id'],**root) for root in d.roots)
        if len(roots)>MAX_ROOTS:raise ValueError('Combined declared root count exceeds its bound; no entries dropped')
        diagnostics.extend(dict(source_id=row['id'],**item) for item in d.diagnostics)
        metadata.append(dict(id=row['id'],asset=asset,format=d.format,sha256=d.sha256,source=source,roots=len(d.roots),identities=len(instructions)))
        bindings['member:'+row['path']]=_binding(bound);bindings['source_image:'+asset]=_binding(image_bound);members.append((row['id'],asset,d))
    if sum(value['size_bytes'] for key,value in bindings.items() if key=='declarations' or key.startswith('member:'))>MAX_DECLARATION_BYTES:
        raise ValueError('Combined source-set numeric inputs grew beyond 64 MiB')
    value=AdmittedSourceSet(path,snapshot.sha256,sorted(union.values(),key=_sort_key),roots,
        dict(format=FORMAT,members=metadata,memberships=sum(membership.values()),overlapping_identities=sum(n>1 for n in membership.values())),
        bindings,diagnostics,store,tuple(members),used)
    value.revalidate();return value


def copy_source_set(path,output,source_images):
    from .declarations import load_declarations
    from .discovery import _directory
    admitted=load_declarations(path,source_images=source_images);output=_path(output)
    if output.is_relative_to(admitted.path.parent/MEMBER_DIR):raise ValueError('Source-set copy cannot modify its original member namespace')
    if output.exists() or output.is_symlink():raise ValueError('Source-set copy requires a new directory')
    _directory(output.parent);output.mkdir();(output/MEMBER_DIR).mkdir()
    for target,source in [(output/'roots.json',admitted.path)]+[(output/MEMBER_DIR/d.path.name,d.path) for _,_,d in admitted._members]:
        sha=admitted.sha256 if source==admitted.path else next(d.sha256 for _,_,d in admitted._members if d.path==source)
        raw=_numeric_bytes(source,sha)
        with target.open('xb') as stream:stream.write(raw)
    admitted.revalidate();copied=load_declarations(output/'roots.json',source_images=source_images)
    if copied.sha256!=admitted.sha256 or copied.source_metadata!=admitted.source_metadata:raise ValueError('Source-set copy changed its closure')
    return copied


def compose_source_set(members,output,source_images):
    """Copy exact numeric annotations, never copy media or manufacture captures."""
    from .declarations import load_declarations
    from .discovery import _directory
    images=_images(source_images)
    if type(members) not in (list,tuple) or not 1<=len(members)<=MAX_MEMBERS:raise ValueError('Expected one to 64 source members')
    admitted=[];names=set();total=0;count=0
    for row in members:
        _fields(row,{'id','asset','path'},'source composition member');name=_id(row['id'])
        if name in names:raise ValueError('Duplicate source member ID')
        names.add(name);asset=row['asset']
        if type(asset) is not str or asset not in ASSETS or asset not in images:raise ValueError('Source member requires an available boot asset')
        d=load_declarations(row['path'],images[asset]);total+=d.path.stat().st_size;count+=len(d.roots)
        if total>MAX_DECLARATION_BYTES or count>MAX_ROOTS:raise ValueError('Combined source-set bounds exceeded')
        admitted.append((name,asset,d))
    doc=dict(format=FORMAT,schema=1,kind='declared',execution_evidence=False,
        sources=[dict(id=name,asset=asset,path=f'{MEMBER_DIR}/{name}.json',sha256=d.sha256) for name,asset,d in admitted])
    raw=(json.dumps(doc,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
    if total+len(raw)>MAX_DECLARATION_BYTES:raise ValueError('Combined source-set numeric inputs exceed 64 MiB')
    output=_path(output)
    if output.exists() or output.is_symlink():raise ValueError('Source composition requires a new directory')
    _directory(output.parent);output.mkdir();(output/MEMBER_DIR).mkdir()
    for name,_,d in admitted:
        content=_numeric_bytes(d.path,d.sha256)
        with (output/MEMBER_DIR/(name+'.json')).open('xb') as stream:stream.write(content)
        d.revalidate()
    with (output/'roots.json').open('xb') as stream:stream.write(raw)
    return load_declarations(output/'roots.json',source_images=images)
