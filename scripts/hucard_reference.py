"""Finite authored HuCard reset/map checks against unchanged Geargrafx.

Gear receives decoded authored images. Header/bit-reversal policy is not
claimed to be independently implemented by Gear. Native mode captures actual
retirements, emits operations, compiles a separate module and reruns without
interpreter fallback. All fixture data is authored, never a disc/firmware dump.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests'))
from hucard_fixture import (BANK_COUNTS, CPU_FIELDS, DEVICE_FIELDS, authored_rom,
                            independent_expectations, plans, serialize)
from scripts import filtered_audio_reference as reference
sha = reference.sha


def validate_records(records, cases):
    tags = []
    for case in cases:
        for operation in case['operations']:
            op = operation[0]
            if op == 'i':
                tags.extend([('cpu', len(CPU_FIELDS))]*operation[1])
            elif op in ('s', 'd', 'q', 'p'):
                tags.append(({'s': 'cpu', 'd': 'devices', 'q': 'memory', 'p': 'peek'}[op],
                             len(CPU_FIELDS) if op == 's' else len(DEVICE_FIELDS) if op == 'd' else 3))
    if not isinstance(records, list) or len(records) != len(tags):
        raise ValueError('HuCard observation count differs from authored plan')
    for record, (kind, width) in zip(records, tags):
        if (not isinstance(record, dict) or set(record) != {'kind', 'values'} or record['kind'] != kind
                or not isinstance(record['values'], list) or len(record['values']) != width
                or any(type(value) is not int or not 0 <= value < 2**64 for value in record['values'])):
            raise ValueError('Malformed HuCard observation')
    return records


def compare(actual, expected, cases):
    validate_records(actual, cases)
    validate_records(expected, cases)
    for index, (left, right) in enumerate(zip(actual, expected)):
        if left != right:
            fields = CPU_FIELDS if left['kind'] == 'cpu' else DEVICE_FIELDS if left['kind'] == 'devices' else ('bank', 'offset', 'byte')
            for field, value, wanted in zip(fields, left['values'], right['values']):
                if value != wanted:
                    return dict(observation=index, kind=left['kind'], field=field, actual=value, expected=wanted)
    return None


def capture_identity(item):
    return item['pc'], tuple(item['mpr']), tuple(item['physical']), tuple(item['data'])


def validate_execution(execution, cases, native):
    from pcerecomp.project import ABI
    fields = {'runtime_abi', 'native_only', 'interpreter_fallback', 'cases', 'native_steps',
              'interpreter_steps', 'guard_checks', 'restored_source_mutations', 'per_case'}
    counts = [sum(op[1] for op in case['operations'] if op[0] == 'i') for case in cases]
    expected = dict(runtime_abi=ABI, native_only=native, interpreter_fallback=False,
                    cases=len(cases), native_steps=sum(counts) if native else 0,
                    interpreter_steps=0 if native else sum(counts), guard_checks=3*len(cases) if native else 0,
                    restored_source_mutations=len(cases) if native else 0,
                    per_case=[[count, 0] if native else [0, count] for count in counts])
    if not isinstance(execution, dict) or set(execution) != fields or execution != expected:
        raise ValueError('Actual HuCard execution tiers/guards/case accounting differ')
    if any(type(execution[key]) is not int for key in fields-{'native_only', 'interpreter_fallback', 'per_case'}):
        raise ValueError('Actual HuCard execution counts must be integers')
    if type(execution['native_only']) is not bool or type(execution['interpreter_fallback']) is not bool:
        raise ValueError('Actual HuCard execution policy must be boolean')
    if any(type(value) is not int for pair in execution['per_case'] for value in pair):
        raise ValueError('Actual HuCard per-case counts must be integers')
    return execution


def validate_capture(capture, execution, native):
    from pcerecomp.capture import validate_capture as validate
    from pcerecomp.project import ABI
    validate(capture)
    if (capture['runtime_abi'] != ABI or not capture['complete'] or capture['dropped_instructions']
            or capture['unreadable_instructions'] or capture['retired_instructions'] != execution['native_steps']+execution['interpreter_steps']
            or sum(o['native_hits'] for o in capture['observations']) != execution['native_steps']
            or sum(o['interpreted_hits'] for o in capture['observations']) != execution['interpreter_steps']
            or any(o['interpreted_hits'] if native else o['native_hits'] for o in capture['observations'])):
        raise ValueError('Actual HuCard capture identity/tier accounting differs')
    return capture


def compose_captures(captures):
    from pcerecomp.capture import validate_capture as validate
    union = {}
    for capture in captures:
        validate(capture)
        if not capture['complete'] or capture['dropped_instructions'] or capture['unreadable_instructions']:
            raise ValueError('Cannot compose incomplete authored capture')
        for item in capture['observations']:
            key = capture_identity(item)
            if key not in union:
                union[key] = copy.deepcopy(item)
            else:
                union[key]['native_hits'] += item['native_hits']
                union[key]['interpreted_hits'] += item['interpreted_hits']
    if not captures or len({c['runtime_abi'] for c in captures}) != 1:
        raise ValueError('Require same-ABI actual authored captures')
    capture = dict(schema=1, runtime_abi=captures[0]['runtime_abi'], capacity=65536,
                   complete=True, dropped_instructions=0, unreadable_instructions=0,
                   retired_instructions=sum(c['retired_instructions'] for c in captures),
                   observations=[union[key] for key in sorted(union)])
    validate(capture)
    return capture


def evidence(command, label, out, report, bindings, timeout=180):
    report['commands'].append(list(map(str, command)))
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    for suffix, value in (('stdout', result.stdout), ('stderr', result.stderr)):
        file = out/(label+'.'+suffix)
        file.write_text(value, encoding='utf-8', newline='\n')
        bindings.setdefault('raw_outputs', {})[str(file)] = sha(file)
    report.setdefault('processes', []).append(dict(label=label, returncode=result.returncode))
    result.check_returncode()
    return result


def build_gear(args, out, report, bindings, compiler):
    checkout = args.gear_source.resolve()
    source = reference.source_binding(checkout)
    bindings['reference_sources'] = {str(checkout/name): digest for name, digest in source.items()}
    cpp, c = reference.compile_sources(checkout, source)
    cpp.append(ROOT/'tests/geargrafx_hucard_probe.cpp')
    deps = checkout/'platforms/shared/dependencies'
    common = ['-O2', '-ffp-contract=off', '-ffunction-sections', '-fdata-sections',
              '-DGG_DISABLE_DISASSEMBLER', '-DGG_DISABLE_VGMRECORDER', '-DGG_DISABLE_MMI_THREADS']
    for include in (checkout/'src', ROOT/'tests', deps/'miniz', deps/'libchdr/include', deps/'minivorbis', deps/'json'):
        common += ['-I', str(include)]
    objects = out/'objects'
    objects.mkdir()
    jobs = []
    for index, path in enumerate(cpp+c):
        target = objects/(f'{index:02}-'+path.stem+'.o')
        command = [str(compiler), *common, '-x', 'c++' if path.suffix == '.cpp' else 'c',
                   *(['-std=c++20', '-include', 'cerrno'] if path.suffix == '.cpp' else ['-std=c11']),
                   '-c', str(path), '-o', str(target)]
        jobs.append((command, target))
        report['commands'].append(command)

    def compile_one(job):
        command, target = job
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        target.with_suffix('.log').write_text(result.stdout+result.stderr, encoding='utf-8')
        result.check_returncode()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(compile_one, jobs))
    libraries = [p.resolve() for p in args.library]
    if not libraries or any(not path.is_file() for path in libraries):
        raise ValueError('Supply existing external static --library inputs explicitly')
    bindings['external_libraries'] = {str(path): sha(path) for path in libraries}
    binary = out/('gear-hucard.exe' if os.name == 'nt' else 'gear-hucard')
    evidence([str(compiler), *[str(target) for _, target in jobs], *map(str, libraries),
              '-Wl,--gc-sections', '-o', str(binary)], 'gear-link', out, report, bindings)
    bindings['gear_objects'] = {str(path): sha(path) for _, path in jobs}
    bindings['gear_binary'] = {str(binary): sha(binary)}
    return binary


def build_tool(args, out, report, bindings, compiler, tool, native=False, module=None):
    label = 'native' if native else 'interpreted'
    cmake = Path(shutil.which(str(args.cmake)) or '').resolve()
    ninja = Path(shutil.which(str(args.ninja)) or '').resolve()
    if not cmake.is_file() or not ninja.is_file():
        raise ValueError('Require actual CMake and Ninja for native qualification')
    bindings['tools'].update({str(cmake): sha(cmake), str(ninja): sha(ninja)})
    wrapper = out/(label+'-wrapper')
    wrapper.mkdir()

    def quoted(path):
        value = Path(path).resolve().as_posix()
        if any(c in value for c in ('"', ';', '$', '\n', '\r')):
            raise ValueError('CMake path cannot be represented')
        return '"'+value+'"'

    source = ROOT/'tests/hucard_oracle_probe.cpp'
    lines = ['cmake_minimum_required(VERSION 3.20)', 'project(AuthoredHuCard LANGUAGES CXX)',
             'set(PCE_BUILD_TOOLS OFF CACHE BOOL "" FORCE)', 'set(PCE_BUILD_TESTS OFF CACHE BOOL "" FORCE)',
             'set(PCE_BUILD_DESKTOP OFF CACHE BOOL "" FORCE)', 'set(PCE_BUILD_REFERENCE_PROBE OFF CACHE BOOL "" FORCE)',
             'set(BUILD_TESTING OFF CACHE BOOL "" FORCE)', f'add_subdirectory({quoted(tool)} tool)']
    if native:
        lines += [f'pce_add_native_module(_module MODULE {quoted(module/"module.cpp")} MANIFEST {quoted(module/"module.json")})',
                  f'add_executable(hucard-probe {quoted(source)})',
                  'target_compile_definitions(hucard-probe PRIVATE PCE_HUCARD_NATIVE_ONLY=1)',
                  'target_link_libraries(hucard-probe PRIVATE ${_module} pce-runtime)']
    else:
        lines += [f'add_executable(hucard-probe {quoted(source)} {quoted(tool/"runtime/src/no_module.cpp")})',
                  'target_link_libraries(hucard-probe PRIVATE pce-runtime)']
    file = wrapper/'CMakeLists.txt'
    file.write_text('\n'.join(lines)+'\n', encoding='utf-8', newline='\n')
    bindings.setdefault('tool_build_inputs', {})[str(file)] = sha(file)
    build = out/(label+'-build')
    evidence([str(cmake), '-S', str(wrapper), '-B', str(build), '-G', 'Ninja',
              '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_COMPILER='+str(compiler),
              '-DCMAKE_MAKE_PROGRAM='+str(ninja)], label+'-configure', out, report, bindings, 90)
    evidence([str(cmake), '--build', str(build), '--target', 'hucard-probe', '--parallel', '4'],
             label+'-build', out, report, bindings, 600)
    binary = build/('hucard-probe.exe' if os.name == 'nt' else 'hucard-probe')
    bindings.setdefault('tool_build_artifacts', {}).update({str(p): sha(p) for p in build.rglob('*')
        if p.is_file() and (p.suffix in ('.obj', '.o', '.a') or p.name in ('CMakeCache.txt', 'build.ninja', 'rules.ninja', '.ninja_log'))})
    bindings.setdefault('tool_binaries', {})[str(binary)] = sha(binary)
    return binary


def execute(label, binary, plan, rom, cases, out, report, bindings, native=None):
    command = [str(binary), str(plan), str(rom)]
    capture, execution = out/(label+'-capture.json'), out/(label+'-execution.json')
    if native is not None:
        command += ['--capture', str(capture), '--execution-report', str(execution)]
        if native:
            command += ['--guard-checks', 'on']
    result = evidence(command, label, out, report, bindings)
    file = out/(label+'.json')
    file.write_text(result.stdout, encoding='ascii', newline='\n')
    bindings['raw_outputs'][str(file)] = sha(file)
    records = validate_records(json.loads(result.stdout), cases)
    if native is None:
        return records, None, None
    bindings['raw_outputs'].update({str(p): sha(p) for p in (capture, execution)})
    work = validate_execution(json.loads(execution.read_text()), cases, native)
    captured = validate_capture(json.loads(capture.read_text()), work, native)
    return records, captured, work


def run(args):
    tool = (args.tool_source or ROOT).resolve()
    if args.native:
        sys.path.insert(0, str(tool))
    compiler = Path(shutil.which(str(args.compiler)) or '').resolve()
    out = args.out.resolve()
    if out.exists() or not compiler.is_file() or args.gear_only and (args.native or args.probe):
        raise ValueError('Require a new output, compiler and one coherent execution mode')
    if not args.gear_only and not args.native and (not args.probe or not args.probe.is_file()):
        raise ValueError('Provide --native or an actual --probe')
    out.mkdir(parents=True)
    sources = [Path(__file__).resolve(), ROOT/'tests/hucard_fixture.py', ROOT/'tests/geargrafx_hucard_probe.cpp',
               ROOT/'tests/hucard_oracle_probe.cpp', ROOT/'tests/reset_probe_support.hpp',
               ROOT/'scripts/filtered_audio_reference.py', ROOT/'scripts/psg_reference.py']
    if not args.gear_only:
        sources += sorted((tool/'runtime').rglob('*.cpp')) + sorted((tool/'runtime').rglob('*.hpp'))
    if args.native:
        sources += sorted((tool/'pcerecomp').glob('*.py')) + [tool/'CMakeLists.txt', tool/'cmake/PCEConsumer.cmake']
    bindings = dict(tools={str(compiler): sha(compiler)}, authored_sources={str(p): sha(p) for p in sources})
    report = dict(schema=1, result='incomplete', oracle_commit=reference.COMMIT, bindings=bindings, commands=[],
                  scope='Authored decoded base HuCard memory/reset/low-speed instruction fixtures; selected compatibility mapping, not physical-board/electrical conformance',
                  not_checked=['Retail software', 'Header/bit-reversal policy in Gear', 'Physical power-on values',
                               'Cartridge RAM/SF2/SuperGrafx', 'Warm reset', 'CPU bus-phase timing', 'Audio output'])
    archive = out/'authored'
    for path in sources:
        relative = Path('toolkit')/path.relative_to(tool) if path.is_relative_to(tool) else Path('adapter')/path.relative_to(ROOT)
        saved = archive/relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, saved)
        report.setdefault('source_epoch_mappings', []).append(dict(original=str(path), sha256=sha(path), preserved=str(saved)))
    try:
        gear = build_gear(args, out, report, bindings, compiler)
        probe = None if args.gear_only else build_tool(args, out, report, bindings, compiler, tool) if args.native else args.probe.resolve()
        if probe:
            bindings['tools'][str(probe)] = sha(probe)
        results, captures, fixtures = [], [], []
        bindings['authored_fixtures'] = {}
        for count in BANK_COUNTS:
            image = authored_rom(count)
            cases = plans(count)
            text, spans = serialize(cases)
            rom, plan = out/f'authored-{count}.pce', out/f'authored-{count}.plan'
            rom.write_bytes(image)
            plan.write_text(text, encoding='ascii')
            bindings['authored_fixtures'].update({str(p): sha(p) for p in (rom, plan)})
            oracle = execute(f'gear-{count}', gear, plan, rom, cases, out, report, bindings)
            expected_checks = {'gear': independent_expectations(oracle[0], cases, count, image)}
            item = dict(banks=count, cases=len(cases), observations=len(oracle[0]), independent_expected_checks=expected_checks)
            observed = None
            if probe:
                observed = execute(f'interpreted-{count}', probe, plan, rom, cases, out, report, bindings, False)
                mismatch = compare(observed[0], oracle[0], cases)
                expected_checks['interpreter'] = independent_expectations(observed[0], cases, count, image)
                if mismatch:
                    raise ValueError('Independent HuCard comparison failed: '+str(dict(banks=count, **mismatch)))
                captures.append(observed[1])
            results.append(item)
            fixtures.append((count, rom, plan, cases, oracle, observed))
        report['images'] = results
        if args.native:
            from pcerecomp.emitter import emit_capture
            from pcerecomp.capture import load_capture
            from pcerecomp.project import source_identity
            union = compose_captures(captures)
            capture = out/'authored-capture-union.json'
            capture.write_text(json.dumps(union, indent=2)+'\n')
            bindings['authored_fixtures'][str(capture)] = sha(capture)
            captured, digest = load_capture(capture)
            module = out/'native-module'
            manifest = emit_capture(captured, module, capture_sha256=digest)
            if manifest['unsupported_observations'] or manifest['excluded_observations'] or manifest['native_instructions_emitted'] != len(union['observations']):
                raise ValueError('Every actual authored HuCard identity must be translated')
            for file in module.glob('*.cpp'):
                if 'interpret_step' in file.read_text() or 'execute_one' in file.read_text():
                    raise ValueError('Generated module contains an interpreter bridge')
            bindings['generated_module'] = {str(p): sha(p) for p in module.iterdir() if p.is_file()}
            native_probe = build_tool(args, out, report, bindings, compiler, tool, True, module)
            total_native = total_guards = total_mutations = 0
            for count, rom, plan, cases, oracle, interpreted in fixtures:
                actual = execute(f'native-{count}', native_probe, plan, rom, cases, out, report, bindings, True)
                if actual[0] != interpreted[0] or compare(actual[0], oracle[0], cases):
                    raise ValueError('Native raw HuCard records differ from interpreted/Gear')
                before = {capture_identity(o): o['interpreted_hits'] for o in interpreted[1]['observations']}
                after = {capture_identity(o): o['native_hits'] for o in actual[1]['observations']}
                if before != after:
                    raise ValueError('Native capture identities/hits differ from actual training')
                independent_expectations(actual[0], cases, count, authored_rom(count))
                total_native += actual[2]['native_steps']
                total_guards += actual[2]['guard_checks']
                total_mutations += actual[2]['restored_source_mutations']
            report['native'] = dict(native_steps=total_native, interpreter_steps=0, guard_checks=total_guards,
                                    restored_source_mutations=total_mutations, observed_identities=len(union['observations']),
                                    mpr_contexts=len({tuple(o['mpr']) for o in union['observations']}),
                                    raw_native_interpreted_gear_equal=True, module=manifest,
                                    capture_union_scope='Exact union of eight separate complete authored runs; not a single-run capture')
            report['tool'] = source_identity(tool)
        report.update(result='pass', image_count=len(results), cases=sum(r['cases'] for r in results),
                      observations=sum(r['observations'] for r in results))
    except Exception as error:
        report.update(result='fail', error=str(error))
        raise
    finally:
        reference.record_preservation(report, bindings)
        (out/'result.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    if report['result'] != 'pass':
        raise ValueError('HuCard reference input bindings changed')
    print(json.dumps({k: v for k, v in report.items() if k not in ('bindings', 'commands', 'source_epoch_mappings', 'images')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source', type=Path, required=True)
    parser.add_argument('--probe', type=Path)
    parser.add_argument('--tool-source', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--compiler', default='clang++')
    parser.add_argument('--cmake', default='cmake')
    parser.add_argument('--ninja', default='ninja')
    parser.add_argument('--library', type=Path, action='append', default=[])
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--gear-only', action='store_true', help='External authored preflight without toolkit/native qualification')
    try:
        run(parser.parse_args())
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
