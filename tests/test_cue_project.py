"""Authored compound-media consumer bindings; host execution is mocked only."""

import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from pcerecomp import project
from pcerecomp.cue import Cue
from pcerecomp.toc import Toc
import test_project as fixtures


class CueConsumerTests(unittest.TestCase):
    def setUp(self):
        fixtures.ConsumerProjectTests.setUp(self)
        (self.root / "data.bin").write_bytes(bytes([0x53]) * 2048)
        (self.root / "audio.bin").write_bytes(bytes([0xA5]) * 2352)
        self.cue = self.root / "disc.cue"
        self.cue.write_text('FILE "data.bin" BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n'
                            'FILE "audio.bin" BINARY\nTRACK 02 AUDIO\nINDEX 01 00:00:00\n', encoding="utf-8")
        self.digest = Cue(self.cue).image_sha256()
        self.text += f'\n[disc]\npath = "disc.cue"\nsha256 = "{self.digest}"\n'
        self.descriptor.write_text(self.text, encoding="utf-8")

    def verify(self):
        return project.verify(self.descriptor, allow_revision_override=True)

    def build_fixture(self):
        return fixtures.ConsumerProjectTests.build_fixture(self)

    def test_complete_image_pin_and_individual_component_bindings(self):
        checked = self.verify()
        self.assertEqual(checked["config"]["disc"]["sha256"], self.digest)
        self.assertEqual(checked["identities"]["disc"], project.sha256(self.cue))
        self.assertNotEqual(checked["identities"]["disc"], self.digest)
        for name in ("data.bin", "audio.bin"):
            self.assertEqual(checked["files"][f"disc_component:{name}"], self.root / name)
            self.assertEqual(checked["identities"][f"disc_component:{name}"], project.sha256(self.root / name))
        command = project.command_for(checked, Path("runner"))
        self.assertEqual(command[command.index("--disc") + 1], str(self.cue))
        self.assertFalse(any("disc-component" in token for token in command))

    def test_postgaps_export_disc_positions_and_rebind_same_stored_components(self):
        self.cue.write_text('FILE "data.bin" BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n'
                            'POSTGAP 00:00:02\nFILE "audio.bin" BINARY\nTRACK 02 AUDIO\n'
                            'INDEX 01 00:00:00\nPOSTGAP 00:00:03\n', encoding='utf-8')
        disc = Cue(self.cue)
        changed = disc.image_sha256()
        self.assertNotEqual(changed, self.digest)
        with self.assertRaisesRegex(ValueError, 'complete BIN/CUE image SHA256 mismatch'):
            self.verify()
        self.descriptor.write_text(self.text.replace(self.digest, changed), encoding='utf-8')
        verified = self.verify()
        toc = Toc.from_image(self.cue)
        self.assertEqual(toc.leadout_lba, 7)
        self.assertEqual([(t.number, t.index1_lba, t.type) for t in toc.tracks],
                         [(1, 0, 4), (2, 3, 0)])
        self.assertEqual(toc.image_sha256, changed)
        self.assertEqual([t.data_frames for t in disc.tracks], [1, 1])
        self.assertEqual([t.postgap for t in disc.tracks], [2, 3])
        for name, byte in (('data.bin', 0x53), ('audio.bin', 0xA5)):
            component = verified['files']['disc_component:'+name]
            self.assertEqual(component.read_bytes(), bytes([byte])*(2048 if name=='data.bin' else 2352))

    def test_plain_cue_file_hash_cannot_misrepresent_complete_image(self):
        self.descriptor.write_text(self.text.replace(self.digest, project.sha256(self.cue)), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "complete BIN/CUE image SHA256 mismatch"):
            self.verify()

    def test_descriptor_symlink_keeps_declared_root_in_actual_command(self):
        nested = self.root / "nested"
        nested.mkdir()
        actual = nested / "actual.cue"
        actual.write_bytes(self.cue.read_bytes())
        (nested / "data.bin").write_bytes(bytes([0x19]) * 2048)
        (nested / "audio.bin").write_bytes(bytes([0x37]) * 2352)
        alias = self.root / "alias.cue"
        try:
            alias.symlink_to(actual)
        except OSError:
            self.skipTest("Symlink creation unavailable")
        self.assertEqual(Cue(alias).image_sha256(), self.digest)
        self.assertNotEqual(Cue(actual).image_sha256(), self.digest)
        self.descriptor.write_text(self.text.replace('path = "disc.cue"', 'path = "alias.cue"'), encoding="utf-8")
        checked = self.verify()
        self.assertEqual(checked["files"]["disc"], alias)
        self.assertEqual(checked["files"]["disc_component:data.bin"], self.root / "data.bin")
        command = project.command_for(checked, Path("runner"))
        selected = Path(command[command.index("--disc") + 1])
        self.assertEqual(selected, alias)
        self.assertEqual(Cue(selected).read(0), bytes([0x53]) * 2048)

    def test_mutation_during_final_component_hash_binding_is_refused(self):
        original_hash = project.sha256
        mutated = False

        def hash_and_mutate(path):
            nonlocal mutated
            digest = original_hash(path)
            if Path(path) == self.cue and not mutated:
                mutated = True
                (self.root / "audio.bin").write_bytes(bytes(2352) + b"changed-size")
            return digest

        with patch.object(project, "sha256", side_effect=hash_and_mutate):
            with self.assertRaisesRegex(ValueError, "changed"):
                self.verify()

    def test_each_component_mutation_refuses_before_host_execution(self):
        for name in ("data.bin", "audio.bin"):
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(bytes([original[0] ^ 255]) + original[1:])
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "complete BIN/CUE image SHA256 mismatch"):
                self.verify()
            path.write_bytes(original)

    def test_even_updated_disc_pin_cannot_reuse_old_build_binding(self):
        directory, _ = self.build_fixture()
        (self.root / "audio.bin").write_bytes(bytes(2352))
        changed = Cue(self.cue).image_sha256()
        self.descriptor.write_text(self.text.replace(self.digest, changed), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not match verified consumer"):
            project.run(self.descriptor, directory, self.root / "refused.json", allow_revision_override=True)

    def test_runtime_component_mutation_is_recorded_and_never_qualified(self):
        directory, binary = self.build_fixture()
        actual_run = subprocess.run

        def execute(command, **kwargs):
            if command[0] == str(binary):
                (self.root / "audio.bin").write_bytes(bytes(2352))
                return subprocess.CompletedProcess(command, 0, json.dumps({"native_steps": 7, "interpreter_steps": 0}))
            return actual_run(command, **kwargs)

        with patch.object(project.subprocess, "run", side_effect=execute):
            receipt = project.run(self.descriptor, directory, self.root / "changed.json", allow_revision_override=True)
        self.assertFalse(receipt["qualified"])
        self.assertFalse(receipt["input_hashes_unchanged"]["disc_component:audio.bin"])
        self.assertTrue(receipt["input_hashes_unchanged"]["disc"])
        self.assertEqual(receipt["work"]["native"], 7)

    def test_complete_unchanged_set_is_bound_in_execution_receipt(self):
        directory, binary = self.build_fixture()
        actual_run = subprocess.run

        def execute(command, **kwargs):
            if command[0] == str(binary):
                return subprocess.CompletedProcess(command, 0, json.dumps({"native_steps": 7, "interpreter_steps": 3}))
            return actual_run(command, **kwargs)

        with patch.object(project.subprocess, "run", side_effect=execute):
            receipt = project.run(self.descriptor, directory, self.root / "unchanged.json", allow_revision_override=True)
        self.assertTrue(receipt["qualified"])
        self.assertTrue(all(receipt["input_hashes_unchanged"].values()))
        self.assertEqual(receipt["binding"]["files"]["disc_component:audio.bin"], project.sha256(self.root / "audio.bin"))

    def test_schema_does_not_allow_unverified_component_override(self):
        self.descriptor.write_text(self.text + 'components = []\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid disc fields"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
