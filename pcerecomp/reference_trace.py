"""Bounded, code-free instruction-boundary reference traces and comparison.

Run ``python -m pcerecomp.reference_trace EXPECTED ACTUAL``. Engine identity is
preserved, never treated as a field to project until two traces agree. Raw
status, mapping, clock and memory values are compared without normalization.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import BinaryIO


FORMAT = 'pce-cpu-trace-1'
MAX_RECORDS = 100000
MAX_LINE_BYTES = 16384
MAX_FILE_BYTES = 128 * 1024 * 1024
STATE_FIELDS = ('pc', 'a', 'x', 'y', 'sp', 'p', 'mpr', 'mpr_latch',
                'physical_pc', 'clock_divisor', 'ticks', 'wram_sha256')
PROFILES = ('exact', 'architectural-v1', 'architectural-elapsed-v1')


@dataclass(frozen=True)
class Trace:
    header: dict
    initial: dict
    instructions: tuple[dict, ...]
    final: dict
    sha256: str


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _keys(value, expected, label):
    _require(type(value) is dict and set(value) == set(expected), label+' fields differ')


def _integer(value, maximum, label, minimum=0):
    _require(type(value) is int and minimum <= value <= maximum, 'Invalid '+label)


def _digest(value, length, label):
    _require(type(value) is str and re.fullmatch('[0-9a-f]{'+str(length)+'}', value) is not None,
             'Invalid '+label)


def _mpr(value, label):
    _require(type(value) is list and len(value) == 8, 'Invalid '+label)
    for bank in value:
        _integer(bank, 255, label+' byte')


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'Duplicate JSON key: '+key)
            result[key] = value
        return result

    def constant(value):
        raise ValueError('Invalid JSON constant: '+value)

    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('Invalid trace JSON or UTF-8') from error


def _header(value):
    _keys(value, ('type', 'schema', 'format', 'engine', 'fixture_sha256', 'case',
                  'clock', 'phase', 'unavailable_fields'), 'Header')
    _require(value['type'] == 'header' and type(value['schema']) is int and value['schema'] == 1
             and value['format'] == FORMAT, 'Unsupported trace header')
    _keys(value['engine'], ('name', 'revision', 'source_sha256', 'binary_sha256'), 'Engine')
    engine = value['engine']
    _require(type(engine['name']) is str and
             re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._+\-]{0,63}', engine['name']) is not None,
             'Invalid engine name')
    _digest(engine['revision'], 40, 'engine revision')
    for key in ('source_sha256', 'binary_sha256'):
        _digest(engine[key], 64, 'engine '+key)
    _digest(value['fixture_sha256'], 64, 'fixture SHA256')
    _require(type(value['case']) is str and
             re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._\-]{0,95}', value['case']) is not None,
             'Invalid trace case')
    _require(value['clock'] == 'master-ticks' and value['phase'] == 'instruction-boundary',
             'Unsupported trace clock or phase')
    _require(type(value['unavailable_fields']) is list and
             value['unavailable_fields'] in ([], ['mpr_latch']), 'Invalid unavailable fields')


def _state(value, unavailable):
    _keys(value, STATE_FIELDS, 'State')
    _integer(value['pc'], 65535, 'PC')
    for field in ('a', 'x', 'y', 'sp', 'p'):
        _integer(value[field], 255, field)
    _mpr(value['mpr'], 'MPR')
    if 'mpr_latch' in unavailable:
        _require(value['mpr_latch'] is None, 'Unavailable MPR latch must be null')
    else:
        _integer(value['mpr_latch'], 255, 'MPR latch')
    _integer(value['physical_pc'], 0x1FFFFF, 'physical PC')
    _require(value['physical_pc'] == (value['mpr'][value['pc'] >> 13] << 13) | (value['pc'] & 8191),
             'Physical PC differs from complete mapping')
    _require(type(value['clock_divisor']) is int and value['clock_divisor'] in (3, 12),
             'Invalid CPU clock divisor')
    _integer(value['ticks'], 2**64-1, 'master ticks')
    _digest(value['wram_sha256'], 64, 'WRAM SHA256')


def _load(stream: BinaryIO, *, max_records, max_line_bytes, max_file_bytes):
    for value, maximum, label in ((max_records, MAX_RECORDS, 'record bound'),
                                  (max_line_bytes, MAX_LINE_BYTES, 'line bound'),
                                  (max_file_bytes, MAX_FILE_BYTES, 'file bound')):
        _integer(value, maximum, label, 1)
    header = initial = final = previous = None
    instructions = []
    digest = hashlib.sha256()
    total = count = 0
    while True:
        raw = stream.readline(max_line_bytes + 1)
        if not raw:
            break
        total += len(raw)
        count += 1
        _require(total <= max_file_bytes, 'Trace file bound exceeded')
        _require(len(raw) <= max_line_bytes, 'Trace line bound exceeded')
        _require(count <= max_records, 'Trace record bound exceeded')
        digest.update(raw)
        value = _json(raw)
        if header is None:
            _header(value)
            header = value
        elif initial is None:
            _keys(value, ('type', 'state'), 'Initial record')
            _require(value['type'] == 'initial', 'Initial record required')
            _state(value['state'], header['unavailable_fields'])
            initial = previous = value['state']
        elif final is not None:
            raise ValueError('Records after final record')
        elif type(value) is dict and value.get('type') == 'instruction':
            _keys(value, ('type', 'ordinal', 'entry_pc', 'entry_mpr', 'state'), 'Instruction record')
            _integer(value['ordinal'], MAX_RECORDS, 'instruction ordinal', 1)
            _require(value['ordinal'] == len(instructions)+1, 'Noncontiguous instruction ordinal')
            _integer(value['entry_pc'], 65535, 'entry PC')
            _mpr(value['entry_mpr'], 'entry MPR')
            _require(value['entry_pc'] == previous['pc'] and value['entry_mpr'] == previous['mpr'],
                     'Instruction entry differs from previous state')
            _state(value['state'], header['unavailable_fields'])
            _require(value['state']['ticks'] > previous['ticks'], 'Instruction master ticks must increase')
            instructions.append(value)
            previous = value['state']
        else:
            _keys(value, ('type', 'executed', 'stop', 'complete'), 'Final record')
            _require(value['type'] == 'final' and value['stop'] == 'instruction-limit'
                     and value['complete'] is True, 'Complete instruction-limit final record required')
            _integer(value['executed'], MAX_RECORDS, 'final executed count')
            _require(value['executed'] == len(instructions), 'Final executed count differs')
            final = value
    _require(header is not None and initial is not None and final is not None,
             'Incomplete trace: header, initial and final records required')
    return Trace(header, initial, tuple(instructions), final, digest.hexdigest())


def load_trace(path: Path, *, max_records=MAX_RECORDS, max_line_bytes=MAX_LINE_BYTES,
               max_file_bytes=MAX_FILE_BYTES) -> Trace:
    """Read bounded JSONL: 100,000 total records allow 99,997 instructions.

    The header, initial state and final marker consume three records. Line and
    file bounds count encoded bytes, including newline bytes.
    """
    with Path(path).open('rb') as stream:
        return _load(stream, max_records=max_records, max_line_bytes=max_line_bytes,
                     max_file_bytes=max_file_bytes)


def parse_trace(data: bytes, **limits) -> Trace:
    """Validate an in-memory JSONL byte sequence without writing a file."""
    from io import BytesIO
    _require(type(data) is bytes, 'Trace input must be bytes')
    return _load(BytesIO(data), max_records=limits.pop('max_records', MAX_RECORDS),
                 max_line_bytes=limits.pop('max_line_bytes', MAX_LINE_BYTES),
                 max_file_bytes=limits.pop('max_file_bytes', MAX_FILE_BYTES), **limits)


def compare_traces(expected: Trace, actual: Trace, *, profile='exact') -> dict:
    """Report the first raw divergence; engine identities need not match.

    Architectural-v1 excludes only the unexposed transfer latch. The separately
    named architectural-elapsed-v1 additionally compares time from each trace's
    own initial epoch, retaining raw origins and every elapsed timing difference.
    Neither establishes TAM/TMA latch parity. No profile masks status or MPRs.
    """
    _require(isinstance(expected, Trace) and isinstance(actual, Trace), 'Validated traces required')
    _require(type(profile) is str and profile in PROFILES, 'Unsupported comparison profile')
    fields = tuple(field for field in STATE_FIELDS if profile == 'exact' or field != 'mpr_latch')
    elapsed = profile == 'architectural-elapsed-v1'
    unavailable = set(expected.header['unavailable_fields']) | set(actual.header['unavailable_fields'])
    unchecked = []
    if profile != 'exact' or unavailable:
        unchecked.append(dict(field='mpr_latch', reason=(
            profile+' excludes only the transfer latch; no TAM/TMA latch parity claim'
            if profile != 'exact' else 'MPR latch is unavailable in one or both engines; null is availability metadata')))
    result = dict(schema=1, format='pce-trace-comparison-1', profile=profile, compatible=True,
        equal=False, expected_engine=expected.header['engine'], actual_engine=actual.header['engine'],
        expected_trace_sha256=expected.sha256, actual_trace_sha256=actual.sha256,
        fixture_sha256=expected.header['fixture_sha256'], case=expected.header['case'],
        clock=expected.header['clock'], phase=expected.header['phase'],
        clock_comparison_policy='elapsed-from-initial-state' if elapsed else 'raw-master-ticks',
        clock_origins=dict(expected=expected.initial['ticks'], actual=actual.initial['ticks']),
        comparison_state_fields=list(fields),
        checked_state_fields=[field for field in fields if field not in unavailable],
        unchecked_state_fields=unchecked, initial_matched=False, matched_instructions=0,
        expected_instructions=len(expected.instructions), actual_instructions=len(actual.instructions),
        first_difference=None)

    def difference(ordinal, field, a, b):
        result['first_difference'] = dict(ordinal=ordinal, field=field, expected=a, actual=b)
        return result

    for field in ('fixture_sha256', 'case', 'clock', 'phase'):
        if expected.header[field] != actual.header[field]:
            result['compatible'] = False
            return difference(None, 'header.'+field, expected.header[field], actual.header[field])

    def state_difference(ordinal, a, b):
        for field in fields:
            if field == 'ticks' and elapsed:
                expected_elapsed = a[field]-expected.initial['ticks']
                actual_elapsed = b[field]-actual.initial['ticks']
                if expected_elapsed != actual_elapsed:
                    mismatch = difference(ordinal, 'state.ticks', a[field], b[field])
                    mismatch['first_difference'].update(expected_elapsed=expected_elapsed,
                                                        actual_elapsed=actual_elapsed)
                    return mismatch
                continue
            if a[field] != b[field]:
                return difference(ordinal, 'state.'+field, a[field], b[field])
        return None

    mismatched = state_difference(0, expected.initial, actual.initial)
    if mismatched is not None:
        return mismatched
    result['initial_matched'] = True
    for ordinal, (a, b) in enumerate(zip(expected.instructions, actual.instructions), 1):
        for field in ('entry_pc', 'entry_mpr'):
            if a[field] != b[field]:
                return difference(ordinal, field, a[field], b[field])
        mismatched = state_difference(ordinal, a['state'], b['state'])
        if mismatched is not None:
            return mismatched
        result['matched_instructions'] += 1
    if len(expected.instructions) != len(actual.instructions):
        return difference(result['matched_instructions']+1, 'instruction.present',
                          result['matched_instructions'] < len(expected.instructions),
                          result['matched_instructions'] < len(actual.instructions))
    result['equal'] = True
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('expected', type=Path)
    parser.add_argument('actual', type=Path)
    parser.add_argument('--profile', choices=PROFILES, default='exact')
    parser.add_argument('--out', type=Path, help='Write a NEW comparison report')
    args = parser.parse_args(argv)
    try:
        result = compare_traces(load_trace(args.expected), load_trace(args.actual), profile=args.profile)
        text = json.dumps(result, indent=2, allow_nan=False)+'\n'
        if args.out is not None:
            with args.out.open('x', encoding='utf-8') as stream:
                stream.write(text)
        else:
            print(text, end='')
        return 0 if result['equal'] else 1
    except (ValueError, OSError) as error:
        # OSError filenames may contain private absolute paths; never echo them.
        print(json.dumps(dict(schema=1, format='pce-trace-comparison-1', valid=False,
                              error=str(error) if isinstance(error, ValueError) else 'Trace file operation failed')))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
