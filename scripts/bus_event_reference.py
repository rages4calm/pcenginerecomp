"""Build separate pinned GPL software bus observers on authored finite fixtures.

The source patches add read-only return hooks and fetch suppression only. They do
not replace memory/CPU operations, disable FastMap, or alter guest clock charges.
Original-source, observer-disabled and observer-enabled runs are kept separately.
Raw streams remain private; chronological timing disagreements are diagnostics.
"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from scripts import beetle_reference as beetle
from scripts import mapper_reference as gear
from scripts import filtered_audio_reference as gear_sources
from bus_reference_fixture import fixture, generate, expected_accesses, expected_event_cycles


def binding(path):
    return beetle.binding(path)


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Original observer hook anchor differs: '+old[:100])
    return text.replace(old, new)


def wrap_function(text, signature, prefix, suffix):
    start = text.index(signature)
    begin = text.index('{', start)
    depth = 1
    end = begin+1
    while depth:
        depth += (text[end] == '{')-(text[end] == '}')
        end += 1
    return text[:begin+1]+prefix+text[begin+1:end-1]+suffix+text[end-1:]


def instrument(tree, engine):
    """Patch a fresh private snapshot; all original body statements survive."""
    changed = []
    def edit(relative, transform):
        path = tree/relative
        original = path.read_text(encoding='utf-8')
        result = transform(original)
        if result == original:
            raise ValueError('Observer patch did not change its exact input')
        path.write_text(result, encoding='utf-8', newline='\n')
        changed.append(dict(path=relative, original_sha256=hashlib.sha256(original.encode()).hexdigest(),
                            observed=binding(path)))
    if engine == 'Geargrafx':
        def memory(text):
            text = replace_once(text,
                '        else \n            return m_memory_map[bank][offset];',
                '        else \n        {\n            bus_reference_direct=true;\n            return m_memory_map[bank][offset];\n        }')
            text = wrap_function(text, 'INLINE u8 Memory::Read(u16 address, bool block_transfer)',
                '\n    bool bus_reference_direct=false;\n    const auto bus_reference_read=[&]() -> u8 {\n',
                '\n    };const auto bus_reference_value=bus_reference_read();\n'
                '    BUS_REFERENCE_ACCESS(address,GetPhysicalAddress(address),bus_reference_value,false,false,bus_reference_direct);\n'
                '    return bus_reference_value;\n')
            return wrap_function(text, 'INLINE void Memory::Write(u16 address, u8 value, bool block_transfer)',
                '\n    const auto bus_reference_write=[&]() {\n',
                '\n    };bus_reference_write();\n'
                '    BUS_REFERENCE_ACCESS(address,GetPhysicalAddress(address),value,true,false,false);\n')
        edit('src/memory_inline.h', memory)
        def fetch(text):
            for signature in ('INLINE u8 HuC6280::Fetch8()', 'INLINE u16 HuC6280::Fetch16()'):
                text = replace_once(text, signature+'\n{', signature+'\n{\n    BusReferenceFetchScope bus_reference_fetch;')
            return text
        edit('src/huc6280_inline.h', fetch)
    elif engine == 'beetle-pce':
        def cpu(text):
            text = replace_once(text,
                '\t\tif(FastPageR[address >> 13])\n\t\t\treturn *(uint8*)(FastPageR[address >> 13] + address);',
                '\t\tif(FastPageR[address >> 13])\n\t\t{\n'
                '\t\t\tconst uint8 observed=*(uint8*)(FastPageR[address >> 13] + address);\n'
                '\t\t\tBUS_REFERENCE_ACCESS(address,(MPR[address >> 13]<<13)|(address&0x1FFF),observed,false,false,true);\n'
                '\t\t\treturn observed;\n\t\t}')
            text = replace_once(text,
                '\t\treturn ReadMap[wmpr]((wmpr << 13) | (address & 0x1FFF));',
                '\t\tconst uint8 observed=ReadMap[wmpr]((wmpr << 13) | (address & 0x1FFF));\n'
                '\t\tBUS_REFERENCE_ACCESS(address,(wmpr<<13)|(address&0x1FFF),observed,false,false,false);\n'
                '\t\treturn observed;')
            text = replace_once(text, '\tuint8 INLINE RdOp(unsigned int address)\n\t{',
                '\tuint8 INLINE RdOp(unsigned int address)\n\t{\n\t\tBusReferenceFetchScope bus_reference_fetch;')
            return replace_once(text,
                '\t\tWriteMap[wmpr]((wmpr << 13) | (address & 0x1FFF), V);',
                '\t\tWriteMap[wmpr]((wmpr << 13) | (address & 0x1FFF), V);\n'
                '\t\tBUS_REFERENCE_ACCESS(address,(wmpr<<13)|(address&0x1FFF),V,true,false,false);')
        edit('mednafen/pce/huc6280.h', cpu)
    else:
        raise ValueError('Known independent core required')
    return changed


def invoke(command, out, label, commands, timeout=180):
    return beetle.run_command(command, out, label, commands, timeout)


def build(args, out, engine, fixture_dir, commands):
    out.mkdir()
    if engine == 'Geargrafx':
        original_bindings={}
        original, source = gear.pinned_snapshot(args.gear_source.resolve(), out, original_bindings)
        cpp, c = gear_sources.compile_sources(original, source)
        original_paths = [path.relative_to(original).as_posix() for path in cpp+c]
        source_identity = hashlib.sha256(json.dumps(source,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        license_path = args.gear_source.resolve()/'LICENSE'
        source_bindings = {name:dict(original=binding(args.gear_source.resolve()/name),compiled=binding(original/name)) for name in source}
        revision = gear.COMMIT
    else:
        original, source_identity, files = beetle.source_snapshot(args.beetle_source.resolve(), out)
        cpp, c = beetle.sources(original)
        original_paths = cpp+c
        source_bindings = files
        license_path = original/'COPYING'
        revision = beetle.PIN
    # Unmodified source baseline is separately compiled; never call an observer
    # macro-disabled patched body the unchanged original reference.
    observed = out/'observed-source'
    shutil.copytree(original, observed)
    patches = instrument(observed, engine)
    selected = 'geargrafx_bus_reference_probe.cpp' if engine == 'Geargrafx' else 'beetle_bus_reference_probe.cpp'
    authored = out/'authored'
    authored.mkdir()
    owned = ['bus_reference_hooks.hpp','bus_reference_support.hpp','reference_trace_support.hpp',selected]
    owned += ['geargrafx_mapper_probe.cpp','reset_probe_support.hpp'] if engine == 'Geargrafx' else ['beetle_cpu_probe.cpp']
    for name in owned:
        shutil.copyfile(ROOT/'tests'/name, authored/name)
    shutil.copyfile(fixture_dir/'bus_reference_fixture.hpp', authored/'bus_reference_fixture.hpp')
    probe = authored/selected
    quote = gear.cmake_quote
    lines = ['cmake_minimum_required(VERSION 3.20)','project(OriginalBusObservers LANGUAGES C CXX)',
        'set(CMAKE_C_STANDARD 11)','set(CMAKE_CXX_STANDARD 20)']
    for variant, tree in (('original',original),('observed',observed)):
        target = 'bus-'+variant
        lines += ['add_executable('+target+' '+quote(probe)+' '+' '.join(quote(tree/name)for name in original_paths)+')']
        if engine == 'Geargrafx':
            deps = tree/'platforms/shared/dependencies'
            includes = [tree/'src',authored,deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json']
            definitions = 'GG_DISABLE_DISASSEMBLER GG_DISABLE_VGMRECORDER GG_DISABLE_MMI_THREADS'
            lines += ['target_compile_options('+target+' PRIVATE -ffp-contract=off -ffunction-sections -fdata-sections "$<$<COMPILE_LANGUAGE:CXX>:-include;cerrno>")']
            libraries = [path.resolve(strict=True)for path in args.library]
            if not libraries:
                raise ValueError('Explicit original Gear external libraries required')
            lines += ['target_link_libraries('+target+' PRIVATE '+' '.join(quote(p)for p in libraries)+')',
                      'target_link_options('+target+' PRIVATE -Wl,--gc-sections)']
        else:
            includes = [tree,tree/'mednafen',tree/'mednafen/include',tree/'mednafen/hw_sound',tree/'mednafen/hw_cpu',tree/'mednafen/hw_misc',tree/'libretro-common/include',authored]
            definitions = 'INLINE=inline WANT_PCE_EMU WANT_STEREO_SOUND WANT_16BPP FRONTEND_SUPPORTS_RGB565 NEED_TREMOR STDC_HEADERS __STDC_LIMIT_MACROS __LIBRETRO__ _LOW_ACCURACY_ MEDNAFEN_VERSION_NUMERIC=931 PACKAGE="mednafen"'
            lines += ['set_source_files_properties('+quote(tree/'mednafen/pce/vce.cpp')+' PROPERTIES COMPILE_OPTIONS "-fno-inline")',
                      'if(WIN32)','target_link_libraries('+target+' PRIVATE winmm)','endif()']
        if variant == 'observed':
            definitions += ' PCE_BUS_REFERENCE_OBSERVER'
        lines += ['target_include_directories('+target+' PRIVATE '+' '.join(quote(p)for p in includes)+')',
            'target_compile_definitions('+target+' PRIVATE '+definitions+')',
            'target_compile_options('+target+' PRIVATE "$<$<COMPILE_LANGUAGE:CXX>:-include'+(authored/'bus_reference_hooks.hpp').as_posix()+'>")']
    wrapper = out/'wrapper'
    wrapper.mkdir()
    cmakelists = wrapper/'CMakeLists.txt'
    cmakelists.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    compiler = Path(shutil.which(str(args.compiler)) or '').resolve(strict=True)
    c_compiler = compiler.with_name(compiler.name.replace('clang++','clang').replace('g++','gcc'))
    cmake = Path(shutil.which(str(args.cmake)) or '').resolve(strict=True)
    ninja = Path(shutil.which(str(args.ninja)) or '').resolve(strict=True)
    build_dir = out/'build'
    invoke([str(cmake),'-S',str(wrapper),'-B',str(build_dir),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_COMPILER='+str(c_compiler),'-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],out,'configure',commands)
    invoke([str(cmake),'--build',str(build_dir),'--parallel','4'],out,'build',commands,600)
    suffix = '.exe' if os.name == 'nt' else ''
    binaries = {variant:binding(build_dir/('bus-'+variant+suffix))for variant in ('original','observed')}
    observed_files = [binding(path)for path in sorted(observed.rglob('*'))if path.is_file()]
    return dict(engine=engine,revision=revision,original_source_sha256=source_identity,
        observed_source_sha256=hashlib.sha256(json.dumps({path.relative_to(observed).as_posix():binding(path)['sha256']for path in sorted(observed.rglob('*'))if path.is_file()},sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        original_sources=source_bindings,observer_sources=observed_files,patches=patches,
        license=binding(license_path),authored=[binding(path)for path in sorted(authored.iterdir())],
        tools=[binding(path)for path in (compiler,c_compiler,cmake,ninja)],build_inputs=[binding(cmakelists)],
        libraries=[binding(path)for path in args.library] if engine=='Geargrafx' else [],binaries=binaries)


def raw_rows(path):
    rows = [json.loads(line)for line in path.read_text(encoding='utf-8').splitlines()]
    if not rows or rows[0].get('type')!='initial' or rows[-1].get('type')!='closure':
        raise ValueError('Incomplete original raw observer stream')
    return rows


def compare_nonperturbation(original, disabled, observed):
    remove = lambda rows:[row for row in rows if row['type']!='access' and row['type']!='closure']
    if remove(original)!=remove(disabled) or remove(original)!=remove(observed):
        raise ValueError('Original observation changes source/state/WRAM/clocks')
    if any(row['type']=='access'for row in original+disabled):
        raise ValueError('Disabled reference emitted access observations')
    for rows in (original,disabled,observed):
        end=rows[-1]
        if end['calls']!=sum(row['type']=='entry'for row in rows) or end['retired']!=sum(row.get('retired',0)for row in rows if row['type']=='retired') or end['events']!=sum(row['type']=='access'for row in rows):
            raise ValueError('Original raw accounting differs')
    return dict(equal=True,calls=observed[-1]['calls'],retired=observed[-1]['retired'],events=observed[-1]['events'],
        direct_reads=observed[-1]['direct_reads'],handler_reads=observed[-1]['handler_reads'])


def bus_stream(raw, built, profile, firmware):
    from pcerecomp import bus_trace
    def state(value):
        return {key:item for key,item in value.items()if key!='mpr_latch'}
    rows=[dict(type='header',schema=1,format=bus_trace.FORMAT,
        engine=dict(name=built['engine'],revision=built['revision'],source_sha256=built['observed_source_sha256'],binary_sha256=built['binaries']['observed']['sha256']),
        fixture_sha256=binding(firmware)['sha256'],case='authored-bus-'+profile,clock='master-ticks',
        profile=bus_trace.PROFILE,phase=bus_trace.PHASE,call_model='split',
        capabilities={key:key in ('mapped','data')for key in bus_trace.CAPABILITIES},
        limits=dict(calls=100,events=1000,retired=raw[-1]['retired'],wall_ms=180000))]
    for row in raw:
        if row['type']=='initial':
            rows.append(dict(type='initial',state=state(row['state'])))
        elif row['type']=='entry':
            entry=state(row['state'])
            rows.append(dict(type='call-begin',ordinal=row['instruction'],entry=entry,
                source=bus_trace.source_identity(entry['pc'],entry['mpr'],bytes(row['source_bytes']))))
        elif row['type']=='access':
            direction='write'if row['write']else'read'
            rows.append(dict(type='access',ordinal=row['ordinal'],call_ordinal=row['instruction'],
                ticks=row['tick'],direction=direction,phase=direction+'-return',space='fixed-vdc'if row['fixed']else'mapped',
                logical=row['logical'],mpr=row['mpr'],physical=row['physical'],value=row['value'],purpose=None,dummy=None))
        elif row['type']=='retired':
            rows.append(dict(type='call-end',ordinal=row['instruction'],kind='execution-call',state=state(row['state']),
                retired=row['retired'],native=None,interpreted=None,irq=None))
        elif row['type']=='closure':
            rows.append(dict(type='final',calls=row['calls'],retired=row['retired'],events=row['events'],stop='retirement-limit',complete=True,state=rows[-1]['state']))
        else:
            raise ValueError('Unknown raw original record')
    encoded=bus_trace.encode_records(rows)
    return encoded,bus_trace.parse_trace(encoded)


def verify_bindings(value):
    if type(value)is dict:
        if set(value)=={'path','sha256','bytes'}:
            if binding(value['path'])!=value:
                raise ValueError('Changed retained execution binding: '+value['path'])
        else:
            for item in value.values():verify_bindings(item)
    elif type(value)is list:
        for item in value:verify_bindings(item)


def source_refusal_controls(out, builds, fixture_dir, commands):
    raw, description=fixture('low')
    changed=bytearray(raw)
    changed[description['marker']-0xE000+1]^=1
    path=out/'changed-entry-source.pce';path.write_bytes(changed)
    result={}
    for engine,built in builds.items():
        command=[built['binaries']['observed']['path'],str(path),'low','1']
        commands.append(command)
        observed=subprocess.run(command,capture_output=True,timeout=180)
        label='gear'if engine=='Geargrafx'else'beetle'
        stdout=out/(label+'-source-refusal.stdout');stderr=out/(label+'-source-refusal.stderr')
        stdout.write_bytes(observed.stdout);stderr.write_bytes(observed.stderr)
        if observed.returncode!=1 or b'Actual candidate bytes differ'not in observed.stderr:
            raise ValueError('Altered actual original entry bytes were not refused')
        rows=raw_rows(stdout)if b'"closure"'in observed.stdout else [json.loads(line)for line in observed.stdout.splitlines()]
        if any(row['type']in ('access','retired','closure')for row in rows):
            raise ValueError('Refused source must not execute or claim completion')
        result[label]=dict(returncode=observed.returncode,changed_fixture=binding(path),stdout=binding(stdout),stderr=binding(stderr),
            refused_before_measured_execution=True,complete=False)
    return result


def run(args):
    out=args.out.resolve()
    if out.exists()or not out.is_relative_to(ROOT/'.local'):
        raise ValueError('New private output required')
    out.mkdir(parents=True)
    commands=[]
    report=dict(schema=1,result='incomplete',commands=commands,
        scope='Finite authored software read-return/write-return observations, original full separately linked GPL cores; no hardware-pin, idle/dummy, fetch, arbitrary MMIO/IRQ or retail-game qualification.')
    try:
        inputs=out/'inputs';inputs.mkdir()
        for source in [Path(__file__),ROOT/'tests/bus_reference_fixture.py',ROOT/'scripts/beetle_reference.py',ROOT/'scripts/mapper_reference.py',ROOT/'scripts/filtered_audio_reference.py']:
            shutil.copyfile(source,inputs/source.name)
        report['driver_inputs']=[binding(path)for path in inputs.iterdir()]
        fixture_dir=out/'fixture';generate(fixture_dir)
        report['fixture']=[binding(path)for path in fixture_dir.iterdir()]
        if args.reuse_build:
            reused=json.loads(args.reuse_build.read_text(encoding='utf-8'))
            verify_bindings(reused)
            builds=reused['builds']
            if set(builds)!={'Geargrafx','beetle-pce'}:
                raise ValueError('Both exact independent original builds required')
            for engine,revision in (('Geargrafx',gear.COMMIT),('beetle-pce',beetle.PIN)):
                if builds[engine]['revision']!=revision:
                    raise ValueError('Pinned independent reference revision differs')
            report['reused_build_receipt']=binding(args.reuse_build)
            for engine in args.rebuild_engine:
                builds[engine]=build(args,out/('gear'if engine=='Geargrafx'else'beetle'),engine,fixture_dir,commands)
        else:
            if args.rebuild_engine:
                raise ValueError('Selective reference rebuild requires explicit reused build receipt')
            builds={engine:build(args,out/('gear'if engine=='Geargrafx'else'beetle'),engine,fixture_dir,commands)for engine in ('Geargrafx','beetle-pce')}
        report['builds']=builds;report['runs']={}
        for engine,built in builds.items():
            label='gear'if engine=='Geargrafx'else'beetle'
            for profile in ('low','high','block'):
                paths={};rows={}
                for variant,enable in (('original',False),('disabled',False),('observed',True)):
                    binary=built['binaries']['original'if variant=='original'else'observed']['path']
                    name=label+'-'+profile+'-'+variant
                    invoke([binary,str(fixture_dir/(profile+'.pce')),profile,'1'if enable else'0'],out,name,commands)
                    path=out/(name+'.stdout');paths[variant]=binding(path);rows[variant]=raw_rows(path)
                parity=compare_nonperturbation(rows['original'],rows['disabled'],rows['observed'])
                events=[dict(direction='write'if row['write']else'read',logical=row['logical'],value=row['value'],mpr=row['mpr'],physical=row['physical'])for row in rows['observed']if row['type']=='access']
                if events!=expected_accesses(profile):
                    raise ValueError('Original accesses differ from independent authored literals')
                origin=rows['observed'][0]['state']['ticks']
                divisor=rows['observed'][0]['state']['clock_divisor']
                actual_ticks=[row['tick']for row in rows['observed']if row['type']=='access']
                cycle_literals=expected_event_cycles(profile,engine)
                if actual_ticks!=[origin+divisor*cycle for cycle in cycle_literals]:
                    raise ValueError('Actual software callback ticks differ from finite source-derived cycle literals')
                if profile!='block'and engine=='beetle-pce'and (not parity['direct_reads']or not parity['handler_reads']):
                    raise ValueError('Both unmodified FastMap and handler read paths required')
                encoded,trace=bus_stream(rows['observed'],built,profile,fixture_dir/(profile+'.pce'))
                trace_path=out/(label+'-'+profile+'-trace.jsonl');trace_path.write_bytes(encoded)
                report['runs'][label+'-'+profile]=dict(nonperturbation=parity,raw=paths,trace=binding(trace_path),literal_accesses=len(events),
                    callback_cycles=cycle_literals,clock_origin=origin,clock_divisor=divisor)
        from pcerecomp.bus_trace import load_trace,compare_traces
        report['original_core_diagnostics']={}
        for profile in ('low','high','block'):
            comparison=compare_traces(load_trace(out/('gear-'+profile+'-trace.jsonl')),
                load_trace(out/('beetle-'+profile+'-trace.jsonl')),profile='elapsed-origin-v1',structural=True)
            if comparison['equal']:
                raise ValueError('Expected raw callback phase difference was lost')
            if profile!='block'and not comparison['structural_correspondence']['matched']:
                raise ValueError('Unexpected scalar original architecture/source/access disagreement')
            path=out/('gear-beetle-'+profile+'-comparison.json')
            path.write_text(json.dumps(comparison,indent=2)+'\n',encoding='utf-8')
            report['original_core_diagnostics'][profile]=binding(path)
        report['source_refusal_controls']=source_refusal_controls(out,builds,fixture_dir,commands)
        verify_bindings(report)
        report['preserved_inputs_and_outputs']=True
        report['result']='pass-original-observer-nonperturbation'
    except Exception as error:
        report.update(result='fail',error=repr(error));raise
    finally:
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(result=report['result'],runs={name:row['nonperturbation']for name,row in report['runs'].items()}),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True)
    parser.add_argument('--beetle-source',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--compiler',default='clang++')
    parser.add_argument('--cmake',default='cmake')
    parser.add_argument('--ninja',default='ninja')
    parser.add_argument('--library',type=Path,action='append',default=[])
    parser.add_argument('--reuse-build',type=Path,help='Revalidate and reuse both separately compiled original/observer binaries from an earlier receipt; never relabel as rebuilt')
    parser.add_argument('--rebuild-engine',choices=('Geargrafx','beetle-pce'),action='append',default=[],help='With --reuse-build, freshly rebuild this engine while retaining the other verified binary')
    try:run(parser.parse_args())
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:
        print(error,file=sys.stderr);raise SystemExit(1)
