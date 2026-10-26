"""Authored raw-call chains, retirement attribution and strict rejection controls."""
import copy
import hashlib
import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest

from pcerecomp import irq_trace as trace
from pcerecomp import reference_trace as v1


def state(pc=0xE100, ticks=0, **values):
    result = dict(pc=pc, a=4, x=0, y=0, sp=255, p=4,
        mpr=[0,248,255,0,0,0,0,0], mpr_latch=255,
        physical_pc=pc & 8191, clock_divisor=3, ticks=ticks, wram_sha256='a'*64)
    result.update(values)
    return result


def records(model='split-irq', *, block=False):
    initial = state()
    post = state(0xE101, 6, p=0)
    interrupted = state(0xE200, 30, p=4, sp=252, wram_sha256='b'*64)
    header = dict(type='header', schema=2, format=trace.FORMAT, phase=trace.PHASE,
        engine=dict(name='authored', revision='1'*40, source_sha256='2'*64, binary_sha256='3'*64),
        fixture_sha256='4'*64, case='authored-irq', clock='master-ticks',
        unavailable_fields=[], call_model=model)
    events = []
    def event(kind, before, after, vector=None):
        events.append(dict(type='event', ordinal=len(events)+1, kind=kind,
            entry=copy.deepcopy(before), state=copy.deepcopy(after), irq_vector=vector))
    if model == 'aggregate':
        event('opcode', initial, interrupted, 0xFFFA)
    else:
        event('opcode', initial, post)
        if block:
            resumed = state(0xE101, 12, p=0, wram_sha256='c'*64)
            event('block-continuation', post, resumed)
            post = resumed
        event('irq-entry', post, interrupted, 0xFFFA)
    instruction = dict(type='instruction', ordinal=1, event_start=1, event_end=len(events),
        entry_pc=initial['pc'], entry_mpr=initial['mpr'][:], state=copy.deepcopy(interrupted),
        irq_count=1, irq_vector=0xFFFA)
    final = dict(type='final', executed=1, events=len(events), stop='instruction-limit',
        complete=True, state=copy.deepcopy(interrupted))
    return [header, dict(type='initial', state=initial), *events, instruction, final]


def encode(rows):
    return b''.join(json.dumps(row, separators=(',', ':')).encode()+b'\n' for row in rows)


def parsed(rows=None):
    return trace.parse_trace(encode(records() if rows is None else rows))


class IrqTraceTests(unittest.TestCase):
    def cli(self, arguments):
        with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as errors:
            code = trace.main([str(arg) for arg in arguments])
        return code, output.getvalue(), errors.getvalue()

    def reject(self, rows):
        with self.assertRaises(ValueError):
            parsed(rows)

    def test_split_events_preserve_raw_intermediate_and_retirement_counts(self):
        raw = encode(records(block=True))
        value = trace.parse_trace(raw)
        self.assertEqual(value.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(value.events), 3)
        self.assertEqual(value.final['executed'], 1)
        self.assertEqual(value.events[0]['state']['pc'], 0xE101)
        self.assertEqual(value.events[-1]['state']['pc'], 0xE200)
        self.assertEqual(value.events[1]['kind'], 'block-continuation')

    def test_aggregate_and_split_match_only_explicit_boundary_scope(self):
        a, b = parsed(records('aggregate')), parsed()
        result = trace.compare_traces(a, b)
        self.assertTrue(result['equal'])
        self.assertEqual(result['expected_events'], 1)
        self.assertEqual(result['actual_events'], 2)
        self.assertIn('not equated', result['scope'])
        result = trace.compare_traces(a, b, view='raw-event-exact')
        self.assertFalse(result['compatible'])
        self.assertEqual(result['first_difference']['field'], 'header.call_model')

    def test_raw_event_exact_detects_hidden_intermediate_divergence(self):
        a, b = records(), records()
        b[2]['state']['a'] = 91
        b[3]['entry']['a'] = 91
        self.assertTrue(trace.compare_traces(parsed(a), parsed(b))['equal'])
        result = trace.compare_traces(parsed(a), parsed(b), view='raw-event-exact')
        self.assertEqual(result['first_difference']['field'], 'state.a')

    def test_raw_exact_and_engine_identities(self):
        a, b = records(), records()
        b[0]['engine']['name'] = 'independent'
        result = trace.compare_traces(parsed(a), parsed(b), view='raw-event-exact')
        self.assertTrue(result['equal'])
        self.assertEqual(result['actual_engine']['name'], 'independent')

    def test_boundary_comparison_checks_actual_irq_vector(self):
        rows = records()
        rows[3]['irq_vector'] = rows[-2]['irq_vector'] = 0xFFF8
        result = trace.compare_traces(parsed(), parsed(rows))
        self.assertEqual(result['first_difference']['field'], 'irq_vector')

    def test_header_scope_compatibility_is_required(self):
        for field, value in [('fixture_sha256', '5'*64), ('case', 'different-case')]:
            rows = records(); rows[0][field] = value
            result = trace.compare_traces(parsed(), parsed(rows))
            self.assertFalse(result['compatible'])
            self.assertEqual(result['first_difference']['field'], 'header.' + field)

    def test_unavailable_latch_metadata_requires_null_values(self):
        rows = records(); rows[0]['unavailable_fields'] = ['mpr_latch']; self.reject(rows)
        rows = records(); rows[1]['state']['mpr_latch'] = None; self.reject(rows)

    def test_raw_records_cannot_gain_or_lose_keys(self):
        for index in range(len(records())):
            for action in ('missing', 'extra'):
                rows = records()
                if action == 'missing': rows[index].pop(next(iter(rows[index])))
                else: rows[index]['extra'] = 0
                with self.subTest(index=index, action=action): self.reject(rows)

    def test_all_boundary_architectural_fields_are_checked(self):
        for field in trace.STATE_FIELDS:
            rows = records('aggregate')
            changed = copy.deepcopy(rows[-1]['state'])
            if field == 'mpr':
                changed['mpr'][0] = 9
            elif field == 'physical_pc':
                changed['mpr'][7] = 1
                changed[field] += 8192
            elif field == 'clock_divisor': changed[field] = 12
            elif field == 'wram_sha256': changed[field] = 'f'*64
            elif field == 'pc': changed['pc'] += 1; changed['physical_pc'] += 1
            elif field in ('sp', 'mpr_latch'): changed[field] ^= 1
            else: changed[field] += 1
            rows[2]['state'] = copy.deepcopy(changed)
            rows[-2]['state'] = copy.deepcopy(changed)
            rows[-1]['state'] = copy.deepcopy(changed)
            with self.subTest(field=field):
                self.assertFalse(trace.compare_traces(parsed(records('aggregate')), parsed(rows))['equal'])

    def test_elapsed_profile_retains_raw_ticks_and_checks_every_delta(self):
        rows = records()
        for row in rows[1:]:
            for key in ('entry', 'state'):
                if key in row: row[key]['ticks'] += 900
        value = parsed(rows)
        result = trace.compare_traces(parsed(), value, profile='architectural-elapsed-v1')
        self.assertTrue(result['equal'])
        self.assertEqual(value.initial['ticks'], 900)
        self.assertEqual(result['clock_origins'], dict(expected=0, actual=900))
        for row in (rows[3], rows[4], rows[5]): row['state']['ticks'] += 3
        result = trace.compare_traces(parsed(), parsed(rows), profile='architectural-elapsed-v1')
        self.assertEqual(result['first_difference']['expected_elapsed'], 30)
        self.assertEqual(result['first_difference']['actual_elapsed'], 33)

    def test_optional_latch_only_and_no_status_projection(self):
        rows = records()
        rows[0]['unavailable_fields'] = ['mpr_latch']
        for row in rows[1:]:
            for key in ('entry', 'state'):
                if key in row: row[key]['mpr_latch'] = None
        self.assertTrue(trace.compare_traces(parsed(), parsed(rows), profile='architectural-v1')['equal'])
        for row in (rows[3], rows[4], rows[5]): row['state']['p'] ^= 16
        self.assertEqual(trace.compare_traces(parsed(), parsed(rows), profile='architectural-v1')['first_difference']['field'], 'state.p')

    def test_v1_remains_incompatible(self):
        with self.assertRaises(ValueError): v1.parse_trace(encode(records()))
        rows = records(); rows[0]['schema'] = 1; self.reject(rows)

    def test_header_exact_fields_types_and_availability(self):
        for field, value in [('schema', True), ('phase', 'instruction-boundary'),
                              ('call_model', 'guessed'), ('call_model', []),
                              ('unavailable_fields', ['ticks']), ('fixture_sha256', 'z'*64)]:
            rows = records(); rows[0][field] = value
            with self.subTest(field=field): self.reject(rows)
        rows = records(); rows[0]['unexpected'] = 1; self.reject(rows)

    def test_no_duplicate_json_nonfinite_utf8_or_trailing_records(self):
        raw = encode(records())
        for bad in [raw.replace(b'"schema":2', b'"schema":2,"schema":2'),
                    raw.replace(b'"ticks":0', b'"ticks":NaN'),
                    raw+b'{}\n', b'\xff\n', b'[]\n']:
            with self.subTest(bad=bad[:20]), self.assertRaises(ValueError): trace.parse_trace(bad)

    def test_state_chain_checks_all_raw_fields(self):
        for field in trace.STATE_FIELDS:
            rows = records()
            entry = rows[3]['entry']
            if field == 'mpr': entry[field][0] ^= 1
            elif field == 'wram_sha256': entry[field] = 'c'*64
            elif field == 'clock_divisor': entry[field] = 12
            else: entry[field] += 1
            with self.subTest(field=field): self.reject(rows)

    def test_event_ordinals_strict_and_contiguous(self):
        for ordinal in [0, 1, 3, True, 2.0]:
            rows = records(); rows[3]['ordinal'] = ordinal; self.reject(rows)

    def test_event_ticks_strictly_increasing(self):
        for ticks in [0, -1, True, 2**64]:
            rows = records(); rows[2]['state']['ticks'] = ticks; self.reject(rows)

    def test_instruction_ordinals_and_spans_strict(self):
        for field, value in [('ordinal', 2), ('ordinal', True), ('event_start', 0),
                              ('event_start', 2), ('event_end', 1), ('event_end', True)]:
            rows = records(); rows[-2][field] = value; self.reject(rows)

    def test_instruction_entry_and_final_state_must_match_raw(self):
        for field in ['entry_pc', 'entry_mpr', 'state']:
            rows = records()
            if field == 'entry_pc': rows[-2][field] += 1
            elif field == 'entry_mpr': rows[-2][field][0] ^= 1
            else: rows[-2][field]['p'] ^= 1
            self.reject(rows)

    def test_irq_vector_count_and_split_metadata_rejections(self):
        for index, field, value in [(2, 'irq_vector', 0xFFFA), (3, 'irq_vector', None),
                (3, 'irq_vector', 0xFFFC), (3, 'irq_vector', True),
                (-2, 'irq_count', 0), (-2, 'irq_count', True),
                (-2, 'irq_vector', 0xFFF8), (-2, 'irq_vector', None)]:
            rows = records(); rows[index][field] = value; self.reject(rows)

    def test_aggregate_forbids_split_events(self):
        rows = records(); rows[0]['call_model'] = 'aggregate'; self.reject(rows)
        rows = records('aggregate'); rows[2]['kind'] = 'irq-entry'; self.reject(rows)

    def test_irq_entry_and_continuation_never_begin_retirement(self):
        for kind in ('irq-entry', 'block-continuation'):
            rows = records(); rows[2]['kind'] = kind
            if kind == 'irq-entry': rows[2]['irq_vector'] = 0xFFF8
            self.reject(rows)

    def test_second_opcode_or_post_irq_continuation_rejected(self):
        rows = records(); rows[3]['kind'] = 'opcode'; rows[3]['irq_vector'] = None; self.reject(rows)
        rows = records(block=True)
        rows[3]['kind'] = 'irq-entry'; rows[3]['irq_vector'] = 0xFFFA
        rows[4]['kind'] = 'block-continuation'; rows[4]['irq_vector'] = None
        self.reject(rows)

    def test_ungrouped_events_cannot_close(self):
        rows = records(); rows.pop(-2); self.reject(rows)

    def test_empty_group_cannot_retire(self):
        rows = records(); rows[2:4] = []; self.reject(rows)

    def test_final_counts_state_and_stop_exact(self):
        for field, value in [('executed', 2), ('events', 1), ('events', True),
                              ('complete', 1), ('stop', 'budget')]:
            rows = records(); rows[-1][field] = value; self.reject(rows)
        rows = records(); rows[-1]['state']['p'] ^= 1; self.reject(rows)

    def test_incomplete_trace_rejected_at_every_prefix(self):
        rows = records()
        for end in range(len(rows)):
            with self.assertRaises(ValueError): trace.parse_trace(encode(rows[:end]))

    def test_record_line_file_and_argument_bounds(self):
        raw = encode(records())
        for limits in [dict(max_records=5), dict(max_line_bytes=20), dict(max_file_bytes=len(raw)-1),
                       dict(max_records=True), dict(max_records=100001), dict(extra=1)]:
            with self.subTest(limits=limits), self.assertRaises(ValueError): trace.parse_trace(raw, **limits)

    def test_multiple_groups_close_without_phantom_retirement(self):
        rows = records()
        after = copy.deepcopy(rows[-1]['state']); after.update(pc=0xE201, physical_pc=0x201, ticks=36)
        event = dict(type='event', ordinal=3, kind='opcode', entry=copy.deepcopy(rows[-1]['state']), state=after, irq_vector=None)
        group = dict(type='instruction', ordinal=2, event_start=3, event_end=3, entry_pc=0xE200,
            entry_mpr=after['mpr'][:], state=copy.deepcopy(after), irq_count=0, irq_vector=None)
        rows[-1:-1] = [event, group]
        rows[-1].update(executed=2, events=3, state=copy.deepcopy(after))
        value = parsed(rows)
        self.assertEqual(len(value.instructions), 2)
        self.assertTrue(trace.compare_traces(value, value, view='raw-event-exact')['equal'])
        result = trace.compare_traces(parsed(), value)
        self.assertEqual(result['first_difference']['field'], 'record.present')

    def test_load_cli_and_profile_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'trace.jsonl'; path.write_bytes(encode(records()))
            self.assertEqual(trace.load_trace(path), parsed())
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(trace.main([str(path), str(path)]), 0)
            self.assertTrue(json.loads(output.getvalue())['equal'])
        for kwargs in [dict(view='unknown'), dict(profile='unknown'),
                       dict(view='raw-event-exact', profile='architectural-v1')]:
            with self.assertRaises(ValueError): trace.compare_traces(parsed(), parsed(), **kwargs)


    def test_cli_equal_report_is_exclusive_and_existing_file_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); source = base/'input.jsonl'; report = base/'report.json'
            raw = encode(records()); source.write_bytes(raw)
            code, output, errors = self.cli([source, source, '--out', report])
            self.assertEqual((code, output, errors), (0, '', ''))
            self.assertTrue(json.loads(report.read_text())['equal'])
            saved = report.read_bytes()
            code, output, errors = self.cli([source, source, '--out', report])
            self.assertEqual((code, output), (2, ''))
            self.assertIn('Trace file operation failed', errors)
            self.assertNotIn(directory, errors)
            self.assertEqual(report.read_bytes(), saved)
            self.assertEqual(source.read_bytes(), raw)

    def test_cli_difference_exits_one_and_report_retains_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); left = base/'left'; right = base/'right'; report = base/'report'
            rows = records(); rows[3]['irq_vector'] = rows[-2]['irq_vector'] = 0xFFF8
            left.write_bytes(encode(records())); right.write_bytes(encode(rows))
            code, output, errors = self.cli([left, right])
            self.assertEqual((code, errors), (1, ''))
            self.assertEqual(json.loads(output)['first_difference']['field'], 'irq_vector')
            code, output, errors = self.cli([left, right, '--out', report])
            self.assertEqual((code, output, errors), (1, '', ''))
            self.assertFalse(json.loads(report.read_text())['equal'])

    def test_cli_input_alias_rejected_without_modifying_either_input(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); left = base/'left'; right = base/'right'
            raw = encode(records()); left.write_bytes(raw); right.write_bytes(raw)
            for output_path in (left, right, base/'.'/'left'):
                code, output, errors = self.cli([left, right, '--out', output_path])
                self.assertEqual((code, output), (2, ''))
                self.assertIn('alias', errors)
                self.assertEqual(left.read_bytes(), raw)
                self.assertEqual(right.read_bytes(), raw)

    def test_cli_existing_hard_link_and_directory_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); source = base/'input'; alias = base/'hard-link'
            raw = encode(records()); source.write_bytes(raw); os.link(source, alias)
            for output_path in (alias, base):
                code, output, errors = self.cli([source, source, '--out', output_path])
                self.assertEqual((code, output), (2, ''))
                self.assertNotIn('Traceback', errors)
                self.assertEqual(source.read_bytes(), raw)
                self.assertEqual(alias.read_bytes(), raw)

    def test_cli_symbolic_links_preserve_existing_and_missing_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); source = base/'input'; target = base/'missing'; link = base/'link'
            raw = encode(records()); source.write_bytes(raw)
            try: link.symlink_to(target)
            except OSError:
                # Windows may not grant symlink creation. Other exclusive-file
                # controls remain exercised rather than skipping this test.
                from unittest.mock import patch
                with patch.object(Path, 'is_symlink', return_value=True):
                    code, output, errors = self.cli([source, source, '--out', link])
                self.assertEqual((code, output), (2, ''))
                self.assertIn('symbolic link', errors)
                self.assertFalse(target.exists()); self.assertFalse(link.exists())
                return
            for present in (False, True):
                if present: target.write_bytes(b'preserve target')
                code, output, errors = self.cli([source, source, '--out', link])
                self.assertEqual((code, output), (2, ''))
                self.assertIn('symbolic link', errors)
                self.assertTrue(link.is_symlink())
                if present: self.assertEqual(target.read_bytes(), b'preserve target')
                else: self.assertFalse(target.exists())

    def test_cli_malformed_missing_file_and_refused_profile_exit_two(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); source = base/'input'; broken = base/'broken'; report = base/'report'
            source.write_bytes(encode(records())); broken.write_bytes(b'{bad json\n')
            for arguments in ([source, broken, '--out', report], [source, base/'missing', '--out', report],
                    [source, source, '--view', 'raw-event-exact', '--profile', 'architectural-v1', '--out', report],
                    [source, source, '--out', base/'missing-parent'/'report']):
                code, output, errors = self.cli(arguments)
                self.assertEqual((code, output), (2, ''))
                self.assertTrue(errors.startswith('IRQ trace: '))
                self.assertNotIn('Traceback', errors)
                self.assertNotIn(directory, errors)
                self.assertFalse(report.exists())


if __name__ == '__main__':
    unittest.main()
