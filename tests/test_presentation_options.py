"""Authored presentation options and paused TCP confirmation/checkpoint contracts."""
import json
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from pcerecomp import project
from pcerecomp.project import _presentation_args
from scripts.dev_client import DevError
from test_dev_server_cli import DESKTOP, HEADLESS, RunningSandbox
from test_checkpoint_cli import wait_paused, comparable


class PresentationOptions(unittest.TestCase):
    def test_host_effect_percentages_are_explicit_and_desktop_only(self):
        self.assertEqual(_presentation_args({'desktop': True}, {'softness': 0, 'persistence': 100}),
                         ['--display-softness', '0', '--display-persistence', '100'])
        for key in ('softness', 'persistence'):
            for value in (-1, 101, True, 1.5, '50', None):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    _presentation_args({'desktop': True}, {key: value})
            with self.assertRaises(ValueError):
                _presentation_args({'desktop': False}, {key: 0})

    def test_launch_cli_forwards_both_effect_settings_without_gpu_requirement(self):
        with patch.object(project, 'prepare_launch', return_value={'planned': True}) as launch, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(project.main(['launch-plan', 'authored.toml', '--build-dir', 'output',
                '--display-shader', 'off', '--display-softness', '25', '--display-persistence', '60']), 0)
        self.assertEqual(launch.call_args.kwargs['presentation'],
                         {'shader': 'off', 'softness': 25, 'persistence': 60})

    def test_validated_shader_controls_and_input_path(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / 'input.json'
            profile.write_text('{"schema":1}')
            result = _presentation_args({'desktop': True}, {
                'brightness': 200, 'saturation': 0, 'scanline': 100,
                'mask': 0, 'grid': 26, 'vignette': 8, 'input_profile': profile})
            self.assertEqual(result, ['--shader-scanline', '100', '--shader-mask', '0',
                '--shader-grid', '26', '--shader-vignette', '8', '--shader-brightness', '200',
                '--shader-saturation', '0', '--input-profile', str(profile.resolve())])
            for key in ('scanline', 'mask', 'grid', 'vignette', 'brightness', 'saturation'):
                for value in (-1, True, 2.5, '10', 201):
                    with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                        _presentation_args({'desktop': True}, {key: value})
            for value in (False, '', directory):
                with self.assertRaises(ValueError):
                    _presentation_args({'desktop': True}, {'input_profile': value})
            with self.assertRaises(ValueError):
                _presentation_args({'desktop': False}, {'brightness': 50})

    def test_existing_presentation_arguments_unchanged(self):
        self.assertEqual(_presentation_args({'desktop': True}, {
            'mode': 'square', 'filter': 'linear', 'shader': 'crt-mask', 'fullscreen': False, 'scale': 2}),
            ['--display-mode', 'square', '--display-filter', 'linear', '--display-shader', 'crt-mask',
             '--fullscreen', 'off', '--window-scale', '2'])


@unittest.skipUnless(DESKTOP.is_file(), 'Enable desktop tests')
class DisplayConfirmationTcp(unittest.TestCase):
    def test_paused_display_transactions_preserve_checkpoint_and_guest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            options = ['--checkpoint-dir', str(root), '--checkpoint-context', 'a'*64]
            app = RunningSandbox(DESKTOP, root, desktop=True, extra_options=options)
            try:
                client = app.client
                wait_paused(client, client.call('step_frames', frames=3)['target_frame'])
                before = client.call('status')
                client.call('save_checkpoint', name='before.pcec')
                original = client.call('display_settings')['display']
                preview = dict(action='preview', width=512, height=384, mode='square', filter='linear', timeout_ms=1000)
                self.assertTrue(client.preview_display(512, 384, mode='square', filter='linear', timeout_ms=1000)['pending'])
                with self.assertRaises(DevError): client.call('display_settings', **preview)
                with self.assertRaises(DevError): client.call('resize_window', width=256, height=240)
                self.assertEqual(client.cancel_display(), original)
                client.call('display_settings', **preview)
                committed = client.confirm_display()
                self.assertFalse(committed['pending'])
                self.assertEqual((committed['width'], committed['height']), (512, 384))
                expiring = dict(preview, width=640, timeout_ms=25)
                client.call('display_settings', **expiring)
                time.sleep(.06)
                self.assertEqual(client.call('display_settings')['display'], committed)
                for bad in (dict(preview, width='512'), dict(preview, width=127), dict(preview, timeout_ms=0),
                            dict(preview, mode='invented'), dict(preview, fullscreen=2),
                            {'action': 'status', 'width': 200}):
                    with self.assertRaises(DevError): client.call('display_settings', **bad)
                self.assertEqual(comparable(client.call('status')), comparable(before))
                client.call('save_checkpoint', name='after.pcec')
                self.assertEqual((root/'before.pcec').read_bytes(), (root/'after.pcec').read_bytes())
                client.call('quit')
                stdout, stderr = app.process.communicate(timeout=5)
                self.assertEqual(app.process.returncode, 0, stderr)
                self.assertEqual(json.loads(stdout)['native_steps'], 0)
            finally:
                app.close()
            app = RunningSandbox(DESKTOP, root, desktop=True, extra_options=options)
            try:
                app.client.call('load_checkpoint', name='before.pcec')
                restored = app.client.call('status')
                self.assertEqual(restored['host']['desktop']['presentation_effects']['epoch'],
                                 before['host']['desktop']['presentation_effects']['epoch']+1)
                self.assertEqual(comparable(restored, ignore_presentation_epoch=True),
                                 comparable(before, ignore_presentation_epoch=True))
                self.assertFalse(app.client.call('display_settings')['display']['pending'])
                app.client.call('quit');app.process.communicate(timeout=5)
                self.assertEqual(app.process.returncode, 0)
            finally:
                app.close()

    @unittest.skipUnless(HEADLESS.is_file(), 'Build headless tests')
    def test_headless_has_no_display_transaction(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = RunningSandbox(HEADLESS, Path(temporary))
            try:
                with self.assertRaises(DevError): app.client.call('display_settings')
            finally:
                app.close()
