"""Build and step a separate ORIGINAL full Beetle PCE core on authored ROMs.

The original libretro frontend, CPU, full VCE/VDC scheduler, PSG, CD devices,
mapper, input and support implementations are compiled unchanged. Optional CHD
decoding and physical CD access are disabled for these authored HuCard cases.
No functions are extracted or replaced with plausible emulator stubs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
PIN='b96c11e095b6a40a412d2da02766ae1c3f4fd539'


def sha(data):return hashlib.sha256(data).hexdigest()
def binding(path):
    path=Path(path).resolve(strict=True)
    return dict(path=str(path),sha256=sha(path.read_bytes()),bytes=path.stat().st_size)


def run_command(command,out,label,commands,timeout=180):
    commands.append(command)
    result=subprocess.run(command,capture_output=True,timeout=timeout)
    (out/(label+'.stdout')).write_bytes(result.stdout);(out/(label+'.stderr')).write_bytes(result.stderr)
    if result.returncode:raise RuntimeError(f'{label} exited {result.returncode}; see retained stderr')
    return result


def source_snapshot(source,out):
    rows=subprocess.check_output(['git','-C',str(source),'ls-tree','-r',PIN],text=True).splitlines()
    target=out/'original-source';target.mkdir();files={}
    for row in rows:
        metadata,name=row.split('\t',1);mode,kind,blob=metadata.split()
        if kind!='blob' or mode not in('100644','100755'):raise ValueError('Unexpected reference tree object')
        if Path(name).suffix not in('.c','.cpp','.h','.hpp','.inc') and name not in('Makefile','Makefile.common','COPYING','README.md'):continue
        path=source/name;raw=path.read_bytes();normalized=raw.replace(b'\r\n',b'\n')
        git_hash=lambda data:hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        # Some upstream blobs themselves contain CRLF. Preserve those exact
        # committed bytes; only undo checkout CRLF conversion for LF blobs.
        if git_hash(raw)==blob:normalized=raw
        elif git_hash(normalized)!=blob:raise ValueError('Original reference source differs: '+name)
        saved=target/name;saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(normalized)
        files[name]=dict(original=binding(path),compiled=binding(saved),git_blob=blob)
    if 'mednafen/pce/huc6280.cpp' not in files:raise ValueError('Incomplete original core tree')
    # Tree identity includes every upstream path/blob; compile inputs are separately hashed.
    return target,sha(('\n'.join(rows)+'\n').encode()),files


def sources(tree):
    # The original Makefile.common PCE configuration, with optional CHD/physical
    # drive backends off. All original CPU and machine device files are included.
    cpp=['libretro.cpp']
    cpp += ['mednafen/pce/'+name+'.cpp'for name in('huc6280','huc','input','mcgenjin','pce','pcecd','tsushin','vce','input/gamepad','input/mouse','input/tsushinkb')]
    cpp += ['mednafen/'+name+'.cpp'for name in('hw_misc/arcade_card/arcade_card','hw_sound/pce_psg/pce_psg','hw_video/huc6270/vdc','settings','general','FileStream','MemoryStream','Stream','state','mempatcher','sound/okiadpcm','sound/OwlResampler')]
    cpp += ['mednafen/cdrom/'+name+'.cpp'for name in('CDAccess','CDAccess_Image','CDAccess_CCD','CDAFReader','CDAFReader_Vorbis','cdromif','CDUtility','lec','galois','recover-raw','l-ec','edc_crc32','scsicd')]
    c=['mednafen/sound/Blip_Buffer.c','mednafen/file.c','mednafen/mednafen-endian.c','mednafen/cputest/cputest.c']
    c += [p.relative_to(tree).as_posix()for p in sorted((tree/'mednafen/tremor').glob('*.c'))if p.name!='ivorbisfile_example.c']
    c += ['libretro-common/'+name+'.c'for name in('streams/file_stream','streams/file_stream_transforms','file/file_path','file/retro_dirent','lists/string_list','lists/dir_list','compat/compat_strl','compat/compat_snprintf','compat/compat_posix_string','compat/compat_strcasestr','compat/fopen_utf8','encodings/encoding_utf','encodings/encoding_crc32','vfs/vfs_implementation','memmap/memalign','string/stdstring','time/rtime')]
    original=(tree/'Makefile.common').read_text()
    for path in cpp+c:
        if not(tree/path).is_file():raise ValueError('Missing full-core compile input: '+path)
        if not path.startswith('mednafen/tremor/') and Path(path).name not in original:raise ValueError('Compile file absent from upstream recipe: '+path)
    return cpp,c


def quote(path):
    value=Path(path).resolve().as_posix()
    if any(ch in value for ch in('"',';','$','\n','\r')):raise ValueError('Unsafe CMake path')
    return '"'+value+'"'


def build(args,out,commands):
    tree,identity,files=source_snapshot(args.beetle_source.resolve(),out);cpp,c=sources(tree)
    compiler=Path(shutil.which(str(args.compiler))or'').resolve()
    c_name=compiler.name.replace('clang++','clang').replace('g++','gcc')
    c_compiler=compiler.with_name(c_name)
    cmake=Path(shutil.which(str(args.cmake))or'').resolve();ninja=Path(shutil.which(str(args.ninja))or'').resolve()
    if any(not p.is_file()for p in(compiler,c_compiler,cmake,ninja)):raise ValueError('Require existing C/C++ compilers/CMake/Ninja')
    wrapper=out/'wrapper';wrapper.mkdir()
    originals=[ROOT/'tests/beetle_cpu_probe.cpp',ROOT/'tests/reference_trace_support.hpp',Path(__file__)]
    epoch=out/'authored-inputs';epoch.mkdir()
    for p in originals:shutil.copyfile(p,epoch/p.name)
    probe=epoch/'beetle_cpu_probe.cpp';support=epoch/'reference_trace_support.hpp'
    lines=['cmake_minimum_required(VERSION 3.20)','project(OriginalBeetleCPU LANGUAGES C CXX)',
        'set(CMAKE_C_STANDARD 11)','set(CMAKE_CXX_STANDARD 20)',
        'add_executable(beetle-cpu '+quote(probe)+' '+ ' '.join(quote(tree/p)for p in cpp+c)+')',
        'target_include_directories(beetle-cpu PRIVATE '+ ' '.join(quote(p)for p in(tree,tree/'mednafen',tree/'mednafen/include',tree/'mednafen/hw_sound',tree/'mednafen/hw_cpu',tree/'mednafen/hw_misc',tree/'libretro-common/include',epoch))+')',
        'target_compile_definitions(beetle-cpu PRIVATE INLINE=inline WANT_PCE_EMU WANT_STEREO_SOUND WANT_16BPP FRONTEND_SUPPORTS_RGB565 NEED_TREMOR STDC_HEADERS __STDC_LIMIT_MACROS __LIBRETRO__ _LOW_ACCURACY_ MEDNAFEN_VERSION_NUMERIC=931 PACKAGE="mednafen")',
        # Public SyncReal is inline-defined in the original .cpp. Retain its
        # original called symbol for the external step callback; no body patch.
        'set_source_files_properties('+quote(tree/'mednafen/pce/vce.cpp')+' PROPERTIES COMPILE_OPTIONS "-fno-inline")',
        'if(WIN32)','target_link_libraries(beetle-cpu PRIVATE winmm)','endif()']
    cmakelists=wrapper/'CMakeLists.txt';cmakelists.write_text('\n'.join(lines)+'\n')
    build_dir=out/'build'
    run_command([str(cmake),'-S',str(wrapper),'-B',str(build_dir),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_COMPILER='+str(c_compiler),'-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],out,'configure',commands)
    run_command([str(cmake),'--build',str(build_dir),'--target','beetle-cpu','--parallel','4'],out,'build',commands,600)
    binary=build_dir/('beetle-cpu.exe'if os.name=='nt'else'beetle-cpu')
    manifest=dict(schema=1,engine='beetle-pce',revision=PIN,source_sha256=identity,
        profile='Original full PCE core; upstream optional CHD decoder and physical drive backend disabled',
        binary=binding(binary),files=files,authored=[binding(probe),binding(support),binding(epoch/Path(__file__).name)],
        authored_observed=[binding(p)for p in originals],
        build_inputs=[binding(cmakelists)],tools=[binding(p)for p in(compiler,c_compiler,cmake,ninja)],
        sources_cpp=cpp,sources_c=c)
    path=out/'build-binding.json';path.write_text(json.dumps(manifest,indent=2)+'\n')
    return path,manifest


def check_build(path):
    value=json.loads(path.read_text())
    if value['schema']!=1 or value['engine']!='beetle-pce'or value['revision']!=PIN:raise ValueError('Original full-core binding required')
    def check(row):
        if binding(row['path'])!=row:raise ValueError('Changed full-core build binding: '+row['path'])
    for row in [value['binary'],*value['authored'],*value['build_inputs'],*value['tools']]:check(row)
    for row in value['files'].values():check(row['original']);check(row['compiled'])
    return value


def run(args):
    out=args.out.resolve()
    if out.exists()or not out.is_relative_to(ROOT/'.local'):raise ValueError('Require NEW private output')
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,95}',args.case):raise ValueError('Safe case label required')
    if not 1<=args.steps<=99997 or not 0<=args.primer<=10000:raise ValueError('Bounded step counts required')
    rom=args.rom.resolve();before=binding(rom)
    if before['bytes']!=262144:raise ValueError('Require original authored 256KiB HuCard fixture')
    out.mkdir(parents=True);commands=[]
    driver=out/'driver-preserved.py';shutil.copyfile(Path(__file__),driver)
    report=dict(schema=1,passed=False,commands=commands,driver=binding(driver))
    try:
        if args.reuse_build:build_path=args.reuse_build.resolve();built=check_build(build_path)
        else:build_path,built=build(args,out,commands)
        dump=out/'final-wram.bin'
        actual=run_command([built['binary']['path'],str(rom),str(args.steps),str(args.primer),str(dump)],out,'probe',commands)
        body=actual.stdout.decode('utf-8')
        header=dict(type='header',schema=1,format='pce-cpu-trace-1',
            engine=dict(name='beetle-pce',revision=PIN,source_sha256=built['source_sha256'],binary_sha256=built['binary']['sha256']),
            fixture_sha256=before['sha256'],case=args.case,clock='master-ticks',phase='instruction-boundary',unavailable_fields=['mpr_latch'])
        trace_path=out/'trace.jsonl';trace_path.write_text(json.dumps(header,separators=(',',':'))+'\n'+body,encoding='utf-8',newline='\n')
        from pcerecomp.reference_trace import load_trace,compare_traces
        report['trace_validator']=binding(ROOT/'pcerecomp/reference_trace.py')
        trace=load_trace(trace_path)
        if trace.final['executed']!=args.steps or trace.instructions[-1]['state']['wram_sha256']!=binding(dump)['sha256']or dump.stat().st_size!=8192:raise ValueError('Independent hashlib/final-WRAM or step count mismatch')
        if binding(rom)!=before:raise ValueError('Authored ROM input changed')
        check_build(build_path)
        report.update(passed=True,build=binding(build_path),binary=built['binary'],fixture=before,
            raw_body=binding(out/'probe.stdout'),raw_stderr=binding(out/'probe.stderr'),trace=binding(trace_path),
            final_wram=binding(dump),steps=args.steps,primer=args.primer,raw_initial=trace.initial,
            engine=header['engine'],unavailable_fields=['mpr_latch'],
            scope='Full original Beetle PCE core; original instruction-step API and VCE/VDC event scheduler. '
                'Reset handled separately; optional ordinary software primer is unmeasured but raw measured origin retained. '
                'Repeated field/WRAM-hash inspection must be pure. No original MPR latch exists; it is null, never fabricated.')
        if args.compare:
            comparison=compare_traces(load_trace(args.compare),trace,profile=args.profile)
            comparison_path=out/'comparison.json';comparison_path.write_text(json.dumps(comparison,indent=2)+'\n')
            report['comparison']=binding(comparison_path);report['passed']=comparison['equal']
    except Exception as error:report['error']=repr(error);raise
    finally:(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if not report['passed']:raise ValueError('Independent comparison differs; raw evidence retained')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--beetle-source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--rom',type=Path,required=True);p.add_argument('--case',default='context-low')
    p.add_argument('--steps',type=int,default=40);p.add_argument('--primer',type=int,default=0)
    p.add_argument('--compiler',default='clang++');p.add_argument('--cmake',default='cmake');p.add_argument('--ninja',default='ninja')
    p.add_argument('--reuse-build',type=Path);p.add_argument('--compare',type=Path)
    p.add_argument('--profile',choices=('exact','architectural-v1','architectural-elapsed-v1'),default='exact')
    try:run(p.parse_args())
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:print(error,file=sys.stderr);raise SystemExit(1)
