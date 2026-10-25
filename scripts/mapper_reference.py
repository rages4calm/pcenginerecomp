"""Authored SF2/32-KiB cartridge RAM checks against separate Geargrafx.

The GPL reference is compiled separately from exact pinned Git blobs. Its
Populous RAM size is configured explicitly after loading; no CRC is spoofed.
Actual retired guest identities can be emitted and executed natively. This
checks finite emulator behavior, not electrical boards or a complete title.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from scripts import hucard_reference as common
from scripts import filtered_audio_reference as reference

COMMIT = reference.COMMIT
sha = reference.sha


def cmake_quote(path):
    value = Path(path).resolve().as_posix()
    if any(character in value for character in ('"', ';', '$', '\n', '\r')):
        raise ValueError('CMake path cannot be represented safely')
    return '"'+value+'"'


def authored_rom(profile):
    count = 320 if profile == 'sf2' else 64
    data = bytearray((bank*17+offset*13+(bank//256)*109) & 255
                     for bank in range(count) for offset in range(8192))
    # Low-speed authored guest. SF2 fetches four distinct subroutines through
    # the same logical PC/MPR/physical address after its own mapper writes.
    if profile == 'sf2':
        program = bytearray.fromhex('A9 F8 53 02 A9 40 53 04 A2 00')
        loop = len(program)
        program.extend(bytes.fromhex('A9 A5 9D F0 1F 20 00 41 9D 00 20 E8 E0 10 D0 00'))
        program[-1] = (loop-len(program)) & 255
        program.extend(bytes.fromhex('80 FE'))
        for selected in range(4):
            offset = 0x80000+selected*0x80000+0x100
            data[offset:offset+3] = bytes((0xA9, 0x40+selected, 0x60))
    else:
        program = bytearray.fromhex('A9 F8 53 02 A9 40 53 04 A9 44 53 08')
        program.extend(bytes.fromhex('A9 69 8D 31 40 AD 31 60 8D 00 20'))
        program.extend(bytes.fromhex('A9 43 53 04 A9 5F 53 08 A9 A7 8D 72 40 AD 72 60 8D 01 20 80 FE'))
    data[0x100:0x100+len(program)] = program
    data[8190:8192] = bytes((0, 0xE1))
    return bytes(data)


def plans(profile):
    mapped = [('r', 0, 0, 0, 0), ('s',)]
    if profile == 'sf2':
        for selector in range(16):
            for value in (0, 255, selector*13):
                mapped.append(('w', 0, 0x1FF0+selector, value))
                for bank in range(128):
                    for offset in (0, 8191):
                        mapped.extend((('q', bank, offset), ('p', bank, offset)))
        mapped.append(('w', 0, 0x1FF1, 0))
        for bank, offset in [(b, o) for b in (1, 63, 64, 127) for o in (0x1FF0, 0x1FFF)]:
            mapped.extend((('w', bank, offset, 3), ('q', 64, 0)))
        for offset in (0, 0x1000, 0x1FE0, 0x1FEF):
            mapped.extend((('w', 0, offset, 3), ('q', 64, 0)))
        mapped.extend((('q', 0, 0x100), ('p', 0, 0x100)))
    else:
        mapped = [('r', 0, 0, 0, 0xA5), ('s',)]
        for bank in range(128):
            for offset in (0, 31, 4096, 8191):
                mapped.extend((('q', bank, offset), ('p', bank, offset)))
        for bank in range(0x40, 0x60):
            for offset in (0, 31, 4096, 8191):
                mapped.append(('w', bank, offset, (bank*3+offset) & 255))
                for alias in range(0x40+(bank & 3), 0x60, 4):
                    mapped.extend((('q', alias, offset), ('p', alias, offset)))
        for bank in range(0x60, 0x80):
            mapped.extend((('q', bank, 0), ('p', bank, 8191)))
    guest = [('r', 0, 0, 0, 0), ('s',), ('i', 170 if profile == 'sf2' else 40)]
    for offset in range(16 if profile == 'sf2' else 2):
        guest.extend((('q', 0xF8, offset), ('p', 0xF8, offset)))
    reset = [('r', 0, 0, 0, 0), ('s',), ('q', 64, 0), ('p', 127, 8191)]
    return [dict(id=profile+'-'+name, operations=ops) for name, ops in
            (('map-and-writes', mapped), ('guest-code', guest), ('fresh-reset', reset))]


def serialize(cases):
    return '\n'.join(' '.join(map(str, op)) for case in cases for op in case['operations'])+'\n'


def expected_memory(records, cases, profile, image):
    """Independent authored ROM bytes and a sparse four-page RAM model."""
    common.validate_records(records, cases)
    index, checks, selector, ram_fill, ram = 0, 0, 0, 0, {}
    for case in cases:
        for operation in case['operations']:
            op = operation[0]
            if op == 'r':
                selector, ram_fill, ram = 0, operation[4], {}
            elif op in ('s', 'd'):
                index += 1
            elif op == 'i':
                index += operation[1]
                if profile == 'sf2':
                    selector = 15
                    for offset in range(16):
                        ram[(0xF8, offset)] = 0x40+offset % 4
                else:
                    ram[(0, 0x31)] = 0x69
                    ram[(3, 0x72)] = 0xA7
                    ram[(0xF8, 0)] = 0x69
                    ram[(0xF8, 1)] = 0xA7
            elif op == 'w':
                _, bank, offset, value = operation
                if profile == 'sf2' and bank == 0 and 0x1FF0 <= offset <= 0x1FFF:
                    selector = offset & 15
                elif profile == 'populous' and 0x40 <= bank < 0x60:
                    ram[(bank & 3, offset)] = value
            elif op in ('q', 'p'):
                _, bank, offset = operation
                if bank == 0xF8:
                    wanted = ram.get((0xF8, offset), ram_fill)
                elif profile == 'populous' and 0x40 <= bank < 0x60:
                    wanted = ram.get((bank & 3, offset), ram_fill)
                else:
                    if profile == 'sf2':
                        file_bank = bank if bank < 64 else bank+(selector % 4)*64
                    else:
                        file_bank = bank if bank < 64 else 32+(bank & 31)
                    wanted = image[file_bank*8192+offset]
                record = records[index]
                if record != dict(kind='memory' if op == 'q' else 'peek', values=[bank, offset, wanted]):
                    raise ValueError(f'Literal mapper expectation differs at observation {index}: {record}, wanted {wanted}')
                index += 1
                checks += 1
    if index != len(records):
        raise ValueError('Mapper literal observation accounting differs')
    return checks


def pinned_snapshot(checkout, out, bindings):
    """Verify Git blob identity after CRLF normalization; compile private LF."""
    prefix = 'platforms/shared/dependencies/'
    rows = subprocess.check_output(['git', '-C', str(checkout), 'ls-tree', '-r', COMMIT,
        'src', prefix+'miniz', prefix+'minivorbis', prefix+'qon', prefix+'json', prefix+'libchdr/include'], text=True).splitlines()
    target = out/'pinned-reference-source'
    target.mkdir()
    result = {}
    bindings['reference_raw_sources'] = {}
    bindings['reference_compile_sources'] = {}
    for row in rows:
        metadata, name = row.split('\t', 1)
        if Path(name).suffix not in ('.cpp', '.c', '.h', '.hpp'):
            continue
        mode, kind, blob = metadata.split()
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise ValueError('Unexpected reference source entry')
        path = checkout/name
        raw = path.read_bytes()
        normalized = raw.replace(b'\r\n', b'\n')
        actual = hashlib.sha1(b'blob '+str(len(normalized)).encode()+b'\0'+normalized).hexdigest()
        if actual != blob:
            raise ValueError('Pinned reference Git blob differs: '+name)
        saved = target/name
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(normalized)
        bindings['reference_raw_sources'][str(path)] = sha(path)
        bindings['reference_compile_sources'][str(saved)] = sha(saved)
        result[name] = sha(saved)
    if not result:
        raise ValueError('No pinned reference source')
    return target, result


def build_gear(args, out, report, bindings, compiler):
    checkout, source = pinned_snapshot(args.gear_source.resolve(), out, bindings)
    cpp, c = reference.compile_sources(checkout, source)
    cpp.append(ROOT/'tests/geargrafx_mapper_probe.cpp')
    deps = checkout/'platforms/shared/dependencies'
    flags = ['-O2', '-ffp-contract=off', '-ffunction-sections', '-fdata-sections',
             '-DGG_DISABLE_DISASSEMBLER', '-DGG_DISABLE_VGMRECORDER', '-DGG_DISABLE_MMI_THREADS']
    for include in (checkout/'src', ROOT/'tests', deps/'miniz', deps/'libchdr/include', deps/'minivorbis', deps/'json'):
        flags += ['-I', str(include)]
    objects = out/'objects'
    objects.mkdir()
    jobs = []
    for index, path in enumerate(cpp+c):
        obj = objects/(str(index)+'-'+path.stem+'.o')
        command = [str(compiler), *flags, '-x', 'c++' if path.suffix == '.cpp' else 'c',
                   *(['-std=c++20', '-include', 'cerrno'] if path.suffix == '.cpp' else ['-std=c11']),
                   '-c', str(path), '-o', str(obj)]
        jobs.append((command, obj))
        report['commands'].append(command)
    def compile_one(job):
        command, obj = job
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        obj.with_suffix('.log').write_text(result.stdout+result.stderr)
        result.check_returncode()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(compile_one, jobs))
    libraries = [path.resolve() for path in args.library]
    if not libraries or any(not p.is_file() for p in libraries):
        raise ValueError('Supply existing external static libraries explicitly')
    bindings['external_libraries'] = {str(path):sha(path) for path in libraries}
    binary = out/'gear-mapper.exe'
    common.evidence([str(compiler), *[str(obj) for _, obj in jobs], *map(str, libraries),
                     '-Wl,--gc-sections', '-o', str(binary)], 'gear-link', out, report, bindings)
    bindings['gear_objects'] = {str(obj):sha(obj) for _, obj in jobs}
    bindings['gear_binary'] = {str(binary):sha(binary)}
    return binary


def build_tool(args, out, report, bindings, compiler, tool, module=None):
    label = 'native' if module else 'interpreted'
    cmake, ninja = (Path(shutil.which(str(value)) or '').resolve() for value in (args.cmake, args.ninja))
    if not cmake.is_file() or not ninja.is_file():
        raise ValueError('Require CMake and Ninja')
    bindings['tools'].update({str(p):sha(p) for p in (cmake, ninja)})
    quote = cmake_quote
    wrapper = out/(label+'-wrapper')
    wrapper.mkdir()
    lines = ['cmake_minimum_required(VERSION 3.20)', 'project(AuthoredMappers LANGUAGES CXX)',
             *['set('+option+' OFF CACHE BOOL "" FORCE)' for option in
               ('PCE_BUILD_TOOLS','PCE_BUILD_TESTS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE','BUILD_TESTING')],
             f'add_subdirectory({quote(tool)} tool)']
    source = ROOT/'tests/mapper_oracle_probe.cpp'
    if module:
        lines += [f'pce_add_native_module(_module MODULE {quote(module/"module.cpp")} MANIFEST {quote(module/"module.json")})',
                  f'add_executable(mapper-probe {quote(source)})',
                  'target_compile_definitions(mapper-probe PRIVATE PCE_HUCARD_NATIVE_ONLY=1)',
                  'target_link_libraries(mapper-probe PRIVATE ${_module} pce-runtime)']
    else:
        lines += [f'add_executable(mapper-probe {quote(source)} {quote(tool/"runtime/src/no_module.cpp")})',
                  'target_link_libraries(mapper-probe PRIVATE pce-runtime)']
    file = wrapper/'CMakeLists.txt'
    file.write_text('\n'.join(lines)+'\n')
    bindings.setdefault('tool_build_inputs', {})[str(file)] = sha(file)
    build = out/(label+'-build')
    common.evidence([str(cmake), '-S', str(wrapper), '-B', str(build), '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
                     '-DCMAKE_CXX_COMPILER='+str(compiler), '-DCMAKE_MAKE_PROGRAM='+str(ninja)], label+'-configure', out, report, bindings)
    common.evidence([str(cmake), '--build', str(build), '--target', 'mapper-probe', '--parallel', '4'], label+'-build', out, report, bindings, 600)
    binary = build/('mapper-probe.exe' if os.name == 'nt' else 'mapper-probe')
    bindings.setdefault('tool_build_artifacts', {}).update({str(p):sha(p) for p in build.rglob('*')
        if p.is_file() and (p.suffix in ('.obj','.o','.a') or p.name in
                           ('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))})
    bindings.setdefault('tool_binaries', {})[str(binary)] = sha(binary)
    return binary


def execute(label, binary, plan, rom, profile, cases, out, report, bindings, native=None):
    command = [str(binary), str(plan), str(rom), profile]
    capture, execution = out/(label+'-capture.json'), out/(label+'-execution.json')
    if native is not None:
        command += ['--capture', str(capture), '--execution-report', str(execution)]
        if native:
            command += ['--guard-checks', 'on']
    result = common.evidence(command, label, out, report, bindings)
    records = common.validate_records(json.loads(result.stdout), cases)
    if native is None:
        return records, None, None
    bindings['raw_outputs'].update({str(p):sha(p) for p in (capture,execution)})
    work = common.validate_execution(json.loads(execution.read_text()), cases, native)
    captured = common.validate_capture(json.loads(capture.read_text()), work, native)
    return records, captured, work


def run(args):
    compiler = Path(shutil.which(str(args.compiler)) or '').resolve()
    tool, out = args.tool_source.resolve(), args.out.resolve()
    if args.native:
        # Select the pinned package before common execution validators import
        # pcerecomp. A later sys.path change cannot replace an imported package.
        sys.path.insert(0,str(tool))
        from pcerecomp import project
        if Path(project.__file__).resolve() != tool/'pcerecomp/project.py':
            raise ValueError('Compiler package was imported from a different toolkit')
    if out.exists() or not out.is_relative_to(ROOT/'.local') or not compiler.is_file():
        raise ValueError('Require compiler and NEW private .local output directory')
    sources = [Path(__file__), ROOT/'tests/geargrafx_mapper_probe.cpp', ROOT/'tests/mapper_oracle_probe.cpp',
               ROOT/'tests/reset_probe_support.hpp', ROOT/'scripts/hucard_reference.py', ROOT/'tests/hucard_fixture.py',
               ROOT/'scripts/filtered_audio_reference.py', ROOT/'scripts/psg_reference.py', ROOT/'tests/test_mapper_reference.py']
    if args.native:
        sources += sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))
        sources += sorted((tool/'pcerecomp').glob('*.py'))+[tool/'CMakeLists.txt',tool/'cmake/PCEConsumer.cmake']
    bindings = dict(tools={str(compiler):sha(compiler)}, authored_sources={str(p.resolve()):sha(p) for p in sources})
    report = dict(schema=1, result='incomplete', oracle_commit=COMMIT, commands=[], bindings=bindings,
                  scope='Authored exact SF2/Populous profiles; external configuration-only card RAM selection; low-speed guest CPU/source variants',
                  not_checked=['Retail software','Electrical mapper boards','Warm reset','Persistence','Host audio','Physical CPU bus phases','CRC database detection'])
    out.mkdir(parents=True)
    try:
        gear = build_gear(args, out, report, bindings, compiler)
        probe = build_tool(args, out, report, bindings, compiler, tool) if args.native else args.probe.resolve() if args.probe else None
        results, captures, fixtures = [], [], []
        bindings['authored_fixtures'] = {}
        for profile in ('sf2','populous'):
            image, cases = authored_rom(profile), plans(profile)
            rom, plan = out/(profile+'.pce'), out/(profile+'.plan')
            rom.write_bytes(image);plan.write_text(serialize(cases))
            bindings['authored_fixtures'].update({str(p):sha(p) for p in (rom,plan)})
            oracle = execute('gear-'+profile, gear, plan, rom, profile, cases, out, report, bindings)
            literal = {'gear':expected_memory(oracle[0], cases, profile, image)}
            observed = None
            if probe:
                observed = execute('interpreted-'+profile, probe, plan, rom, profile, cases, out, report, bindings, False)
                if common.compare(observed[0], oracle[0], cases):
                    raise ValueError('Mapper independent comparison differs: '+str(common.compare(observed[0], oracle[0], cases)))
                literal['interpreter'] = expected_memory(observed[0], cases, profile, image)
                captures.append(observed[1])
            results.append(dict(profile=profile,cases=len(cases),observations=len(oracle[0]),literal_checks=literal))
            fixtures.append((profile,rom,plan,cases,oracle,observed))
        report['profiles'] = results
        if args.native:
            sys.path.insert(0,str(tool))
            from pcerecomp.emitter import emit_capture
            from pcerecomp.capture import load_capture
            from pcerecomp.project import source_identity
            union = common.compose_captures(captures)
            capture = out/'actual-union.json';capture.write_text(json.dumps(union,indent=2)+'\n')
            bindings['authored_fixtures'][str(capture)] = sha(capture)
            captured, digest = load_capture(capture)
            module = out/'native-module'
            manifest = emit_capture(captured,module,digest)
            if manifest['native_instructions_emitted'] != len(union['observations']) or manifest['unsupported_observations'] or manifest['excluded_observations']:
                raise ValueError('Every actual mapper identity must translate')
            bindings['generated_module'] = {str(p):sha(p) for p in module.iterdir() if p.is_file()}
            native = build_tool(args,out,report,bindings,compiler,tool,module)
            retired = guards = mutations = 0
            for profile,rom,plan,cases,oracle,interpreted in fixtures:
                observed = execute('native-'+profile,native,plan,rom,profile,cases,out,report,bindings,True)
                if observed[0] != oracle[0] or observed[0] != interpreted[0]:
                    raise ValueError('Native mapper records differ from Gear/interpreter')
                if {common.capture_identity(o):o['native_hits'] for o in observed[1]['observations']} != \
                   {common.capture_identity(o):o['interpreted_hits'] for o in interpreted[1]['observations']}:
                    raise ValueError('Native mapper capture identities/hits differ')
                expected_memory(observed[0],cases,profile,authored_rom(profile))
                retired += observed[2]['native_steps'];guards += observed[2]['guard_checks'];mutations += observed[2]['restored_source_mutations']
            report['native'] = dict(native_steps=retired,interpreter_steps=0,guard_checks=guards,
                restored_source_mutations=mutations,identities=len(union['observations']),
                mpr_contexts=len({tuple(o['mpr']) for o in union['observations']}),source_variants='SF2 same PC/MPR/physical addresses execute four observed byte variants')
            report['tool'] = source_identity(tool)
        report.update(result='pass',observations=sum(r['observations'] for r in results),cases=sum(r['cases'] for r in results))
    except Exception as error:
        report.update(result='fail',error=str(error));raise
    finally:
        reference.record_preservation(report,bindings)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['result']!='pass':
        raise ValueError('Mapper reference binding changed')
    print(json.dumps({k:v for k,v in report.items() if k not in ('bindings','commands')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True)
    parser.add_argument('--tool-source',type=Path,default=ROOT)
    parser.add_argument('--probe',type=Path)
    parser.add_argument('--native',action='store_true')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--compiler',default='clang++')
    parser.add_argument('--cmake',default='cmake')
    parser.add_argument('--ninja',default='ninja')
    parser.add_argument('--library',type=Path,action='append',default=[])
    try:run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:
        print(error,file=sys.stderr);raise SystemExit(1)
