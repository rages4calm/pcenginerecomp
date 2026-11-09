"""Authored history-to-native emission and public CLI contracts."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp.abi import ABI
from pcerecomp.cli import main
from pcerecomp.emitter import emit_history, emit_observation_profile
from pcerecomp.isa import decode
from pcerecomp.observations import compose_observation_profile


MPR = [255, 248, 128, 129, 130, 131, 132, 0]


def observation(pc=0x4000, data=(0xA9, 42), *, mpr=None, native=0, interpreted=1):
    mapping = MPR[:] if mpr is None else list(mpr)
    instruction = decode(lambda address: data[(address-pc) & 65535], pc, tuple(mapping))
    return dict(pc=pc, mpr=mapping, physical=list(instruction.physical), data=list(data),
                native_hits=native, interpreted_hits=interpreted)


def capture(items, abi=18, origin=None):
    result = dict(schema=1, runtime_abi=abi, capacity=65536, complete=True,
                  dropped_instructions=0, unreadable_instructions=0,
                  retired_instructions=sum(row['native_hits']+row['interpreted_hits'] for row in items),
                  observations=items)
    if origin is not None:
        result['checkpoint_origin'] = origin
    return result


class HistoryEmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs = []

    def write(self, value):
        path = self.root/f'capture-{len(self.inputs)}.json'
        path.write_text(json.dumps(value), encoding='utf-8', newline='\n')
        self.inputs.append(path)
        return path

    def history(self, inputs=None, **options):
        from pcerecomp.history import compose_history
        if inputs is None:
            inputs = [self.write(capture([observation()]))]
        return compose_history(inputs, self.root/'history', **options)

    def invoke(self, *arguments):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = main(list(map(str, arguments)))
        return code, output.getvalue(), error.getvalue()

    def sources(self, folder):
        return {path.name: path.read_bytes() for path in folder.iterdir()
                if path.suffix in ('.cpp', '.hpp')}

    def test_history_retains_mixed_provenance_and_emits_translated_operations(self):
        origin = dict(sha256='a'*64, ticks=100, frame=2, native_steps=20, interpreter_steps=5)
        first = self.write(capture([observation(interpreted=3)], 18))
        second = self.write(capture([observation(0x4100, (0xA2, 7), native=2, interpreted=0)], 26, origin))
        original = {path: path.read_bytes() for path in (first, second)}
        history = self.history([first, second])
        output = self.root/'native'
        manifest = emit_history(history.index_path, output, partition_layout='stable', native_span=True)
        self.assertEqual(manifest['runtime_abi'], ABI)
        self.assertEqual(manifest['native_instructions_emitted'], 2)
        self.assertFalse(manifest['execution_evidence'])
        self.assertEqual(manifest['observation_history_sha256'], history.index_sha256)
        self.assertEqual(manifest['observation_history_format'], 'pce-observation-history-1')
        self.assertEqual(manifest['observation_history_schema'], 1)
        self.assertEqual(sorted(item['runtime_abi'] for item in manifest['observation_inputs']), [18, 26])
        self.assertEqual(next(item for item in manifest['observation_inputs'] if item['runtime_abi']==26)['checkpoint_origin'], origin)
        self.assertEqual(manifest['historical_totals']['native_hits'], 2)
        self.assertEqual(manifest['historical_totals']['interpreted_hits'], 3)
        for key in ('code_capture_sha256', 'capture_runtime_abi', 'observation_profile_sha256',
                    'capture_checkpoint_origin', 'capture_execution_policy'):
            self.assertNotIn(key, manifest)
        source = b'\n'.join(self.sources(output).values()).decode()
        self.assertNotIn('interpret_step', source)
        self.assertNotIn('interpret_block', source)
        self.assertIn('bus.retire', source)
        self.assertIn('s.a', source)
        self.assertIn('s.x', source)
        self.assertEqual({path: path.read_bytes() for path in original}, original)

    def test_same_identity_input_has_identical_native_sources_across_transports(self):
        variant = MPR[:];variant[7] ^= 1
        one = self.write(capture([observation(), observation(data=(0xA9, 43)),
                                  observation(0x41FF, (0xAD, 1, 2), mpr=variant)]))
        profile = compose_observation_profile([one])
        history = self.history([one])
        for options in ({}, {'single_unit': True}, {'partition_layout': 'stable'},
                        {'partition_layout': 'stable', 'native_span': True}):
            with self.subTest(options=options):
                identifier = len(list(self.root.glob('inline-*')))
                inline, external = self.root/f'inline-{identifier}', self.root/f'external-{identifier}'
                old = emit_observation_profile(profile, inline, **options)
                new = emit_history(history.index_path, external, **options)
                self.assertEqual(self.sources(inline), self.sources(external))
                for key in ('native_instructions_emitted', 'translated_body_count', 'native_contexts',
                            'excluded_observations', 'unsupported_observations'):
                    self.assertEqual(old[key], new[key])

    def test_additive_history_keeps_original_totals_and_selected_contributions(self):
        old = self.write(capture([observation(interpreted=3)], 18))
        new = self.write(capture([observation(interpreted=5),
                                  observation(0x4100, (0xA9, 43), interpreted=2)], 26))
        history = self.history([new], baseline_inputs=[old])
        manifest = emit_history(history.index_path, self.root/'native')
        self.assertEqual(manifest['historical_totals']['interpreted_hits'], 10)
        self.assertEqual(manifest['selected_historical_totals']['interpreted_hits'], 5)
        self.assertEqual(len(manifest['observation_inputs']), 2)
        self.assertEqual(len(manifest['selection_stages']), 2)
        self.assertEqual(manifest['native_instructions_emitted'], 2)

    def test_exclusions_inspect_every_fetch_byte_and_keep_unaffected_units_stable(self):
        first = self.write(capture([observation(0x40FF, (0xA9, 42)),
                                    observation(0x4200, (0xE8,))]))
        history = self.history([first])
        complete = self.root/'complete'
        all_rows = emit_history(history.index_path, complete, partition_layout='stable')
        excluded = self.root/'excluded'
        subset = emit_history(history.index_path, excluded, partition_layout='stable',
                              exclude_ranges=((0x100100, 1),))
        self.assertEqual(all_rows['native_instructions_emitted'], 2)
        self.assertEqual(subset['native_instructions_emitted'], 1)
        self.assertEqual(subset['excluded_observations'], 1)
        shared = self.sources(complete).keys() & self.sources(excluded).keys()
        part = [name for name in shared if name.endswith('_p4200.cpp')]
        self.assertEqual(len(part), 1)
        self.assertEqual(self.sources(complete)[part[0]], self.sources(excluded)[part[0]])

    def test_admission_happens_once_and_graph_is_rebound_before_manifest(self):
        from pcerecomp import history as module
        admitted = self.history()
        with patch.object(module, 'load_history', wraps=module.load_history) as load:
            emit_history(admitted.index_path, self.root/'native')
        load.assert_called_once_with(admitted.index_path)

    def test_blob_mutation_during_emission_prevents_module_manifest_publication(self):
        from pcerecomp import emitter
        admitted = self.history()
        blob = next(path for path in (admitted.index_path.parent/'captures').iterdir())
        original_emit = emitter._emit_observations
        def changed(*args, **kwargs):
            blob.write_bytes(blob.read_bytes()+b' ')
            return original_emit(*args, **kwargs)
        output = self.root/'partial'
        with patch.object(emitter, '_emit_observations', side_effect=changed):
            with self.assertRaises(ValueError):
                emit_history(admitted.index_path, output)
        self.assertFalse((output/'module.json').exists())

    def test_output_inside_history_and_existing_destination_refuse_without_changes(self):
        admitted = self.history()
        before = {path.relative_to(admitted.index_path.parent): path.read_bytes()
                  for path in admitted.index_path.parent.rglob('*') if path.is_file()}
        with self.assertRaisesRegex(ValueError, 'outside'):
            emit_history(admitted.index_path, admitted.index_path.parent/'native')
        self.assertEqual({path.relative_to(admitted.index_path.parent): path.read_bytes()
                          for path in admitted.index_path.parent.rglob('*') if path.is_file()}, before)
        output = self.root/'existing';output.mkdir();sentinel=output/'keep';sentinel.write_bytes(b'keep')
        with self.assertRaises(ValueError):
            emit_history(admitted.index_path, output)
        self.assertEqual(sentinel.read_bytes(), b'keep')

    def test_public_cli_compose_emit_and_additive_extension(self):
        first = self.write(capture([observation()], 18))
        second = self.write(capture([observation(0x4100, (0xA9, 43))], 26))
        destination = self.root/'history'
        code, output, error = self.invoke('compose-history', first, '--out', destination)
        self.assertEqual(code, 0, error)
        report = json.loads(output)
        self.assertEqual(report['inputs'], 1)
        self.assertFalse(report['execution_evidence'])
        self.assertEqual(report['sha256'], hashlib.sha256((destination/'history.json').read_bytes()).hexdigest())
        extended = self.root/'extended'
        code, output, error = self.invoke('compose-history', second,
            '--baseline-history', destination/'history.json', '--out', extended)
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)['inputs'], 2)
        code, output, error = self.invoke('emit-history', extended/'history.json',
            '--out', self.root/'module', '--partition-layout', 'stable', '--native-span')
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)['native_instructions_emitted'], 2)

    def test_cli_imports_retained_profile_and_history_without_inventing_new_capture(self):
        first = self.write(capture([observation()]))
        profile = compose_observation_profile([first])
        path = self.root/'profile.json'
        path.write_text(json.dumps(profile), encoding='utf-8', newline='\n')
        imported = self.root/'imported'
        code, stdout, stderr = self.invoke('compose-history', '--baseline-profile', path,
                                           '--out', imported)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)['inputs'], 1)
        copied = self.root/'copied'
        code, stdout, stderr = self.invoke('compose-history', '--baseline-history',
                                           imported/'history.json', '--out', copied)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)['inputs'], 1)
        self.assertEqual((imported/'history.json').read_bytes(), (copied/'history.json').read_bytes())
        output = self.root/'empty'
        code, _, _ = self.invoke('compose-history', '--out', output)
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())

    def test_cli_wrong_formats_and_invalid_options_refuse_before_publication(self):
        first = self.write(capture([observation()]))
        history = self.history([first])
        for index, (command, path, extra) in enumerate((
                ('emit-profile', history.index_path, []),
                ('emit-capture', history.index_path, []),
                ('emit-history', first, []),
                ('emit-history', history.index_path, ['--native-span']),
                ('emit-history', history.index_path, ['--partition-size', '0']))):
            output = self.root/f'failed-{index}'
            code, _, _ = self.invoke(command, path, '--out', output, *extra)
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())

    def test_prepare_project_cli_delegates_explicit_paths_without_extra_actions(self):
        spec, output = self.root/'recipe.toml', self.root/'consumer'
        with patch('pcerecomp.prepare.prepare_project', return_value={'prepared': True}) as prepare:
            code, stdout, stderr = self.invoke('prepare-project', spec, '--out', output)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout), {'prepared': True})
        prepare.assert_called_once_with(spec, output)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
