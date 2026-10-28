"""Execute fresh stable-layout translations against original Gear TAM traces.

The bootstrap is a real interpreted run of authored firmware. Only its actual
capture supplies stable translations. Original Gear and independent literals
check all instruction states at both CPU speeds; no retail inputs are needed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from scripts import context_reference as base
from scripts import filtered_audio_reference as reference
from scripts import hucard_reference as common
from generate_context_fixture import generate, firmware, expected_rows, STEPS

sha = reference.sha


def source_key(item):
    return item['pc'], tuple(item['mpr']), tuple(item['physical']), tuple(item['data'])


def expected_sources():
    """Authored byte lengths and pre-instruction mappings, independent of decoder."""
    raw = firmware(spread=True)
    lengths = {0x78:1, 0xA9:2, 0x53:2, 0xA2:2, 0xAD:3, 0x8D:3,
               0xCA:1, 0xD0:2, 0x4C:3, 0x80:2}
    result = {}
    for divisor in (3, 12):
        pc, mpr = 0xE000, (0,)*8
        for row in expected_rows(divisor, spread=True):
            address = (mpr[pc>>13]<<13)|(pc&8191)
            length = lengths[raw[address]]
            physical = tuple((mpr[((pc+i)&65535)>>13]<<13)|((pc+i)&8191)
                             for i in range(length))
            data = tuple(raw[p] for p in physical)
            key = pc, mpr, physical, data
            result[key] = result.get(key, 0)+1
            pc, mpr = row[0], tuple(row[8:16])
    return result


def records(raw):
    value = json.loads(raw)
    expected = [dict(kind='cpu', values=row) for divisor in (3, 12)
                for row in expected_rows(divisor, spread=True)]
    if type(value) is not list or len(value) != 2*STEPS:
        raise ValueError('Stable context trace extent differs')
    for index, (row, literal) in enumerate(zip(value, expected)):
        if (type(row) is not dict or set(row) != {'kind', 'values'} or
                row['kind'] != 'cpu' or type(row['values']) is not list or
                len(row['values']) != 20 or any(type(v) is not int for v in row['values'])):
            raise ValueError('Stable context trace shape differs')
        if row != literal:
            raise ValueError(f'Independent spread-context literal differs at row {index}')
    return value


def capture_work(capture, native):
    from pcerecomp.capture import validate_capture
    from pcerecomp.project import ABI
    validate_capture(capture)
    if (capture['runtime_abi'] != ABI or not capture['complete'] or
            capture['dropped_instructions'] or capture['unreadable_instructions'] or
            capture['retired_instructions'] != 2*STEPS):
        raise ValueError('Stable context capture must be complete current-ABI actual work')
    selected = 'native_hits' if native else 'interpreted_hits'
    other = 'interpreted_hits' if native else 'native_hits'
    if (any(row[other] for row in capture['observations']) or
            {source_key(row):row[selected] for row in capture['observations']} != expected_sources()):
        raise ValueError('Stable context full identity or per-source execution hits differ')
    return dict(native=2*STEPS if native else 0, interpreted=0 if native else 2*STEPS,
                source_identities=len(capture['observations']))


def qualify(gear_raw, bootstrap_raw, native_raw, bootstrap_capture, native_capture, manifest,
            bootstrap_capture_sha256):
    from pcerecomp.project import ABI
    golden = records(gear_raw)
    if records(bootstrap_raw) != golden or records(native_raw) != golden:
        raise ValueError('Stable native/interpreter/original Gear records differ')
    bootstrap = capture_work(bootstrap_capture, False)
    native = capture_work(native_capture, True)
    keys = expected_sources()
    parts = {f'module_m{sum(v<<(8*i) for i,v in enumerate(mpr)):016x}_p{pc&0xFF00:04x}.cpp'
             for pc,mpr,_,_ in keys}
    units = manifest.get('translation_units')
    if (type(units) is not list or any(type(row) is not dict or set(row) != {'file','sha256'} or
            type(row['file']) is not str or type(row['sha256']) is not str or
            len(row['sha256']) != 64 or any(v not in '0123456789abcdef' for v in row['sha256'])
            for row in units) or len({row['file'] for row in units}) != len(units)):
        raise ValueError('Stable manifest translation unit identities are malformed or duplicated')
    if (type(bootstrap_capture_sha256) is not str or len(bootstrap_capture_sha256) != 64 or
            any(v not in '0123456789abcdef' for v in bootstrap_capture_sha256) or
            manifest.get('code_capture_sha256') != bootstrap_capture_sha256 or
            type(manifest.get('runtime_abi')) is not int or manifest['runtime_abi'] != ABI or
            manifest.get('capture_runtime_abi') != ABI or
            manifest.get('partition_layout') != 'stable' or type(manifest.get('pc_bucket_size')) is not int or
            manifest['pc_bucket_size'] != 256 or
            manifest.get('partition_identity') != 'full_mpr_logical_pc_range_v1' or
            manifest.get('unsupported_observations') != 0 or
            manifest.get('excluded_observations') != 0 or
            manifest.get('native_instructions_emitted') != len(keys) or
            {row['file'] for row in units} != {'module.cpp', *parts}):
        raise ValueError('Stable manifest does not describe exactly the executed source buckets')
    return dict(records=len(golden), literal_checks=20*len(golden)*3,
                bootstrap=bootstrap, native=native, executed_parts=len(parts),
                logical_pc_buckets=len({pc>>8 for pc,_,_,_ in keys}),
                full_mpr_contexts=len({mpr for _,mpr,_,_ in keys}))


def run(args):
    tool, out = args.tool_source.resolve(), args.out.resolve()
    compiler = Path(shutil.which(str(args.compiler)) or '').resolve()
    if out.exists() or not out.is_relative_to(ROOT/'.local') or not compiler.is_file():
        raise ValueError('NEW private output and existing compiler required')
    sys.path.insert(0, str(tool))
    from pcerecomp import project
    from pcerecomp.capture import load_capture
    from pcerecomp.emitter import emit_capture
    if Path(project.__file__).resolve() != tool/'pcerecomp/project.py':
        raise ValueError('Selected source import required')
    source = [Path(__file__), ROOT/'scripts/context_reference.py',
              ROOT/'tests/generate_context_fixture.py', ROOT/'tests/context_tests.cpp',
              ROOT/'tests/geargrafx_context_probe.cpp', ROOT/'tests/geargrafx_mapper_probe.cpp',
              ROOT/'tests/reset_probe_support.hpp', *[ROOT/'scripts'/p for p in
              ('mapper_reference.py','hucard_reference.py','filtered_audio_reference.py')]]
    source += (sorted((tool/'pcerecomp').glob('*.py')) + sorted((tool/'runtime').rglob('*.cpp')) +
               sorted((tool/'runtime').rglob('*.hpp')) + [tool/'CMakeLists.txt',tool/'cmake/PCEConsumer.cmake'])
    bindings = dict(tools={str(compiler):sha(compiler)},
                    authored_sources={str(p.resolve()):sha(p) for p in source})
    report = dict(schema=1, result='incomplete', commands=[], bindings=bindings,
                  oracle_commit=reference.COMMIT,
                  scope='Authored multi-page/multi-MPR actual interpreted bootstrap, stable captured translation, original separate Gear and independent per-instruction literals. No retail, hardware timing or changed-object reuse claim.')
    out.mkdir(parents=True)
    epoch = out/'authored-inputs'; epoch.mkdir(); bindings['authored_epoch'] = {}
    for index,path in enumerate(source):
        saved = epoch/str(index)/path.name; saved.parent.mkdir(); shutil.copyfile(path,saved)
        bindings['authored_epoch'][str(saved)] = sha(saved)
    try:
        fixture = out/'fixture'; generate(fixture, spread=True)
        bindings['fixture'] = {str(p):sha(p) for p in fixture.iterdir() if p.is_file()}
        rom = fixture/'authored.pce'
        gear = base.build_gear(args,out,report,bindings,compiler)
        golden = common.evidence([str(gear),str(rom)],'gear',out,report,bindings)
        records(golden.stdout)
        bootstrap_out = out/'bootstrap'; bootstrap_out.mkdir()
        bootstrap_binary = base.build_tool(args,bootstrap_out,report,bindings,compiler,fixture)
        bindings['bootstrap_binary'] = {str(bootstrap_binary):sha(bootstrap_binary)}
        bootstrap_capture_path = out/'bootstrap-capture.json'
        bootstrap = common.evidence([str(bootstrap_binary),'--probe',str(rom),'interpreted',str(bootstrap_capture_path)],'bootstrap',out,report,bindings)
        discovery, digest = load_capture(bootstrap_capture_path)
        bindings['raw_outputs'][str(bootstrap_capture_path)] = digest
        capture_work(discovery, False); records(bootstrap.stdout)
        stable = out/'stable-module'
        manifest = emit_capture(discovery,stable,digest,partition_layout='stable')
        for filename in ('authored.pce','context_fixture.hpp'):
            shutil.copyfile(fixture/filename,stable/filename)
        bindings['stable_module'] = {str(p):sha(p) for p in stable.iterdir() if p.is_file()}
        native_out = out/'native'; native_out.mkdir()
        native_binary = base.build_tool(args,native_out,report,bindings,compiler,stable)
        native_capture_path = out/'native-capture.json'
        native = common.evidence([str(native_binary),'--probe',str(rom),'native',str(native_capture_path)],'native',out,report,bindings)
        observed, native_digest = load_capture(native_capture_path)
        bindings['raw_outputs'][str(native_capture_path)] = native_digest
        qualification = qualify(golden.stdout,bootstrap.stdout,native.stdout,discovery,observed,manifest,digest)
        expected_guards = sum((2+len(key[3]))*hits for key,hits in expected_sources().items())
        for result, native_mode in ((bootstrap,False),(native,True)):
            tokens = result.stderr.strip().split()
            expected = ['CONTEXT_WORK',str(2*STEPS if native_mode else 0),
                        str(0 if native_mode else 2*STEPS),str(expected_guards if native_mode else 0),str(40*STEPS)]
            if tokens != expected:
                raise ValueError('Actual stable context execution/guard counts differ')
        # Store literal admission inputs so an independent later audit can
        # rerun the checker without changing captures or relying on claims.
        admission = out/'admission.json'
        admission.write_text(json.dumps(dict(gear_raw=golden.stdout,bootstrap_raw=bootstrap.stdout,
            native_raw=native.stdout,bootstrap_capture=discovery,native_capture=observed,manifest=manifest,
            bootstrap_capture_sha256=digest),indent=2)+'\n')
        bindings['qualification_inputs'] = {str(admission):sha(admission)}
        report.update(result='pass',tool=project.source_identity(tool),qualification=qualification,
                      pure_native_guards=expected_guards,bootstrap_binary=str(bootstrap_binary),
                      stable_binary=str(native_binary),stable_manifest_sha256=sha(stable/'module.json'),
                      capture_sha256=digest,admission=str(admission))
    except Exception as error:
        report.update(result='fail',error=str(error)); raise
    finally:
        reference.record_preservation(report,bindings)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['result'] != 'pass':
        raise ValueError('Stable reference evidence preservation failed')
    print(json.dumps({k:v for k,v in report.items() if k not in ('commands','bindings')},indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True)
    parser.add_argument('--tool-source',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--compiler',default='clang++');parser.add_argument('--cmake',default='cmake')
    parser.add_argument('--ninja',default='ninja');parser.add_argument('--library',type=Path,action='append',default=[])
    try: run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:
        print(error,file=sys.stderr);raise SystemExit(1)
