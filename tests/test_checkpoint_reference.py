"""Verifier unit controls use authored reports, never count as execution proof."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pcerecomp.project import ABI
from scripts import checkpoint_reference as reference
from tests.generate_adpcm_irq_fixture import authored_fixture, make_program, literals


def admission(case):
    _, program, _, marker, _, mapping = make_program(case)
    _, _, sources = literals(case, program, marker, mapping)
    counts = reference.expected_sources(case)
    records = {reference.identity(r): r for r in sources}
    reports = {}; captures = {}; digests = {}
    for tier in ('native', 'interpreter'):
        digests[tier] = ('a' if tier == 'native' else 'b') * 64
        reports[tier] = {}; captures[tier] = {}
        for mode in ('create', 'resume'):
            reports[tier][mode] = dict(case=case['id'], tier=tier,
                origin_ticks=sum(t for t, _ in reference.oracle.primer_clocks(case, False)),
                imported_native=case['primer_steps'] if tier == 'native' else 0,
                imported_interpreted=0 if tier == 'native' else case['primer_steps'],
                checkpoint_sha256=digests[tier], initial={k:copy.deepcopy(case['initial'][k]) for k in ('values','wram_sha256','irq_vector')},
                rows=[{k:copy.deepcopy(r[k]) for k in ('values','wram_sha256','irq_vector')} for r in case['expected']], window_native=48 if tier == 'native' else 0,
                window_interpreted=0 if tier == 'native' else 48, final_state_sha256='c'*64)
            observations = [dict(pc=records[k]['pc'], mpr=list(records[k]['mpr']),
                physical=list(records[k]['physical']), data=list(records[k]['data']),
                native_hits=v if tier == 'native' else 0, interpreted_hits=0 if tier == 'native' else v)
                for k, v in sorted(counts.items())]
            captures[tier][mode] = dict(schema=1, runtime_abi=ABI, capacity=4096,
                dropped_instructions=0, unreadable_instructions=0, retired_instructions=48,
                complete=True, observations=observations)
            if mode == 'resume':
                r = reports[tier][mode]
                captures[tier][mode]['checkpoint_origin'] = dict(sha256=digests[tier], ticks=r['origin_ticks'],
                    frame=0, native_steps=r['imported_native'], interpreter_steps=r['imported_interpreted'])
    return dict(case=case, reports=reports, captures=captures, checkpoint_sha256=digests, abi=ABI)


class CheckpointReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases, _, _ = authored_fixture()

    def test_all_48_authored_window_admissions(self):
        for case in self.cases:
            result = reference.qualify(**admission(case))
            self.assertEqual((result['restored_native_window'], result['restored_interpreted_window']), (48, 48))

    def test_original_oracle_requires_all_raw_source_binary_and_trace_bindings(self):
        # These small authored files exercise admission integrity only; they are
        # not represented as an executed emulator or native proof.
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'authored-record.txt'
            path.write_bytes(b'authored fixture\n')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            report = dict(bindings={group:{str(path):digest} for group in reference.GEAR_BINDING_GROUPS},
                          preservation={group:True for group in reference.GEAR_BINDING_GROUPS})
            self.assertEqual(reference.verify_gear_bindings(report), report['bindings'])
            for group in reference.GEAR_BINDING_GROUPS:
                for mutation in ('missing', 'empty', 'digest', 'unpreserved', 'bool', 'relative'):
                    bad = copy.deepcopy(report)
                    if mutation == 'missing':
                        del bad['bindings'][group]
                    elif mutation == 'empty':
                        bad['bindings'][group] = {}
                    elif mutation == 'digest':
                        bad['bindings'][group][str(path)] = '0'*64
                    elif mutation == 'unpreserved':
                        bad['preservation'][group] = False
                    elif mutation == 'bool':
                        bad['preservation'][group] = 1
                    elif mutation == 'relative':
                        bad['bindings'][group] = {'relative-record.txt':digest}
                    with self.subTest(group=group, mutation=mutation), self.assertRaises(ValueError):
                        reference.verify_gear_bindings(bad)
            path.write_bytes(b'changed original\n')
            with self.assertRaises(ValueError):
                reference.verify_gear_bindings(report)

    def test_evidence_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'record.json'
            for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
                path.write_text(text, encoding='utf8')
                with self.assertRaises(ValueError):
                    reference.evidence_json(path)
            path.write_text(json.dumps({'authored':True}), encoding='utf8')
            self.assertEqual(reference.evidence_json(path), {'authored':True})

    def test_imported_prefix_is_never_newly_executed_window_work(self):
        original = admission(self.cases[0])
        for tier in ('native', 'interpreter'):
            for mode in ('create', 'resume'):
                field = 'window_native' if tier == 'native' else 'window_interpreted'
                actual = copy.deepcopy(original); actual['reports'][tier][mode][field] += actual['case']['primer_steps']
                with self.assertRaises(ValueError):
                    reference.qualify(**actual)
                actual = copy.deepcopy(original); actual['captures'][tier][mode]['retired_instructions'] += actual['case']['primer_steps']
                with self.assertRaises(ValueError):
                    reference.qualify(**actual)

    def test_actual_state_all_36_columns_and_whole_wram_are_checked(self):
        original = admission(self.cases[0])
        for column in range(36):
            actual = copy.deepcopy(original); actual['reports']['native']['resume']['rows'][0]['values'][column] ^= 1
            with self.subTest(column=column), self.assertRaises(ValueError):
                reference.qualify(**actual)
        actual = copy.deepcopy(original); actual['reports']['native']['resume']['rows'][0]['wram_sha256'] = '0'*64
        with self.assertRaises(ValueError):
            reference.qualify(**actual)

    def test_full_source_identity_and_per_key_counts_are_checked(self):
        original = admission(self.cases[0])
        for field in ('pc', 'mpr', 'physical', 'data', 'native_hits', 'interpreted_hits'):
            actual = copy.deepcopy(original); row = actual['captures']['native']['resume']['observations'][0]
            if isinstance(row[field], list):
                row[field][0] ^= 1
            else:
                row[field] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                reference.qualify(**actual)

    def test_exact_state_digest_profiles_and_strict_fields(self):
        original = admission(self.cases[0])
        for field in ('checkpoint_sha256', 'final_state_sha256', 'tier', 'origin_ticks', 'imported_native'):
            actual = copy.deepcopy(original); row = actual['reports']['native']['resume']
            row[field] = ('0'*64 if field.endswith('sha256') else 'bad' if field == 'tier' else row[field]+1)
            with self.subTest(field=field), self.assertRaises(ValueError):
                reference.qualify(**actual)
        actual = copy.deepcopy(original); actual['reports']['native']['resume']['extra'] = 0
        with self.assertRaises(ValueError):
            reference.qualify(**actual)

    def test_resume_capture_requires_bound_origin(self):
        original = admission(self.cases[0])
        for key in ('sha256', 'ticks', 'frame', 'native_steps', 'interpreter_steps'):
            actual = copy.deepcopy(original); origin = actual['captures']['native']['resume']['checkpoint_origin']
            origin[key] = '0'*64 if key == 'sha256' else origin[key]+1
            with self.subTest(key=key), self.assertRaises(ValueError):
                reference.qualify(**actual)
        actual = copy.deepcopy(original); del actual['captures']['native']['resume']['checkpoint_origin']
        with self.assertRaises(ValueError):
            reference.qualify(**actual)
        actual = copy.deepcopy(original); actual['reports']['native']['resume']['window_native'] = True
        with self.assertRaises(ValueError):
            reference.qualify(**actual)


if __name__ == '__main__':
    unittest.main()
