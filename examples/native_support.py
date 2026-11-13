"""Small shared authoring helpers; receipts do not themselves qualify execution."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(value,indent=2,allow_nan=False)+'\n')

def process(out,name,command,*,timeout=180,env=None):
    argv=list(map(str,command));timed_out=False
    try:
        result=subprocess.run(argv,capture_output=True,timeout=timeout,env=env)
        stdout,stderr,code=result.stdout,result.stderr,result.returncode
    except subprocess.TimeoutExpired as error:
        stdout,stderr,code=error.stdout or b'',error.stderr or b'',None;timed_out=True
    for suffix,data in (('stdout',stdout),('stderr',stderr)):
        with (out/(name+'.'+suffix)).open('xb') as stream:stream.write(data)
    write(out/(name+'-process.json'),dict(argv=argv,exit_code=code,timed_out=timed_out,
        stdout_sha256=digest(out/(name+'.stdout')),stderr_sha256=digest(out/(name+'.stderr'))))
    if timed_out:raise ValueError(name+' timed out; partial output retained')
    if code:raise ValueError(name+' refused: '+stderr.decode(errors='replace'))
    return result

def build_probe(root,module,build_dir,out,source,target):
    """Link a probe against the exact official archive, without another runtime build."""
    from pcerecomp.project import _cmake_path
    archives=[p for p in build_dir.rglob('*') if p.name in ('libpce-runtime.a','pce-runtime.lib')]
    if len(archives)!=1:raise ValueError('Expected one exact official runtime archive')
    options={}
    for line in (build_dir/'CMakeCache.txt').read_text().splitlines():
        if '=' in line and ':' in line.split('=',1)[0]:
            key,value=line.split('=',1);options[key.split(':',1)[0]]=value
    cmake=shutil.which('cmake')
    if not cmake:raise ValueError('CMake required')
    def q(p):return _cmake_path(Path(p))
    text=f'''cmake_minimum_required(VERSION 3.20)
project(AuthoredProbe LANGUAGES CXX)
add_library(pce-runtime STATIC IMPORTED GLOBAL)
set_target_properties(pce-runtime PROPERTIES IMPORTED_LOCATION {q(archives[0])}
 INTERFACE_INCLUDE_DIRECTORIES {q(root/'runtime/include')} INTERFACE_COMPILE_FEATURES cxx_std_20)
include({q(root/'cmake/PCEConsumer.cmake')})
pce_add_native_module(native_objects MODULE {q(module/'module.cpp')} MANIFEST {q(module/'module.json')})
add_executable({target} {q(source)})
target_include_directories({target} PRIVATE {q(out)})
target_link_libraries({target} PRIVATE pce-runtime ${{native_objects}} ${{CMAKE_DL_LIBS}})
if(WIN32)
 target_link_libraries({target} PRIVATE ws2_32)
endif()
'''
    (out/'CMakeLists.txt').write_text(text,encoding='utf-8')
    bound={str(p):digest(p) for p in (source,archives[0],out/'CMakeLists.txt')}
    process(out,'configure',[cmake,'-S',out,'-B',out/'build','-G',options['CMAKE_GENERATOR'],
        '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+options['CMAKE_CXX_COMPILER'],
        '-DCMAKE_MAKE_PROGRAM='+options['CMAKE_MAKE_PROGRAM']])
    process(out,'build',[cmake,'--build',out/'build','--config','Release','--parallel','2'])
    binary=out/'build'/(target+('.exe' if os.name=='nt' else ''))
    if not binary.is_file():binary=binary.parent/'Release'/binary.name
    if not binary.is_file():raise ValueError('Probe executable absent')
    if os.name=='nt':
        # Use the exact dependency closure already packaged by the official
        # consumer builder, so the probe does not depend on an SDK PATH entry.
        receipt=json.loads((build_dir.parent/'build-receipt.json').read_text())
        packaged=Path(receipt['binary']).parent
        for name,expected in receipt['output_files'].items():
            if Path(name).name!=name:raise ValueError('Invalid packaged dependency name')
            if Path(name).suffix.lower()!='.dll':continue
            dependency=packaged/name
            if digest(dependency)!=expected:raise ValueError('Packaged dependency changed')
            destination=binary.parent/name
            if destination.exists():raise ValueError('Probe dependency output already exists')
            shutil.copy2(dependency,destination)
            if digest(destination)!=expected:raise ValueError('Probe dependency copy differs')
            bound[str(dependency)]=expected;bound[str(destination)]=expected
    if any(digest(p)!=h for p,h in bound.items()):raise ValueError('Probe build inputs changed')
    return binary,bound
