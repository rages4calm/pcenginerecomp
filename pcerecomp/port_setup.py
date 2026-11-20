"""Portable source SDK/setup kits and player-owned-media recompilation.

Architecture inspired by RondoRecomp's player-side generation, with permission.
No media, RAM snapshots, captured code or generated game C++ enters a kit.
Toolchains are explicit local inputs; export never downloads or installs them.
"""
from copy import deepcopy
from pathlib import Path,PurePosixPath
from contextlib import contextmanager
import hashlib,json,os,shutil,sys
from . import project,prepare
from .declarations import _fields,_ordinary,_path,_digest
from .snapshots import SnapshotStore
from .loader_sweep import write,consumer_session,sweep,plan
from .feedback import prepare_feedback
from .overlay_snapshot import exact

FORMAT='pce-port-setup-1'
def profile(value):
    value=deepcopy(value);_fields(value,{'format','schema','recipe','bootstrap','route','loader','assets'},'port setup profile')
    if value['format']!=FORMAT or type(value['schema']) is not int or value['schema']!=1:raise ValueError('Unsupported setup profile')
    if type(value['recipe']) is not dict or type(value['bootstrap']) is not dict:raise ValueError('Setup requires explicit recipe/numeric bootstrap')
    spec=value['recipe']
    project._table(spec,{'schema','format','name','module','runtime','limits'},{'boot','payload'}|project.ASSETS,name='setup recipe')
    if type(spec['name']) is not str or not 1<=len(spec['name'])<=64 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in spec['name']):raise ValueError('Portable setup name required')
    if spec.get('module')!={'kind':'declared','path':'bootstrap.json'}:raise ValueError('Setup bootstrap must use its owned numeric declaration')
    if 'sdk' in spec:raise ValueError('Kit uses the exact exported SDK pin')
    names=value['assets']
    if type(names) is not dict or not names or set(names)-{'bios','disc','libchdr','cartridge','payload','toc'}:raise ValueError('Explicit setup asset slots required; persistent owner saves excluded')
    for key,hashes in names.items():
        if key not in spec or type(spec[key]) is not dict or spec[key].get('path')!='$'+key:raise ValueError('Recipe paths must be asset placeholders')
        if type(hashes) is not list or not 1<=len(hashes)<=32:raise ValueError('Setup asset requires1..32known SHA256 values')
        for sha in hashes:_digest(sha)
    # No secondary recipe file may smuggle a path to private media or captures.
    for key,table in spec.items():
        if key not in ('module',*names) and type(table) is dict and 'path' in table:raise ValueError('Unbound setup recipe path')
    route=value['route']
    if type(route) is not list or not 1<=len(route)<=256:raise ValueError('Setup needs a finite baseline route')
    from .capture import integer
    for segment in route:
        if type(segment) is not dict or set(segment)-{'frames','buttons','writes'} or not {'frames','buttons'}<=segment.keys():raise ValueError('Invalid setup route segment')
        integer(segment['frames'],600,'route frames',1);integer(segment['buttons'],4095,'route buttons')
        writes=segment.get('writes',[])
        if type(writes) is not list or len(writes)>16:raise ValueError('Setup route writes exceed explicit bound')
        for edit in writes:
            _fields(edit,{'address','data','expected'},'setup data edit');integer(edit['address'],0x1FFFFF,'data edit')
            for key in ('data','expected'):
                text=edit[key]
                if type(text) is not str or not 2<=len(text)<=512 or len(text)%2 or any(c not in '0123456789abcdef' for c in text):raise ValueError('Setup edits require bounded lowercase hex')
            if len(edit['data'])!=len(edit['expected']):raise ValueError('Setup edit lengths differ')
    plan(value['loader'])
    bootstrap=value['bootstrap'];_fields(bootstrap,{'format','schema','kind','execution_evidence','image','roots'},'setup bootstrap')
    if (bootstrap['format'] not in ('pce-declared-roots-1','pce-declared-boot-roots-1') or type(bootstrap['schema']) is not int or bootstrap['schema']!=1
            or bootstrap['kind']!='declared' or bootstrap['execution_evidence'] is not False):raise ValueError('Bootstrap is an explicit numeric source declaration')
    offsets='rom_offsets' if bootstrap['format']=='pce-declared-roots-1' else 'source_offsets'
    if type(bootstrap['roots']) is not list or not 1<=len(bootstrap['roots'])<=256:raise ValueError('Explicit numeric bootstrap roots required')
    for row in bootstrap['roots']:
        _fields(row,{'pc','mpr','selector',offsets},'numeric bootstrap root')
        integer(row['pc'],65535,'bootstrap PC');integer(row['selector'],15,'bootstrap selector')
        if type(row['mpr']) is not list or len(row['mpr'])!=8:raise ValueError('Bootstrap MPR bytes required')
        for byte in row['mpr']:integer(byte,255,'bootstrap MPR')
        if type(row[offsets]) is not list or not 1<=len(row[offsets])<=7:raise ValueError('Bootstrap numeric offsets required')
        for offset in row[offsets]:integer(offset,16*1024*1024,'bootstrap offset')
    image=bootstrap['image']
    if type(image) is not dict or 'sha256' not in image or not any(image['sha256'] in hashes for hashes in names.values()):raise ValueError('Bootstrap source hash must match a known asset slot')
    if offsets=='rom_offsets':_fields(image,{'sha256','profile','header','encoding'},'bootstrap image')
    elif image.get('kind')=='system-card':_fields(image,{'sha256','kind','profile'},'bootstrap image')
    elif image.get('kind')=='bios':_fields(image,{'sha256','kind'},'bootstrap image')
    elif image.get('kind')=='payload':_fields(image,{'sha256','kind','physical_load'},'bootstrap image')
    else:raise ValueError('Unsupported bootstrap source role')
    if offsets=='rom_offsets':
        from .cartridge import PROFILES,HEADERS,ENCODINGS
        for k,choices in (('profile',PROFILES),('header',HEADERS),('encoding',ENCODINGS)):
            if type(image[k]) is not str or image[k] not in choices:raise ValueError('Unsupported bootstrap ROM encoding/profile')
    elif image['kind']=='system-card' and image['profile'] not in ('standard','super'):raise ValueError('Unsupported System Card profile')
    elif image['kind']=='payload':integer(image['physical_load'],0x1FFFFF,'bootstrap payload location')
    return value

def _files(root):
    result={}
    for path in root.rglob('*'):
        if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&0x400:raise ValueError('Kit namespace cannot contain links/reparse points')
        if path.is_file():
            _ordinary(path,2*1024*1024*1024,minimum=0);result[path.relative_to(root).as_posix()]=dict(sha256=project.sha256(path),size_bytes=path.stat().st_size)
    return result

def export_kit(profile_path,output,*,toolchain_root=None):
    root=Path(__file__).resolve().parent.parent;output=_path(output);profile_path=_path(profile_path)
    _ordinary(profile_path,1048576);store=SnapshotStore();bound=store.read_json(profile_path,max_bytes=1048576);options=profile(bound.value)
    if output.exists() or output.is_symlink() or not output.parent.is_dir():raise ValueError('Kit output requires a new directory')
    if output.is_relative_to(root) and not output.is_relative_to(root/'.local'):raise ValueError('Use .local for private exported kits')
    identity=project.source_identity(root)
    if identity['revision'] is None:raise ValueError('SDK export requires an explicit source pin')
    toolchain=None;toolchain_files={}
    if toolchain_root is not None:
        toolchain=_path(toolchain_root)
        if not toolchain.is_dir() or output.is_relative_to(toolchain):raise ValueError('Invalid or overlapping toolchain root')
        for name in ('clang++','ninja','cmake'):_ordinary(toolchain/'bin'/(name+('.exe' if os.name=='nt' else '')),512*1024*1024)
        toolchain_files=_files(toolchain)
        if not any('license' in name.lower() or 'copying' in name.lower() for name in toolchain_files):raise ValueError('Bundled toolchain must retain its actual license notices')
    output.mkdir();sdk=output/'sdk';sdk.mkdir()
    sources=[root/'CMakeLists.txt',root/'LICENSE',root/'THIRD_PARTY.md']
    for directory in (*project.SOURCE_DIRS,'scripts','licenses'):
        sources.extend(p for p in (root/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.cpp','.hpp','.h','.cmake','.txt','.hlsl'))
    source_bindings={}
    for source in sorted(set(sources)):
        _ordinary(source,64*1024*1024);sha=project.sha256(source);relative=source.relative_to(root);target=sdk/relative;target.parent.mkdir(parents=True,exist_ok=True)
        with source.open('rb') as src,target.open('xb') as dest:shutil.copyfileobj(src,dest)
        if project.sha256(source)!=sha or project.sha256(target)!=sha:raise ValueError('SDK source changed during export')
        source_bindings[relative.as_posix()]=sha
    write(sdk/'pce-sdk.json',dict(format='pce-exported-sdk-1',schema=1,**identity))
    if project.source_identity(sdk)!=identity:raise ValueError('Exported SDK is not an exact source snapshot')
    write(output/'profile.json',options)
    (output/'setup_port.py').write_text('from pathlib import Path\nimport sys\nsys.dont_write_bytecode=True\nsys.path.insert(0,str(Path(__file__).resolve().parent/"sdk"))\nfrom pcerecomp.port_setup import main\nraise SystemExit(main())\n',encoding='utf-8',newline='\n')
    if toolchain:
        for name,binding in toolchain_files.items():
            source=toolchain/name;target=output/'toolchain'/name;target.parent.mkdir(parents=True,exist_ok=True)
            if project.sha256(source)!=binding['sha256']:raise ValueError('Toolchain changed during export')
            with source.open('rb') as src,target.open('xb') as dest:shutil.copyfileobj(src,dest)
            shutil.copymode(source,target)
            if project.sha256(target)!=binding['sha256']:raise ValueError('Toolchain copy differs')
    store.revalidate()
    if project.source_identity(root)!=identity:raise ValueError('SDK changed during export')
    files=_files(output);write(output/'KIT.json',dict(format='pce-port-kit-1',schema=1,tool=identity,files=files,toolchain_bundled=toolchain is not None,
        scope='Source SDK, authored numeric profile, optional explicitly supplied toolchain and its notices. No game/firmware bytes, captures, RAM images or generated game source. Python3.11+ is required.'))
    return verify_kit(output)

def verify_kit(root):
    root=_path(root);_ordinary(root/'KIT.json',64*1024*1024);store=SnapshotStore();manifest=store.read_json(root/'KIT.json',max_bytes=64*1024*1024).value
    _fields(manifest,{'format','schema','tool','files','toolchain_bundled','scope'},'port kit')
    if manifest['format']!='pce-port-kit-1' or type(manifest['schema']) is not int or manifest['schema']!=1 or type(manifest['toolchain_bundled']) is not bool:raise ValueError('Unsupported kit format')
    actual=_files(root);actual.pop('KIT.json')
    if not exact(actual,manifest['files']):raise ValueError('Kit file closure/fingerprints differ')
    identity=project.source_identity(root/'sdk')
    if not exact(identity,manifest['tool']):raise ValueError('Kit SDK pin differs')
    _ordinary(root/'profile.json',1048576);profile(store.read_json(root/'profile.json',max_bytes=1048576).value);store.revalidate()
    return dict(passed=True,tool=identity,files=len(actual),toolchain_bundled=manifest['toolchain_bundled'],execution_evidence=False)

@contextmanager
def compiler_environment(root):
    root=_path(root);suffix='.exe' if os.name=='nt' else '';compiler=root/'bin'/('clang++'+suffix);ninja=root/'bin'/('ninja'+suffix);cmake=root/'bin'/('cmake'+suffix)
    for path in (compiler,ninja,cmake):_ordinary(path,512*1024*1024)
    previous=os.environ.get('PATH','');os.environ['PATH']=str(root/'bin')+os.pathsep+previous
    try:yield ['-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)]
    finally:os.environ['PATH']=previous

def setup_port(profile_path,assets,output,compiler_root):
    profile_path=_path(profile_path);store=SnapshotStore();bound=store.read_json(profile_path,max_bytes=1048576);options=profile(bound.value);output=_path(output)
    if output.exists() or output.is_symlink() or not output.parent.is_dir():raise ValueError('Setup requires a new directory')
    if (profile_path.parent/'KIT.json').exists() and output.is_relative_to(profile_path.parent):raise ValueError('Setup output must be outside the immutable kit')
    if type(assets) is not dict or set(assets)!=set(options['assets']):raise ValueError('Provide exactly the profile asset slots')
    recipe=deepcopy(options['recipe']);asset_hashes={};asset_sources={}
    for key,source in assets.items():
        path=_path(source);_ordinary(path,16*1024*1024*1024)
        if output.is_relative_to(path.parent) and path.parent==output:raise ValueError('Setup cannot contain its original media')
        _,sha,cue=prepare._asset(path.parent,dict(path=path.name),key)
        if sha not in options['assets'][key]:raise ValueError('Unrecognized '+key+' input; nothing written')
        asset_hashes[key]=sha;asset_sources[key]=cue;recipe[key]['path']=str(path)
    store.revalidate();output.mkdir();write(output/'bootstrap.json',options['bootstrap'])
    (output/'bootstrap.toml').write_text(prepare._toml(recipe),encoding='utf-8',newline='\n');prepare.prepare_project(output/'bootstrap.toml',output/'bootstrap')
    with compiler_environment(compiler_root) as args:
        project.build(output/'bootstrap/project.toml',output/'bootstrap-build',generator='Ninja',cmake_args=args)
        checkpoints=output/'baseline-checkpoints';checkpoints.mkdir()
        with consumer_session(output/'bootstrap/project.toml',output/'bootstrap-build',output/'baseline',checkpoints,None) as (client,record):
            for segment in options['route']:
                for edit in segment.get('writes',[]):
                    client.write_memory(edit['address'],bytes.fromhex(edit['data']),bytes.fromhex(edit['expected']));record.setdefault('assistance',[]).append(edit)
                client.call('set_input',port=0,mask=segment['buttons']);client.advance(segment['frames'],reference=True)
            client.call('clear_input');record['checkpoint']=client.call('save_checkpoint',name='baseline.pcec')
        write(output/'loader.json',options['loader']);swept=sweep(output/'bootstrap/project.toml',output/'bootstrap-build',checkpoints,'baseline.pcec',output/'loader.json',output/'sweep')
        recipe['module']=dict(kind='overlay',path=str(output/'sweep/library/library.json'),partition_layout='shared',partition_size=1024,operand_sharing=True);recipe['runtime']['tier']='native'
        (output/'native.toml').write_text(prepare._toml(recipe),encoding='utf-8',newline='\n')
        captures=[output/'baseline/capture.jsonl']+[output/'sweep'/name/'capture.jsonl' for name in swept['sessions']]
        prepared=prepare_feedback(output/'native.toml',captures,output/'native')
        built=project.build(output/'native/consumer/project.toml',output/'native-build',generator='Ninja',cmake_args=args)
    store.revalidate()
    for key,source in assets.items():
        cue=asset_sources[key]
        if cue:cue.check_unchanged()
        if (cue.image_sha256() if cue else project.sha256(_path(source)))!=asset_hashes[key]:raise ValueError('Media changed during setup')
    value=dict(format='pce-port-setup-receipt-1',schema=1,passed=True,compiled=True,executed=False,discovery_executed=True,native_executed=False,tool=project.source_identity(Path(__file__).resolve().parent.parent),profile_sha256=bound.sha256,assets=asset_hashes,
        sweep=dict(epochs=swept['epochs'],identities=swept['identities']),preparation=prepared,build=built,
        scope='Player-owned inputs verified before writes; original guest reference baseline/loader probes captured, actual translated native package compiled. Final native gameplay is not yet qualified. Original captures/epochs retain their actual producers.')
    write(output/'setup.json',value);return value

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--profile',type=Path);parser.add_argument('--asset',action='append',default=[]);parser.add_argument('--out',required=True,type=Path);parser.add_argument('--compiler-root',type=Path);args=parser.parse_args(argv)
    kit=Path(sys.argv[0]).resolve().parent
    try:
        verify_kit(kit);assets={}
        for item in args.asset:
            key,sep,value=item.partition('=')
            if not sep or key in assets:raise ValueError('Asset syntax is SLOT=PATH, without duplicates')
            assets[key]=value
        result=setup_port(args.profile or kit/'profile.json',assets,args.out,args.compiler_root or kit/'toolchain');print(json.dumps(dict(passed=result['passed'],compiled=result['compiled'],executed=result['executed']),indent=2));return 0
    except (ValueError,OSError) as error:print(str(error),file=sys.stderr);return 2
