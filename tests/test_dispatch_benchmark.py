"""Independent checks for benchmark comparability and semantic refusal."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.dispatch_benchmark import (argv, benchmark, command, compare,
                                        digest, fingerprint, parse_simulation,
                                        summary)


class DispatchBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base/'fixture').write_bytes(b'authored fixture')
        (self.base/'implementation').write_bytes(b'implementation')
        self.spec = dict(schema=1,workload='authored-loop',
            inputs=[dict(path='fixture',sha256=fingerprint(self.base/'fixture'))],
            implementation=[dict(path='implementation')],
            controls=dict(compiler='clang++',compiler_version='test',flags=['-O3'],
                          configuration='Release',architecture='test'),
            run=dict(command=['synthetic'],warmups=1,samples=3))
        self.semantic = dict(retired=200,ticks=1794,checksum='abcdef')

    def sample(self, seconds=1.0, semantic=None):
        return (seconds+0.1,json.dumps(dict(semantic=self.semantic if semantic is None else semantic,
                                         simulation_seconds=seconds)).encode())

    def receipt(self):
        with patch('scripts.dispatch_benchmark.command',return_value=self.sample()):
            return benchmark(self.spec,self.base,self.base)

    def test_canonical_digest_ignores_key_order(self):
        self.assertEqual(digest(dict(a=1,b=2)),digest(dict(b=2,a=1)))

    def test_medians_are_not_total_elapsed_or_warmups(self):
        with patch('scripts.dispatch_benchmark.command',side_effect=[self.sample(v) for v in (99,4,1,2)]):
            result = benchmark(self.spec,self.base,self.base)
        self.assertEqual(result['simulation']['instrumented_seconds']['samples'],[4,1,2])
        self.assertEqual(result['simulation']['instrumented_seconds']['median'],2)
        self.assertAlmostEqual(result['simulation']['process_wall_seconds']['median'],2.1)
        self.assertEqual(result['semantic'],self.semantic)

    def test_all_samples_including_warmup_must_match_semantics(self):
        with patch('scripts.dispatch_benchmark.command',side_effect=[self.sample(),self.sample(semantic=dict(retired=199))]):
            with self.assertRaisesRegex(ValueError,'Semantic result changed'):
                benchmark(self.spec,self.base,self.base)

    def test_input_mutation_refused_before_command(self):
        (self.base/'fixture').write_bytes(b'changed')
        with patch('scripts.dispatch_benchmark.command') as run:
            with self.assertRaisesRegex(ValueError,'checksum mismatch'):
                benchmark(self.spec,self.base,self.base)
            run.assert_not_called()

    def test_implementation_mutation_during_sample_refused(self):
        def mutate(*args):
            (self.base/'implementation').write_bytes(b'changed')
            return self.sample()
        with patch('scripts.dispatch_benchmark.command',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'changed while benchmarking'):
                benchmark(self.spec,self.base,self.base)

    def test_compare_refuses_any_semantic_or_control_change(self):
        result = self.receipt()
        for key in ('workload','inputs','controls','host','semantic','semantic_sha256'):
            prior = copy.deepcopy(result); prior[key] = 'different'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,key):
                compare(prior,result)
        self.assertEqual(compare(result,result)['instrumented_simulation_ratio_baseline_over_candidate'],1)

    def test_build_comparison_requires_same_declared_scope_and_cache(self):
        result = self.receipt()
        result['build'] = dict(scope='compile_only',cache_state='fresh',process_wall_seconds=summary([2]))
        prior = copy.deepcopy(result)
        prior['build']['process_wall_seconds'] = summary([4])
        self.assertEqual(compare(prior,result)['build_wall_ratio_baseline_over_candidate'],2)
        for key in ('scope','cache_state'):
            changed = copy.deepcopy(prior);changed['build'][key]='different'
            with self.assertRaisesRegex(ValueError,key):compare(changed,result)

    def test_repeated_build_requires_prepare(self):
        self.spec['build'] = dict(command=['compiler'],scope='compile_only',cache_state='fresh',samples=2)
        with self.assertRaisesRegex(ValueError,'prepare command'):
            benchmark(self.spec,self.base,self.base)

    def test_build_and_simulation_report_separate_durations(self):
        self.spec['build'] = dict(command=['compiler'],scope='total_build',cache_state='fresh',samples=1)
        with patch('scripts.dispatch_benchmark.command',side_effect=[(5,b'build log')]+[self.sample()]*4):
            result = benchmark(self.spec,self.base,self.base)
        self.assertEqual(result['build']['process_wall_seconds']['median'],5)
        self.assertEqual(result['simulation']['instrumented_seconds']['median'],1)

    def test_invalid_sample_and_command_shapes(self):
        for value in ('compiler',[],[''],['compiler',3]):
            with self.subTest(value=value),self.assertRaises(ValueError):argv(value)
        for sample in (dict(semantic={},simulation_seconds=1),
                       dict(semantic=dict(a=1),simulation_seconds=0),
                       dict(semantic=dict(a=1),simulation_seconds=float('inf')),
                       dict(semantic=dict(a=float('nan')),simulation_seconds=1),
                       dict(semantic=dict(a=1),simulation_seconds=True),
                       dict(semantic=dict(a=1),simulation_seconds=1,ignored=1)):
            with self.subTest(sample=sample),self.assertRaises(ValueError):
                parse_simulation(json.dumps(sample))

    def test_missing_controls_or_noninteger_samples_refused(self):
        for key in self.spec['controls']:
            changed = copy.deepcopy(self.spec);del changed['controls'][key]
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,key):
                benchmark(changed,self.base,self.base)
        self.spec['run']['samples'] = True
        with self.assertRaises(ValueError):benchmark(self.spec,self.base,self.base)

    def test_command_runs_argv_without_shell_and_refuses_failed_exit(self):
        elapsed, raw = command([sys.executable,'-c','print("authored")'],self.base,self.base,5)
        self.assertGreater(elapsed,0)
        self.assertEqual(raw.strip(),b'authored')
        with self.assertRaisesRegex(RuntimeError,'exited 3'):
            command([sys.executable,'-c','raise SystemExit(3)'],self.base,self.base,5)

    def test_command_timeout_is_bounded(self):
        with self.assertRaisesRegex(RuntimeError,'timeout'):
            command([sys.executable,'-c','import time;time.sleep(5)'],self.base,self.base,0.03)

    def test_oversized_command_output_is_refused(self):
        with self.assertRaisesRegex(RuntimeError,'output limit'):
            command([sys.executable,'-c','import sys;sys.stdout.write("x"*1100000)'],self.base,self.base,5)


if __name__ == '__main__':
    unittest.main()
