"""Qualify authored toolkit bus observers against retained original-core runs.

No reference rebuild, retail data, timing projection or call regrouping occurs.
Failures and actual software callback differences retain their original files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from pcerecomp import bus_trace
from pcerecomp.isa import _LENGTH, _ROWS
from pcerecomp.project import source_identity
from pcerecomp.snapshots import SnapshotStore
from scripts.bus_event_reference import binding, verify_bindings
from bus_reference_fixture import expected_accesses, fixture


def require(condition, message):
    if not condition:
        raise ValueError(message)


def invoke(command, out, name, commands):
    commands.append(command)
    result = subprocess.run(command, capture_output=True, timeout=30, check=False)
    stdout, stderr = out/(name+'.stdout'), out/(name+'.stderr')
    stdout.write_bytes(result.stdout)
    stderr.write_bytes(result.stderr)
    require(result.returncode == 0, 'Compiled qualification process failed: '+name)
    return dict(stdout=binding(stdout), stderr=binding(stderr)), result.stdout


def validate_literal_accesses(trace, profile):
    rows = [{field:event[field] for field in ('direction','logical','value','mpr','physical')}
            for event in trace.events]
    require(rows == expected_accesses(profile), 'Actual access chronology differs from authored literals')
    return len(rows)


def validate_sources(trace, description, *, allow_continuations=False):
    instructions = {row['pc']:row for row in description['instructions']}
    # The authored measured source is ROM. Every original continuation candidate
    # must still identify a real independently supplied entry extent, not a
    # guessed retired operation. ROM wrapping/mapping is checked by its producer.
    checked = 0
    for call in trace.calls:
        row = call['entry']
        instruction = instructions.get(row['entry']['pc'])
        require(instruction is not None, 'Actual entry PC outside authored measured source')
        require(row['source'] == bus_trace.source_identity(row['entry']['pc'], row['entry']['mpr'],
            bytes(instruction['data'])), 'Actual entry identity differs from authored encoded bytes')
        checked += 1
    require(allow_continuations or checked == description['steps'], 'Toolkit actual call extent differs')
    return checked


def run(args):
    out = args.out.resolve()
    require(not out.exists() and out.is_relative_to(ROOT/'.local'), 'New private output required')
    out.mkdir(parents=True)
    store = SnapshotStore()
    probe = args.probe.resolve(strict=True)
    probe_pin = store.bind(probe)
    reference_pin = store.read_json(args.references.resolve(strict=True), max_bytes=16*1024*1024)
    references = json.loads(reference_pin.raw)
    verify_bindings(references)
    require(references.get('result') == 'pass-original-observer-nonperturbation',
            'Passed independent original/disabled/observed receipt required')
    identity = source_identity(ROOT)
    require(identity['revision'] is not None, 'Exact toolkit revision required')
    commands = []
    report = dict(schema=1, result='incomplete', scope='Authored finite software callback observations; '
        'native/interpreter parity is internal evidence; original-core timing/call differences remain '
        'diagnostics, not electrical bus-cycle or retail-game qualification.',
        commands=commands, toolkit_identity=identity, binary=binding(probe),
        original_reference_receipt=binding(args.references.resolve()), runs={}, diagnostics={})
    for path in (Path(__file__), ROOT/'pcerecomp/bus_trace.py', ROOT/'tests/bus_trace_tests.cpp',
                 ROOT/'tests/bus_reference_fixture.py', ROOT/'tests/test_bus_trace_integration.py'):
        store.bind(path)
    try:
        # The C++ test includes an actual changed-byte native guard miss,
        # unchanged checkpoint control and observed zero-retirement callback set.
        report['native_guard_and_observer_controls'], _ = invoke([str(probe)], out, 'selftest', commands)
        identities_log, raw = invoke([str(probe), '--source-identities'], out, 'source-identities', commands)
        identities = [json.loads(line) for line in raw.splitlines()]
        require(len(identities) == 256, 'All encoded source extents required')
        for opcode, row in enumerate(identities):
            length = _LENGTH[_ROWS[opcode].split('.')[1]]
            expected = bus_trace.source_identity(0x2870,[248]*8,
                bytes((opcode,17,34,51,68,85,102))[:length])
            require(row == dict(opcode=opcode,pc=0x2870,length=length,sha256=expected['sha256']),
                    'Compiled source extent/digest differs from decoder')
        report['source_extent_controls'] = dict(log=identities_log, checked=256)
        for profile in ('low','high','block'):
            rom, description = fixture(profile)
            firmware = out/(profile+'.pce'); firmware.write_bytes(rom)
            traces = {}
            for tier in ('native','interpreter'):
                label = tier+'-'+profile
                target = out/(label+'.jsonl')
                base = [str(probe),'--probe',profile,tier,str(firmware),str(target),identity['revision'],
                        identity['source_sha256'],probe_pin.sha256,description['fixture_sha256']]
                logs, raw = invoke(base+['observed'],out,label+'-observed',commands)
                observed = json.loads(raw)
                disabled_logs, disabled_raw = invoke(base+['disabled'],out,label+'-disabled',commands)
                disabled = json.loads(disabled_raw)
                require(all(observed[field] == disabled[field] for field in
                    ('checkpoint_sha256','ticks','native','interpreted')), 'Observer changed full guest state')
                require(disabled['calls'] == disabled['events'] == 0, 'Disabled path emitted events')
                trace = bus_trace.load_trace(target)
                require(trace.header['engine'] == dict(name='toolkit-'+tier,revision=identity['revision'],
                    source_sha256=identity['source_sha256'],binary_sha256=probe_pin.sha256),
                    'Serialized producer differs from actual invocation')
                require(trace.header['fixture_sha256'] == hashlib.sha256(rom).hexdigest(),
                        'Serialized fixture differs from actual input')
                require(trace.final['complete'] and trace.final['retired'] == description['steps'],
                        'Toolkit capture did not complete actual retirement window')
                count = validate_literal_accesses(trace,profile)
                sources = validate_sources(trace,description)
                traces[tier] = trace
                report['runs'][label] = dict(trace=binding(target),observed=logs,disabled=disabled_logs,
                    literal_accesses=count,entry_source_bindings=sources,
                    nonperturbation=dict(equal=True,checkpoint_sha256=observed['checkpoint_sha256']),
                    calls=trace.final['calls'],retired=trace.final['retired'],events=trace.final['events'])
            internal = bus_trace.compare_traces(traces['native'],traces['interpreter'])
            require(internal['equal'], 'Actual translated/interpreted callbacks differ')
            internal_path = out/(profile+'-internal-comparison.json')
            internal_path.write_text(json.dumps(internal,indent=2)+'\n',encoding='utf-8')
            report['diagnostics'][profile+'-internal'] = binding(internal_path)
            for engine in ('gear','beetle'):
                original_info = references['runs'][engine+'-'+profile]
                original_path = Path(original_info['trace']['path'])
                original_pin = store.bind(original_path,expected_sha256=original_info['trace']['sha256'])
                original = bus_trace.load_trace(original_path)
                require(original.sha256 == original_pin.sha256, 'Original trace changed during parsing')
                validate_literal_accesses(original,profile)
                validate_sources(original,description,allow_continuations=True)
                require(original.header['fixture_sha256'] == description['fixture_sha256'],
                        'Independent reference fixture differs')
                for tier, trace in traces.items():
                    key = tier+'-'+engine+'-'+profile
                    comparisons = {}
                    for clock in ('exact','elapsed-origin-v1'):
                        comparisons[clock] = bus_trace.compare_traces(original,trace,
                            profile=clock,scope='mapped-callback-v1',structural=True)
                        require(comparisons[clock]['compatible'], 'Mapped callback scope unexpectedly incompatible')
                    # Preserve actual agreement as well as disagreement. In
                    # particular Gear's aggregate callbacks can match the
                    # toolkit while original Beetle clocks remain different.
                    path = out/(key+'-comparisons.json')
                    path.write_text(json.dumps(comparisons,indent=2)+'\n',encoding='utf-8')
                    report['diagnostics'][key] = binding(path)
        store.revalidate()
        verify_bindings(references)
        require(source_identity(ROOT) == identity, 'Toolkit sources changed during qualification')
        report.update(result='pass-observer-contract-with-preserved-reference-differences',
                      preserved_inputs_and_outputs=True)
    except Exception as error:
        report.update(result='fail', error=repr(error))
        raise
    finally:
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(result=report['result'],runs=len(report['runs']),
        original_comparisons=12,source_extents=256),indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--references',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    try:
        run(parser.parse_args())
    except (ValueError,OSError,KeyError,TypeError,subprocess.SubprocessError) as error:
        print(error,file=sys.stderr)
        raise SystemExit(1)
