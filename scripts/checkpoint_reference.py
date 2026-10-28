"""Fresh-process checkpoint continuation checks for authored ADPCM/IRQ programs.

The independent Gear run is produced separately by adpcm_irq_reference.py.
This adapter admits its actual, hashed journals and compares only the newly
executed suffix. No reference emulator state is imported into this runtime.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from generate_adpcm_irq_fixture import authored_fixture, make_program, literals, STEPS
from scripts import adpcm_irq_reference as oracle
from pcerecomp.capture import load_capture, validate_capture


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(row):
    return row['pc'], tuple(row['mpr']), tuple(row['physical']), tuple(row['data'])


def expected_sources(case):
    _, program, _, marker, _, mapping = make_program(case)
    _, _, sources = literals(case, program, marker, mapping)
    return Counter(identity(row) for row in sources)


def qualify(case, reports, captures, checkpoint_sha256, abi, gear=None):
    """Admit actual create/resume records; do not project any guest state."""
    expected = expected_sources(case)
    for tier in ('native', 'interpreter'):
        fields = {'case', 'tier', 'origin_ticks', 'imported_native', 'imported_interpreted',
                  'checkpoint_sha256', 'initial', 'rows', 'window_native',
                  'window_interpreted', 'final_state_sha256'}
        for mode in ('create', 'resume'):
            row = reports[tier][mode]
            require(type(row) is dict and set(row) == fields, 'Strict checkpoint execution fields required')
            require(row['case'] == case['id'] and row['tier'] == tier, 'Checkpoint case/tier differs')
            for key in ('origin_ticks', 'imported_native', 'imported_interpreted', 'window_native', 'window_interpreted'):
                require(type(row[key]) is int and row[key] >= 0, 'Typed checkpoint counters required')
            require(row['origin_ticks'] == sum(t for t, _ in oracle.primer_clocks(case, False)), 'Checkpoint raw origin clock differs')
            require((row['imported_native'], row['imported_interpreted']) ==
                    ((case['primer_steps'], 0) if tier == 'native' else (0, case['primer_steps'])), 'Imported prefix work differs')
            require((row['window_native'], row['window_interpreted']) ==
                    ((STEPS, 0) if tier == 'native' else (0, STEPS)), 'Fresh continuation work differs')
            require(row['checkpoint_sha256'] == checkpoint_sha256[tier], 'Saved payload digest differs')
            require(type(row['final_state_sha256']) is str and len(row['final_state_sha256']) == 64 and
                    all(c in '0123456789abcdef' for c in row['final_state_sha256']), 'Canonical final state digest required')
            oracle.row(row['initial'], case['initial'])
            require(type(row['rows']) is list and len(row['rows']) == STEPS, 'Exact checkpoint suffix extent required')
            for actual, literal in zip(row['rows'], case['expected']):
                oracle.row(actual, literal)
            capture = captures[tier][mode]
            validate_capture(capture)
            origin = dict(sha256=checkpoint_sha256[tier], ticks=row['origin_ticks'], frame=0,
                          native_steps=row['imported_native'], interpreter_steps=row['imported_interpreted'])
            require(capture.get('checkpoint_origin') == (origin if mode == 'resume' else None),
                    'Checkpoint capture origin differs or is falsely labeled from reset')
            require(capture['runtime_abi'] == abi and capture['complete'] and
                    capture['retired_instructions'] == STEPS and not capture['dropped_instructions'] and
                    not capture['unreadable_instructions'], 'Actual new-window capture required')
            hit, other = ('native_hits', 'interpreted_hits') if tier == 'native' else ('interpreted_hits', 'native_hits')
            require(not any(r[other] for r in capture['observations']), 'Continuation capture contains the wrong tier')
            require(Counter({identity(r): r[hit] for r in capture['observations']}) == expected,
                    'Full PC/eight-MPR/physical/fetched-byte suffix hits differ')
        require(reports[tier]['create'] == reports[tier]['resume'], 'Uninterrupted and fresh-process full-state suffix differ')
        restored = dict(captures[tier]['resume']); restored.pop('checkpoint_origin')
        require(captures[tier]['create'] == restored, 'Uninterrupted and fresh-process source-window captures differ')
    require(reports['native']['resume']['rows'] == reports['interpreter']['resume']['rows'], 'Execution tiers differ')
    if gear is not None:
        require(gear['case'] == case['id'] and gear['tier'] == 'gear', 'Independent original case differs')
        require(gear['rows'] == reports['native']['resume']['rows'] and gear['initial'] == reports['native']['resume']['initial'],
                'Checkpoint continuation differs from actual original Gear rows')
    return dict(case=case['id'], native_window=2*STEPS, interpreted_window=2*STEPS,
                restored_native_window=STEPS, restored_interpreted_window=STEPS,
                source_identities=len(expected), literal_checks=4*(STEPS+1)*38,
                original_gear=gear is not None)


def load_gear_evidence(folder, cases, abi):
    report = json.loads((folder / 'result.json').read_text())
    require(report['result'] == 'pass' and report['oracle_commit'] == oracle.ref.COMMIT,
            'Passed pinned original Gear execution required')
    admissions = report['bindings']['admissions']
    result = {}
    for case in cases:
        path = folder / case['id'] / 'admission.json'
        require(admissions.get(str(path)) == sha(path), 'Original admission digest differs')
        actual = json.loads(path.read_text())
        require(actual['case'] == case and actual['abi'] == abi, 'Current authored fixture/ABI differs from original proof')
        oracle.qualify(**actual)
        result[case['id']] = actual['outputs']['gear']
    return result


def run(args):
    out = args.out.resolve()
    require(not out.exists() and out.is_relative_to(ROOT / '.local'), 'New private output required')
    probe = args.probe.resolve()
    require(probe.is_file(), 'Existing newly built checkpoint probe required')
    from pcerecomp.project import ABI, source_identity
    cases, _, _ = authored_fixture()
    if args.case:
        cases = [c for c in cases if c['id'] in args.case]
        require(len(cases) == len(set(args.case)), 'Unknown/duplicate authored case')
    out.mkdir(parents=True)
    inputs = [Path(__file__), ROOT/'tests/checkpoint_probe.cpp', ROOT/'tests/generate_adpcm_irq_fixture.py',
              ROOT/'tests/generate_irq_device_fixture.py', ROOT/'scripts/adpcm_irq_reference.py', probe]
    bindings = {str(p): sha(p) for p in inputs}
    report = dict(schema=1, passed=False, tool=source_identity(ROOT), inputs=bindings, cases=[],
                  scope='Authored fresh-process payload continuations; 48 newly retired suffix opcodes per run, full source windows and independent CPU/device/WRAM literals. Host-seeded device matrix is separate. No retail, analog or cross-version state claim.')
    try:
        gear = load_gear_evidence(args.gear_evidence.resolve(), cases, ABI) if args.gear_evidence else {}
        if args.gear_evidence:
            report['gear_evidence'] = dict(path=str(args.gear_evidence.resolve()/'result.json'), sha256=sha(args.gear_evidence/'result.json'))
        for case in cases:
            folder = out/case['id']; folder.mkdir()
            reports = {}; captures = {}; digests = {}; controls = []
            for tier in ('native', 'interpreter'):
                reports[tier] = {}; captures[tier] = {}; payload = folder/(tier+'.pcec')
                for mode in ('create', 'resume'):
                    cap = folder/(tier+'-'+mode+'-capture.json')
                    command = [str(probe), mode, case['id'], tier, str(payload), str(cap)]
                    actual = subprocess.run(command, capture_output=True, text=True, timeout=90)
                    (folder/(tier+'-'+mode+'.stdout')).write_text(actual.stdout)
                    (folder/(tier+'-'+mode+'.stderr')).write_text(actual.stderr)
                    actual.check_returncode(); reports[tier][mode] = json.loads(actual.stdout)
                    captures[tier][mode], _ = load_capture(cap)
                digests[tier] = sha(payload)
                raw = payload.read_bytes()
                copies = {'empty': b'', 'truncated': raw[:-1], 'trailing': raw+b'\0',
                          'magic': bytes([raw[0]^255])+raw[1:], 'short-header': raw[:7]}
                for name, data in copies.items():
                    corrupt = folder/(tier+'-'+name+'.pcec'); corrupt.write_bytes(data)
                    command = [str(probe), 'reject', case['id'], tier, str(corrupt), 'unused']
                    actual = subprocess.run(command, capture_output=True, text=True, timeout=90)
                    actual.check_returncode(); evidence = json.loads(actual.stdout)
                    require(evidence['rejected'] is True and evidence['unchanged'] is True, 'Actual written/reloaded rejection failed')
                    controls.append(dict(tier=tier, mutation=name, copy_sha256=sha(corrupt), actual=evidence))
                actual = subprocess.run([str(probe), 'profile', case['id'], tier, str(payload), 'unused'], capture_output=True, text=True, timeout=90)
                actual.check_returncode(); evidence = json.loads(actual.stdout)
                require(evidence['rejected'] is True and evidence['unchanged'] is True, 'Actual configured-profile rejection failed')
                controls.append(dict(tier=tier, mutation='configured-profile', actual=evidence))
            result = qualify(case, reports, captures, digests, ABI, gear.get(case['id']))
            result['actual_rejections'] = len(controls); report['cases'].append(result)
            (folder/'admission.json').write_text(json.dumps(dict(case=case, reports=reports, captures=captures,
                checkpoint_sha256=digests, abi=ABI, gear=gear.get(case['id']), controls=controls), indent=2)+'\n')
            print(json.dumps(result), flush=True)
        require(all(sha(p) == digest for p, digest in bindings.items()), 'In-flight probe or authored inputs changed')
        require(source_identity(ROOT) == report['tool'], 'In-flight runtime/compiler source identity changed')
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        (out/'result.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--gear-evidence', type=Path)
    parser.add_argument('--case', action='append', default=[])
    try:
        run(parser.parse_args())
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
