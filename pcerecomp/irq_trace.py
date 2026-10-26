"""Strict code-free raw-call traces and explicit post-IRQ retirement boundaries.

V1 remains unchanged. This format never counts interrupt entry or a resumed
block-transfer call as an opcode retirement. Cross-engine boundary comparison
is an explicitly named scope, distinct from exact raw-call comparison.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import sys

from . import reference_trace as v1

FORMAT = 'pce-cpu-trace-2'
PHASE = 'retirement-boundary-after-irq'
MAX_RECORDS = v1.MAX_RECORDS
MAX_LINE_BYTES = v1.MAX_LINE_BYTES
MAX_FILE_BYTES = v1.MAX_FILE_BYTES
PROFILES = v1.PROFILES
VIEWS = ('retirement-boundary', 'raw-event-exact')
STATE_FIELDS = v1.STATE_FIELDS
_require, _keys, _integer = v1._require, v1._keys, v1._integer


@dataclass(frozen=True)
class Trace:
    header: dict
    initial: dict
    events: tuple[dict, ...]
    instructions: tuple[dict, ...]
    final: dict
    sha256: str


def _header(value):
    _keys(value, ('type', 'schema', 'format', 'engine', 'fixture_sha256', 'case',
                  'clock', 'phase', 'unavailable_fields', 'call_model'), 'Header')
    _require(type(value['schema']) is int and value['schema'] == 2 and
             value['format'] == FORMAT and value['phase'] == PHASE,
             'Unsupported IRQ trace header')
    _require(value['call_model'] in ('aggregate', 'split-irq'), 'Invalid call model')
    # Reuse the existing strict metadata validator without admitting v2 to v1.
    metadata = {k: v for k, v in value.items() if k != 'call_model'}
    metadata.update(schema=1, format=v1.FORMAT, phase='instruction-boundary')
    v1._header(metadata)


def _vector(value):
    _require(value is None or (type(value) is int and value in (0xFFF6, 0xFFF8, 0xFFFA)),
             'Invalid IRQ vector')


def _group(header, pending, row, previous_instruction, ordinal):
    _keys(row, ('type', 'ordinal', 'event_start', 'event_end', 'entry_pc',
                'entry_mpr', 'state', 'irq_count', 'irq_vector'), 'Instruction')
    _integer(row['ordinal'], MAX_RECORDS, 'instruction ordinal', 1)
    _require(row['ordinal'] == ordinal, 'Noncontiguous instruction ordinal')
    _require(bool(pending), 'Instruction has no raw events')
    for key in ('event_start', 'event_end'):
        _integer(row[key], MAX_RECORDS, key, 1)
    _require(row['event_start'] == pending[0]['ordinal'] and
             row['event_end'] == pending[-1]['ordinal'], 'Instruction event span differs')
    _integer(row['entry_pc'], 65535, 'instruction entry PC')
    v1._mpr(row['entry_mpr'], 'instruction entry MPR')
    _require(row['entry_pc'] == previous_instruction['pc'] and
             row['entry_mpr'] == previous_instruction['mpr'], 'Instruction entry context differs')
    v1._state(row['state'], header['unavailable_fields'])
    _require(row['state'] == pending[-1]['state'], 'Instruction final state differs from raw event')
    _integer(row['irq_count'], 1, 'IRQ count')
    _vector(row['irq_vector'])
    kinds = [event['kind'] for event in pending]
    _require(kinds[0] == 'opcode', 'Retirement group must begin with exactly one opcode')
    if header['call_model'] == 'aggregate':
        _require(kinds == ['opcode'], 'Aggregate group must contain one opcode call')
    else:
        tail = kinds[1:]
        if tail and tail[-1] == 'irq-entry':
            tail = tail[:-1]
        _require(all(kind == 'block-continuation' for kind in tail),
                 'Split group must be opcode, continuations, optional single IRQ entry')
    vectors = [event['irq_vector'] for event in pending if event['irq_vector'] is not None]
    _require(len(vectors) <= 1 and row['irq_count'] == len(vectors) and
             row['irq_vector'] == (vectors[0] if vectors else None),
             'Instruction IRQ metadata differs from raw events')


def _load(stream, *, max_records, max_line_bytes, max_file_bytes):
    for value, maximum, label in ((max_records, MAX_RECORDS, 'record bound'),
                                  (max_line_bytes, MAX_LINE_BYTES, 'line bound'),
                                  (max_file_bytes, MAX_FILE_BYTES, 'file bound')):
        _integer(value, maximum, label, 1)
    header = initial = previous = previous_instruction = final = None
    events, instructions, pending = [], [], []
    total = count = 0
    digest = hashlib.sha256()
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
        row = v1._json(raw)
        if header is None:
            _header(row)
            header = row
        elif initial is None:
            _keys(row, ('type', 'state'), 'Initial record')
            _require(row['type'] == 'initial', 'Initial record required')
            v1._state(row['state'], header['unavailable_fields'])
            initial = previous = previous_instruction = row['state']
        elif final is not None:
            raise ValueError('Records after final record')
        elif type(row) is dict and row.get('type') == 'event':
            _keys(row, ('type', 'ordinal', 'kind', 'entry', 'state', 'irq_vector'), 'Event')
            _integer(row['ordinal'], MAX_RECORDS, 'raw-call ordinal', 1)
            _require(row['ordinal'] == len(events) + 1, 'Noncontiguous raw-call ordinal')
            _require(row['kind'] in ('opcode', 'block-continuation', 'irq-entry'), 'Invalid event kind')
            v1._state(row['entry'], header['unavailable_fields'])
            v1._state(row['state'], header['unavailable_fields'])
            _require(row['entry'] == previous, 'Raw event entry state breaks state chain')
            _require(row['state']['ticks'] > previous['ticks'], 'Raw-call master ticks must increase')
            _vector(row['irq_vector'])
            if header['call_model'] == 'aggregate':
                _require(row['kind'] == 'opcode', 'Aggregate call must be an opcode')
            elif row['kind'] == 'irq-entry':
                _require(row['irq_vector'] is not None, 'IRQ entry requires actual vector')
            else:
                _require(row['irq_vector'] is None, 'Split opcode/continuation cannot contain IRQ entry')
            events.append(row)
            pending.append(row)
            previous = row['state']
        elif type(row) is dict and row.get('type') == 'instruction':
            _group(header, pending, row, previous_instruction, len(instructions) + 1)
            instructions.append(row)
            pending = []
            previous_instruction = row['state']
        else:
            _keys(row, ('type', 'executed', 'events', 'stop', 'complete', 'state'), 'Final record')
            _require(row['type'] == 'final' and row['stop'] == 'instruction-limit' and
                     row['complete'] is True, 'Complete instruction-limit final record required')
            for field in ('executed', 'events'):
                _integer(row[field], MAX_RECORDS, 'final ' + field)
            _require(not pending, 'Final record leaves raw events ungrouped')
            _require(row['executed'] == len(instructions) and row['events'] == len(events),
                     'Final retirement/raw-call counts differ')
            v1._state(row['state'], header['unavailable_fields'])
            _require(row['state'] == previous, 'Final state differs from closed event chain')
            final = row
    _require(header is not None and initial is not None and final is not None,
             'Incomplete IRQ trace')
    return Trace(header, initial, tuple(events), tuple(instructions), final, digest.hexdigest())


def load_trace(path: Path, **limits) -> Trace:
    with Path(path).open('rb') as stream:
        return _load(stream, **_limits(limits))


def _limits(values):
    result = dict(max_records=MAX_RECORDS, max_line_bytes=MAX_LINE_BYTES, max_file_bytes=MAX_FILE_BYTES)
    _require(not (set(values) - set(result)), 'Unknown trace bound')
    result.update(values)
    return result


def parse_trace(data: bytes, **limits) -> Trace:
    _require(type(data) is bytes, 'Trace input must be bytes')
    return _load(io.BytesIO(data), **_limits(limits))


def compare_traces(expected: Trace, actual: Trace, *, view='retirement-boundary', profile='exact'):
    _require(isinstance(expected, Trace) and isinstance(actual, Trace), 'Validated IRQ traces required')
    _require(type(view) is str and view in VIEWS, 'Unsupported comparison view')
    _require(type(profile) is str and profile in PROFILES, 'Unsupported comparison profile')
    _require(view != 'raw-event-exact' or profile == 'exact', 'Raw-event-exact requires exact profile')
    elapsed = profile == 'architectural-elapsed-v1'
    fields = [f for f in STATE_FIELDS if profile == 'exact' or f != 'mpr_latch']
    unavailable = set(expected.header['unavailable_fields']) | set(actual.header['unavailable_fields'])
    result = dict(schema=2, format='pce-irq-trace-comparison-2', view=view, profile=profile,
        compatible=True, equal=False, expected_engine=expected.header['engine'], actual_engine=actual.header['engine'],
        expected_trace_sha256=expected.sha256, actual_trace_sha256=actual.sha256,
        fixture_sha256=expected.header['fixture_sha256'], case=expected.header['case'],
        clock=expected.header['clock'], phase=expected.header['phase'],
        expected_call_model=expected.header['call_model'], actual_call_model=actual.header['call_model'],
        clock_comparison_policy='elapsed-from-initial-state' if elapsed else 'raw-master-ticks',
        clock_origins=dict(expected=expected.initial['ticks'], actual=actual.initial['ticks']),
        checked_state_fields=[f for f in fields if f not in unavailable],
        unchecked_state_fields=[dict(field='mpr_latch', reason='Unavailable original latch or explicitly selected architectural profile; no latch parity')]
            if profile != 'exact' or unavailable else [],
        scope='All raw call states and structure' if view == 'raw-event-exact' else
            'Actual post-IRQ retirement states, entry contexts and IRQ count/vector; internal raw call phases are retained but not equated',
        expected_events=len(expected.events), actual_events=len(actual.events),
        expected_instructions=len(expected.instructions), actual_instructions=len(actual.instructions),
        matched_records=0, first_difference=None)

    def difference(ordinal, field, a, b):
        result['first_difference'] = dict(ordinal=ordinal, field=field, expected=a, actual=b)
        return result

    def state_difference(ordinal, label, a, b):
        for field in fields:
            av, bv = a[field], b[field]
            if field == 'ticks' and elapsed:
                ae, be = av - expected.initial['ticks'], bv - actual.initial['ticks']
                if ae != be:
                    difference(ordinal, label + '.ticks', av, bv)
                    result['first_difference'].update(expected_elapsed=ae, actual_elapsed=be)
                    return result
            elif av != bv:
                return difference(ordinal, label + '.' + field, av, bv)
        return None

    for field in ('format', 'schema', 'fixture_sha256', 'case', 'clock', 'phase'):
        if expected.header[field] != actual.header[field]:
            result['compatible'] = False
            return difference(None, 'header.' + field, expected.header[field], actual.header[field])
    if view == 'raw-event-exact' and expected.header['call_model'] != actual.header['call_model']:
        result['compatible'] = False
        return difference(None, 'header.call_model', expected.header['call_model'], actual.header['call_model'])
    if state_difference(0, 'initial', expected.initial, actual.initial):
        return result
    left, right = (expected.events, actual.events) if view == 'raw-event-exact' else (expected.instructions, actual.instructions)
    for ordinal, (a, b) in enumerate(zip(left, right), 1):
        keys = ('kind', 'irq_vector') if view == 'raw-event-exact' else ('entry_pc', 'entry_mpr', 'irq_count', 'irq_vector')
        for field in keys:
            if a[field] != b[field]:
                return difference(ordinal, field, a[field], b[field])
        if view == 'raw-event-exact' and state_difference(ordinal, 'entry', a['entry'], b['entry']):
            return result
        if state_difference(ordinal, 'state', a['state'], b['state']):
            return result
        result['matched_records'] += 1
    if len(left) != len(right):
        return difference(result['matched_records'] + 1, 'record.present', len(left), len(right))
    # Raw view also binds actual retirement grouping, not merely event bytes.
    if view == 'raw-event-exact':
        for ordinal, (a, b) in enumerate(zip(expected.instructions, actual.instructions), 1):
            for field in ('event_start', 'event_end', 'entry_pc', 'entry_mpr', 'irq_count', 'irq_vector'):
                if a[field] != b[field]:
                    return difference(ordinal, 'instruction.' + field, a[field], b[field])
            if state_difference(ordinal, 'instruction.state', a['state'], b['state']):
                return result
        if len(expected.instructions) != len(actual.instructions):
            return difference(None, 'instruction.count', len(expected.instructions), len(actual.instructions))
    result['equal'] = True
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('expected', type=Path)
    parser.add_argument('actual', type=Path)
    parser.add_argument('--view', choices=VIEWS, default='retirement-boundary')
    parser.add_argument('--profile', choices=PROFILES, default='exact')
    parser.add_argument('--out', type=Path, help='Write a NEW comparison report')
    args = parser.parse_args(argv)
    try:
        result = compare_traces(load_trace(args.expected), load_trace(args.actual), view=args.view, profile=args.profile)
        text = json.dumps(result, indent=2, allow_nan=False) + '\n'
        if args.out is not None:
            _require(not args.out.is_symlink(), 'Report path must not be a symbolic link')
            _require(args.out.resolve() not in (args.expected.resolve(), args.actual.resolve()),
                     'Report path must not alias either trace input')
            # Exclusive creation also rejects hard links, existing files and a
            # symlink created between validation and open. Never truncate.
            with args.out.open('x', encoding='utf-8') as stream:
                stream.write(text)
        else:
            print(text, end='')
        return 0 if result['equal'] else 1
    except (ValueError, OSError, RuntimeError) as error:
        # OSError may embed owner paths. Keep expected failures concise and
        # never expose a traceback or write an invalid comparison as a report.
        message = str(error) if isinstance(error, ValueError) else 'Trace file operation failed'
        message = ' '.join(message.split())[:240]
        print('IRQ trace: ' + message, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
