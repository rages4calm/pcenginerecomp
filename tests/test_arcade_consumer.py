"""Authored Arcade Card recipe/metadata admission; no retail files required."""
import json
from pathlib import Path
import unittest

from pcerecomp import project
import test_project as fixtures


class ArcadeConsumerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ConsumerProjectTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.descriptor = self.fixture.root, self.fixture.descriptor
        self.plain = self.fixture.reset_descriptor('super')
        self.arcade = self.plain.replace('profile = "super"',
                                         'profile = "super"\narcade_card = "duo"')
        self.descriptor.write_text(self.arcade)

    def verify(self):
        return project.verify(self.descriptor, allow_revision_override=True)

    def boot(self):
        return dict(mode='system-card-reset', profile='super',
                    initialization='gear-deterministic-zero-v1', vector_physical=8190,
                    pc=0, a=0, x=0, y=0, sp=0, p=4, clock_divisor=12, ticks=0,
                    cycles=0, mpr=[0]*8, bram='blank-unformatted', arcade_card='duo')

    def test_explicit_super_expansion_is_bound_and_forwarded_once(self):
        enabled = self.verify()
        command = project.command_for(enabled, Path('runner'))
        self.assertEqual(command[1:4], ['--system-card-reset', 'super', str(self.root/'authored.pce')])
        self.assertEqual(command.count('--arcade-card'), 1)
        self.assertEqual(command[command.index('--arcade-card')+1], 'duo')
        self.descriptor.write_text(self.plain)
        disabled = self.verify()
        self.assertEqual(enabled['identities'], disabled['identities'])
        self.assertNotEqual(project._binding(enabled), project._binding(disabled))
        self.assertNotIn('--arcade-card', project.command_for(disabled, Path('runner')))

    def test_expansion_requires_super_reset_recipe_and_known_exact_name(self):
        for text in (self.arcade.replace('profile = "super"', 'profile = "standard"'),
                     *(self.arcade.replace('arcade_card = "duo"', 'arcade_card = '+value)
                       for value in ('"pro"', '"none"', '"DUO"', 'true', '0', '["duo"]')),
                     self.arcade.replace('arcade_card = "duo"',
                                         'arcade_card = "duo"\narcade_card = "duo"')):
            with self.subTest(text=text):
                self.descriptor.write_text(text)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_hucard_and_payload_cannot_accept_expansion(self):
        rom = self.root/'authored-hucard.pce'
        rom.write_bytes(bytes(8192))
        hucard = f'''[boot]
mode = "hucard-reset"
profile = "base"
header = "none"
encoding = "linear"
arcade_card = "duo"
[cartridge]
path = "authored-hucard.pce"
sha256 = "{project.sha256(rom)}"
'''
        start, end = self.fixture.text.index('[payload]'), self.fixture.text.index('[runtime]')
        for text in (self.fixture.text[:start]+hucard+self.fixture.text[end:],
                     self.fixture.text.replace('[payload]', '[payload]\narcade_card = "duo"'),
                     self.fixture.text+'\n[boot]\nmode = "system-card-reset"\nprofile = "super"\narcade_card = "duo"\n'):
            self.descriptor.write_text(text)
            with self.assertRaises(ValueError):
                self.verify()

    def test_initial_expansion_metadata_is_required_exact_and_typed(self):
        checked = self.verify()
        expected = self.boot()
        self.assertEqual(project._boot_provenance(checked, {'boot': expected}), {'valid': True})
        missing = dict(expected)
        del missing['arcade_card']
        variants = [missing, expected | {'extra': 0}]
        variants += [expected | {'arcade_card': value} for value in (None, True, 'pro', 'DUO', ['duo'])]
        for value in variants:
            with self.subTest(value=value):
                self.assertFalse(project._boot_provenance(checked, {'boot': value})['valid'])
        self.descriptor.write_text(self.plain)
        plain = self.verify()
        self.assertFalse(project._boot_provenance(plain, {'boot': expected})['valid'])
        self.assertEqual(project._boot_provenance(plain, {'boot': missing}), {'valid': True})


if __name__ == '__main__':
    unittest.main()
