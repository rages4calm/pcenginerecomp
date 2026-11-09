"""Strict chronological software bus-callback traces, never inferred bus cycles.

Execution calls and their measured retirement deltas are separate observations.
Source identities describe the dispatch-entry candidate, including calls which
retire no opcode. Hash syntax is not proof of the producer or captured bytes.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import sys

from . import reference_trace as cpu
from .snapshots import _strict_json

FORMAT = 'pce-bus-event-trace-1'
PROFILE = 'software-access-callback-v1'
PHASE = 'callback-return-before-caller-clock'
MAX_RECORDS = cpu.MAX_RECORDS
MAX_LINE_BYTES = cpu.MAX_LINE_BYTES
MAX_FILE_BYTES = cpu.MAX_FILE_BYTES
MAX_TICKS = (1 << 64) - 1
STATE_FIELDS = tuple(field for field in cpu.STATE_FIELDS if field != 'mpr_latch')
CAPABILITIES = ('mapped', 'fixed_vdc', 'data', 'fetch', 'purpose', 'dummy',
                'idle', 'mpr_latch', 'irq', 'tier_counters')
PROFILES = ('exact', 'elapsed-origin-v1')
SCOPES = ('exact', 'mapped-callback-v1')
_require, _keys, _integer = cpu._require, cpu._keys, cpu._integer


@dataclass(frozen=True)
class Trace:
    header: dict
    initial: dict
    records: tuple[dict, ...]
    calls: tuple[dict, ...]
    events: tuple[dict, ...]
    final: dict
    sha256: str


def source_identity(pc: int, mpr: list[int], encoded: bytes) -> dict:
    """Bind exact entry bytes and mapped addresses, without exporting the bytes.

    Producers must supply bytes observed at dispatch entry, before execution.
    This helper cannot recover them from a later snapshot or attest their origin.
    """
    _integer(pc, 65535, 'source PC')
    cpu._mpr(mpr, 'source MPR')
    _require(type(encoded) is bytes and 1 <= len(encoded) <= 7,
             'Source requires one through seven encoded entry bytes')
    payload = bytearray(b'pce-bus-source-1\0')
    payload.extend(pc.to_bytes(2, 'little'))
    payload.extend(mpr)
    payload.append(len(encoded))
    for offset, byte in enumerate(encoded):
        logical = (pc + offset) & 65535
        physical = (mpr[logical >> 13] << 13) | (logical & 8191)
        payload.extend(physical.to_bytes(4, 'little'))
        payload.append(byte)
    return dict(kind='dispatch-entry-candidate', length=len(encoded),
                sha256=hashlib.sha256(payload).hexdigest())


def encode_records(records) -> bytes:
    """Encode records deterministically; parsing remains the admission gate."""
    return b''.join(json.dumps(row, separators=(',', ':'), allow_nan=False,
                              ensure_ascii=True).encode('utf-8') + b'\n'
                    for row in records)


def _state(value):
    _keys(value, STATE_FIELDS, 'State')
    # Keep the old trace format unchanged while reusing its precise validators.
    cpu._state(dict(value, mpr_latch=None), ['mpr_latch'])


def _header(row):
    fields = ('type', 'schema', 'format', 'engine', 'fixture_sha256', 'case',
              'clock', 'profile', 'phase', 'call_model', 'capabilities', 'limits')
    _require(type(row) is dict, 'Header fields differ')
    _keys(row, fields + (('checkpoint_origin',) if 'checkpoint_origin' in row else ()), 'Header')
    _require(row['type'] == 'header' and type(row['schema']) is int and row['schema'] == 1
             and row['format'] == FORMAT, 'Unsupported bus trace header')
    cpu._header(dict(type='header', schema=1, format=cpu.FORMAT,
        engine=row['engine'], fixture_sha256=row['fixture_sha256'], case=row['case'],
        clock=row['clock'], phase='instruction-boundary', unavailable_fields=[]))
    _require(row['profile'] == PROFILE and row['phase'] == PHASE,
             'Unsupported bus observation profile or phase')
    _require(row['call_model'] in ('aggregate', 'split'), 'Invalid call model')
    caps = row['capabilities']
    _keys(caps, CAPABILITIES, 'Capabilities')
    for field in CAPABILITIES:
        _require(type(caps[field]) is bool, 'Invalid capability ' + field)
    _require(caps['mapped'] and caps['data'], 'Mapped data observation required')
    _require(not any(caps[field] for field in ('fetch', 'purpose', 'dummy', 'idle', 'mpr_latch')),
             'Unsupported observation capability')
    _keys(row['limits'], ('calls', 'events', 'retired', 'wall_ms'), 'Limits')
    for field in ('calls', 'events', 'retired'):
        _integer(row['limits'][field], MAX_RECORDS, field + ' execution limit', 1)
    _integer(row['limits']['wall_ms'], 3600000, 'wall execution limit', 1)
    if 'checkpoint_origin' in row:
        origin = row['checkpoint_origin']
        _keys(origin, ('sha256', 'ticks', 'frame', 'native_steps', 'interpreter_steps'),
              'Checkpoint origin')
        cpu._digest(origin['sha256'], 64, 'checkpoint origin SHA256')
        for field in ('ticks', 'frame', 'native_steps', 'interpreter_steps'):
            _integer(origin[field], MAX_TICKS, 'checkpoint origin ' + field)


def _source(value):
    _keys(value, ('kind', 'length', 'sha256'), 'Source')
    _require(value['kind'] == 'dispatch-entry-candidate', 'Invalid source identity kind')
    _integer(value['length'], 7, 'source encoded length', 1)
    cpu._digest(value['sha256'], 64, 'source SHA256')


def _event(row, active, ordinal, last_tick, caps):
    _keys(row, ('type', 'ordinal', 'call_ordinal', 'ticks', 'direction', 'phase',
                'space', 'logical', 'mpr', 'physical', 'value', 'purpose', 'dummy'), 'Access')
    _integer(row['ordinal'], MAX_RECORDS, 'access ordinal', 1)
    _integer(row['call_ordinal'], MAX_RECORDS, 'access call ordinal', 1)
    _require(row['ordinal'] == ordinal and row['call_ordinal'] == active['ordinal'],
             'Noncontiguous access ordinal or wrong execution call')
    _integer(row['ticks'], MAX_TICKS, 'access ticks')
    _require(row['ticks'] >= last_tick, 'Access clock moved backwards')
    _require(row['direction'] in ('read', 'write'), 'Invalid access direction')
    _require(row['phase'] == row['direction'] + '-return', 'Access sampling phase differs')
    _require(row['purpose'] is None and row['dummy'] is None,
             'Unavailable access purpose/dummy must be null')
    _integer(row['physical'], 0x1FFFFF, 'access physical address')
    _integer(row['value'], 255, 'access byte')
    if row['space'] == 'mapped':
        _integer(row['logical'], 65535, 'access logical address')
        cpu._mpr(row['mpr'], 'access MPR')
        physical = (row['mpr'][row['logical'] >> 13] << 13) | (row['logical'] & 8191)
        _require(row['physical'] == physical, 'Access physical address differs from mapping')
    else:
        _require(row['space'] == 'fixed-vdc' and caps['fixed_vdc'], 'Unsupported access space')
        _require(row['logical'] is None and row['mpr'] is None,
                 'Fixed VDC address has no logical mapping')
        _require(row['direction'] == 'write' and row['physical'] in (0, 2, 3),
                 'Invalid fixed VDC port access')


def _limits(values):
    limits = dict(max_records=MAX_RECORDS, max_line_bytes=MAX_LINE_BYTES, max_file_bytes=MAX_FILE_BYTES)
    _require(not (set(values) - set(limits)), 'Unknown trace bound')
    limits.update(values)
    for field, maximum in (('max_records', MAX_RECORDS), ('max_line_bytes', MAX_LINE_BYTES),
                           ('max_file_bytes', MAX_FILE_BYTES)):
        _integer(limits[field], maximum, field, 1)
    return limits


def _load(stream, *, max_records, max_line_bytes, max_file_bytes):
    header = initial = previous = active = final = None
    records, calls, events = [], [], []
    count = total = retired = 0
    missing_source = False
    digest = hashlib.sha256()
    last_tick = 0
    while True:
        raw = stream.readline(max_line_bytes + 1)
        if not raw:
            break
        total += len(raw)
        count += 1
        _require(total <= max_file_bytes, 'Trace file bound exceeded')
        _require(len(raw) <= max_line_bytes, 'Trace line bound exceeded')
        _require(count <= max_records, 'Trace record bound exceeded')
        _require(raw.endswith(b'\n'), 'Unterminated JSONL record')
        digest.update(raw)
        row = _strict_json(raw)
        if header is None:
            _header(row)
            header = row
        elif initial is None:
            _keys(row, ('type', 'state'), 'Initial record')
            _require(row['type'] == 'initial', 'Initial record required')
            _state(row['state'])
            initial = previous = row['state']
            if 'checkpoint_origin' in header:
                _require(initial['ticks'] >= header['checkpoint_origin']['ticks'],
                         'Initial state precedes checkpoint origin')
            last_tick = initial['ticks']
        elif final is not None:
            raise ValueError('Records after final record')
        elif type(row) is dict and row.get('type') == 'call-begin':
            _keys(row, ('type', 'ordinal', 'entry', 'source'), 'Call entry')
            _require(active is None, 'Nested execution call')
            _integer(row['ordinal'], MAX_RECORDS, 'call ordinal', 1)
            _require(row['ordinal'] == len(calls) + 1, 'Noncontiguous call ordinal')
            _require(row['ordinal'] <= header['limits']['calls'], 'Call execution limit exceeded')
            _state(row['entry'])
            _require(row['entry'] == previous, 'Call entry breaks state chain')
            if row['source'] is None:
                missing_source = True
            else:
                _source(row['source'])
            active = row
            records.append(row)
        elif type(row) is dict and row.get('type') == 'access':
            _require(active is not None, 'Access outside execution call')
            _event(row, active, len(events) + 1, last_tick, header['capabilities'])
            _require(row['ordinal'] <= header['limits']['events'], 'Access execution limit exceeded')
            last_tick = row['ticks']
            events.append(row)
            records.append(row)
        elif type(row) is dict and row.get('type') == 'call-end':
            _keys(row, ('type', 'ordinal', 'kind', 'state', 'retired', 'native', 'interpreted', 'irq'),
                  'Call return')
            _require(active is not None, 'Call return without entry')
            _integer(row['ordinal'], MAX_RECORDS, 'call return ordinal', 1)
            _require(row['ordinal'] == active['ordinal'], 'Call return ordinal differs')
            _require(row['kind'] == 'execution-call', 'Invalid call kind')
            _state(row['state'])
            _require(row['state']['ticks'] >= last_tick, 'Call return clock differs')
            _integer(row['retired'], MAX_RECORDS, 'actual retired delta')
            for field in ('native', 'interpreted', 'irq'):
                available = header['capabilities']['irq' if field == 'irq' else 'tier_counters']
                if available:
                    _integer(row[field], MAX_RECORDS, 'actual ' + field + ' delta')
                else:
                    _require(row[field] is None, 'Unavailable ' + field + ' delta must be null')
            if header['capabilities']['tier_counters']:
                _require(row['native'] + row['interpreted'] == row['retired'],
                         'Tier counters differ from actual retirement delta')
            retired += row['retired']
            _require(retired <= header['limits']['retired'], 'Retirement execution limit exceeded')
            calls.append(dict(entry=active, end=row))
            records.append(row)
            previous = row['state']
            last_tick = previous['ticks']
            active = None
        else:
            _keys(row, ('type', 'calls', 'retired', 'events', 'stop', 'complete', 'state'), 'Final record')
            _require(row['type'] == 'final' and active is None, 'Final leaves unclosed execution call')
            _require(type(row['complete']) is bool, 'Invalid final complete flag')
            for field, actual in (('calls', len(calls)), ('retired', retired), ('events', len(events))):
                _integer(row[field], MAX_RECORDS, 'final ' + field)
                _require(row[field] == actual, 'Final ' + field + ' count differs')
            _state(row['state'])
            _require(row['state'] == previous, 'Final state breaks closed chain')
            if row['complete']:
                _require(not missing_source, 'Complete trace requires every entry source identity')
                _require(row['stop'] in ('call-limit', 'retirement-limit'), 'Invalid complete stop')
                field = 'calls' if row['stop'] == 'call-limit' else 'retired'
                _require(row[field] == header['limits'][field], 'Final did not reach declared stop')
            else:
                _require(row['stop'] in ('event-limit', 'wall-limit', 'fault', 'source-mismatch', 'cancelled'),
                         'Invalid incomplete stop')
                if row['stop'] == 'event-limit':
                    _require(row['events'] == header['limits']['events'], 'Event limit not reached')
                _require(not missing_source or row['stop'] == 'source-mismatch',
                         'Unavailable source requires source-mismatch diagnostic closure')
            final = row
    _require(header is not None and initial is not None and final is not None, 'Incomplete bus trace')
    return Trace(header, initial, tuple(records), tuple(calls), tuple(events), final, digest.hexdigest())


def parse_trace(data: bytes, **limits) -> Trace:
    _require(type(data) is bytes, 'Trace input must be bytes')
    return _load(io.BytesIO(data), **_limits(limits))


def load_trace(path: Path, **limits) -> Trace:
    admitted = _limits(limits)
    with Path(path).open('rb') as stream:
        return _load(stream, **admitted)


def compare_traces(expected: Trace, actual: Trace, *, profile='exact', structural=False, scope='exact') -> dict:
    """Compare raw chronological observations; optionally describe structure too.

    Tier counters are provenance, not a guest-equivalence comparison. Unknown
    counters are reported as unknown. Structural correspondence never converts
    differing timestamps into equality. Only elapsed-origin-v1 subtracts epochs.
    """
    _require(isinstance(expected, Trace) and isinstance(actual, Trace), 'Validated traces required')
    _require(type(profile) is str and profile in PROFILES, 'Unsupported comparison profile')
    _require(type(scope) is str and scope in SCOPES, 'Unsupported comparison scope')
    _require(type(structural) is bool, 'Invalid structural report flag')
    elapsed = profile == 'elapsed-origin-v1'
    mapped = scope == 'mapped-callback-v1'
    result = dict(schema=1, format='pce-bus-comparison-1', profile=profile, scope=scope, compatible=True,
        equal=False, expected_engine=expected.header['engine'], actual_engine=actual.header['engine'],
        expected_trace_sha256=expected.sha256, actual_trace_sha256=actual.sha256,
        clock_origins=dict(expected=expected.initial['ticks'], actual=actual.initial['ticks']),
        clock_policy='elapsed-from-initial-state' if elapsed else 'raw-master-ticks',
        execution_limits=dict(expected=expected.header['limits'], actual=actual.header['limits']),
        checkpoint_origins=dict(expected=expected.header.get('checkpoint_origin'),
                                actual=actual.header.get('checkpoint_origin')),
        call_models=dict(expected=expected.header['call_model'], actual=actual.header['call_model']),
        closure_policies=dict(expected=expected.final['stop'], actual=actual.final['stop']),
        observation_capabilities=dict(expected=expected.header['capabilities'],
                                      actual=actual.header['capabilities']),
        matched_records=0, matched_events=0, first_difference=None,
        observation_scope=expected.header['capabilities'], counter_observations={},
        structural_correspondence=None)

    def difference(ordinal, field, left, right, **extra):
        return dict(ordinal=ordinal, field=field, expected=left, actual=right, **extra)

    for field in ('fixture_sha256', 'case', 'clock', 'profile', 'phase', 'call_model'):
        if mapped and field == 'call_model':
            continue
        if expected.header[field] != actual.header[field]:
            result['compatible'] = False
            result['first_difference'] = difference(None, 'header.' + field,
                                                     expected.header[field], actual.header[field])
            return result
    for field in CAPABILITIES:
        if (field not in ('tier_counters', 'irq') and not (mapped and field == 'fixed_vdc')
                and expected.header['capabilities'][field] != actual.header['capabilities'][field]):
            result['compatible'] = False
            result['first_difference'] = difference(None, 'header.capabilities.' + field,
                expected.header['capabilities'][field], actual.header['capabilities'][field])
            return result
    if mapped:
        for label, trace in (('expected', expected), ('actual', actual)):
            if any(event['space'] != 'mapped' for event in trace.events):
                result['compatible'] = False
                result['first_difference'] = difference(None, 'scope.mapped-callback-v1',
                    'every actual event must be mapped', label + ' contains fixed-vdc access')
                return result
    for field in ('native', 'interpreted', 'irq'):
        left = [call['end'][field] for call in expected.calls]
        right = [call['end'][field] for call in actual.calls]
        cap = 'irq' if field == 'irq' else 'tier_counters'
        observed = expected.header['capabilities'][cap] and actual.header['capabilities'][cap]
        result['counter_observations'][field] = dict(expected=left, actual=right,
            both_observed=observed, equal=(left == right) if observed else None,
            compared=(field == 'irq' and observed))
    if not expected.final['complete'] or not actual.final['complete']:
        result['compatible'] = False
        result['first_difference'] = difference(None, 'final.complete',
            expected.final['complete'], actual.final['complete'])
        return result

    origins = (expected.initial['ticks'], actual.initial['ticks'])
    timing, structural_difference = [], None

    def walk(left, right, path, ordinal):
        nonlocal structural_difference
        if type(left) is dict and type(right) is dict:
            if left.get('type') != right.get('type'):
                mismatch = difference(ordinal, path + '.type', left.get('type'), right.get('type'))
                if structural_difference is None:
                    structural_difference = mismatch
                yield mismatch
                return
            # Validated records have closed fields; preserve their canonical
            # schema order, independently of the producer's JSON key order.
            fields = sorted(set(left) | set(right))
            if 'type' in fields:
                fields.remove('type'); fields.insert(0, 'type')
            for field in fields:
                if mapped and field == 'stop' and path == 'final':
                    continue
                if field in ('native', 'interpreted') and path == 'record':
                    continue
                if field == 'irq' and path == 'record' and not result['counter_observations']['irq']['both_observed']:
                    continue
                yield from walk(left.get(field), right.get(field), path + '.' + field, ordinal)
            return
        is_tick = path.endswith('.ticks')
        a, b = left, right
        if is_tick and elapsed:
            a, b = left - origins[0], right - origins[1]
        if a != b:
            extra = dict(expected_elapsed=a, actual_elapsed=b) if is_tick and elapsed else {}
            mismatch = difference(ordinal, path, left, right, **extra)
            if is_tick:
                timing.append(mismatch)
            elif structural_difference is None:
                structural_difference = mismatch
            yield mismatch

    initial_differences = list(walk(expected.initial, actual.initial, 'initial', 0))
    if initial_differences:
        result['first_difference'] = initial_differences[0]
    for ordinal in range(max(len(expected.records), len(actual.records))):
        if ordinal >= len(expected.records) or ordinal >= len(actual.records):
            mismatch = difference(ordinal + 1, 'record.present', ordinal < len(expected.records),
                                  ordinal < len(actual.records))
            if structural_difference is None:
                structural_difference = mismatch
            if result['first_difference'] is None:
                result['first_difference'] = mismatch
            break
        left, right = expected.records[ordinal], actual.records[ordinal]
        differences = list(walk(left, right, 'record', ordinal + 1))
        if differences and result['first_difference'] is None:
            result['first_difference'] = differences[0]
        if result['first_difference'] is None:
            result['matched_records'] += 1
            if left['type'] == 'access':
                result['matched_events'] += 1
    final_differences = list(walk(expected.final, actual.final, 'final', len(expected.records) + 1))
    if final_differences and result['first_difference'] is None:
        result['first_difference'] = final_differences[0]
    result['equal'] = result['first_difference'] is None
    if structural:
        result['structural_correspondence'] = dict(matched=structural_difference is None,
            first_difference=structural_difference, timing_differences=timing,
            timing_equal=not timing, qualification='structure-only; timestamps remain observed differences')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('expected', type=Path)
    parser.add_argument('actual', type=Path)
    parser.add_argument('--profile', choices=PROFILES, default='exact')
    parser.add_argument('--scope', choices=SCOPES, default='exact')
    parser.add_argument('--structural', action='store_true')
    parser.add_argument('--out', type=Path, help='Create a new report without overwriting any file')
    args = parser.parse_args(argv)
    try:
        result = compare_traces(load_trace(args.expected), load_trace(args.actual),
                                profile=args.profile, structural=args.structural, scope=args.scope)
        report = json.dumps(result, indent=2, allow_nan=False) + '\n'
        if args.out is None:
            print(report, end='')
        else:
            _require(not args.out.is_symlink(), 'Report path must not be a symbolic link')
            _require(args.out.resolve() not in (args.expected.resolve(), args.actual.resolve()),
                     'Report path must not alias either trace input')
            with args.out.open('x', encoding='utf-8') as stream:
                stream.write(report)
        return 0 if result['equal'] else (1 if result['compatible'] else 2)
    except (ValueError, OSError, RuntimeError) as error:
        message = str(error) if isinstance(error, ValueError) else 'Trace file operation failed'
        print('Bus trace: ' + ' '.join(message.split())[:240], file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
