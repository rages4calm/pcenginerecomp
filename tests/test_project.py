"""Authored consumer descriptor/refusal/receipt checks without private inputs."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import project


class ConsumerProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tool = self.root / "tool"
        for name in project.SOURCE_DIRS:
            (self.tool / name).mkdir(parents=True)
        (self.tool / "runtime/include/pce").mkdir(parents=True)
        (self.tool / "runtime/include/pce/runtime.hpp").write_text("inline constexpr unsigned abi_version = 12;\n")
        (self.tool / "CMakeLists.txt").write_text("# authored stub\n")
        (self.tool / "pcerecomp/logic.py").write_text("VALUE = 1\n")
        (self.root / "program.bin").write_bytes(bytes([0xEA, 0x80, 0xFD]))
        (self.root / "module.cpp").write_text("// authored contract fixture\n")
        (self.root / "module.json").write_text(json.dumps({"schema": 1, "runtime_abi": 12, "native_instructions_emitted": 2}))
        self.descriptor = self.root / "project.toml"
        self.text = f'''schema = 1
name = "fixture"
[tool]
path = "tool"
revision = "{'0' * 40}"
source_sha256 = "{project.source_identity(self.tool)['source_sha256']}"
runtime_abi = 12
[module.source]
path = "module.cpp"
sha256 = "{project.sha256(self.root / 'module.cpp')}"
[module.manifest]
path = "module.json"
sha256 = "{project.sha256(self.root / 'module.json')}"
[payload]
path = "program.bin"
sha256 = "{project.sha256(self.root / 'program.bin')}"
physical_load = 1048576
pc = 16384
mpr = [255,248,128,129,130,131,132,0]
[runtime]
tier = "hybrid"
video = "continuous"
cd_unknown_status = "fault"
joypad = 2
region = "usa"
multitap = "off"
[limits]
steps = 200
ticks = 100000
wall_seconds = 5
'''
        self.descriptor.write_text(self.text, encoding="utf-8")

    def verify(self):
        return project.verify(self.descriptor, allow_revision_override=True)

    def replace(self, old, new):
        self.descriptor.write_text(self.text.replace(old, new), encoding="utf-8")

    def test_valid_identity_and_paths_independent_of_cwd(self):
        old = Path.cwd()
        try:
            os.chdir(self.root / "tool")
            checked = self.verify()
        finally:
            os.chdir(old)
        self.assertEqual(checked["files"]["payload"], self.root / "program.bin")
        self.assertTrue(checked["revision_override"])

    def test_revision_requires_explicit_override(self):
        with self.assertRaisesRegex(ValueError, "revision mismatch"):
            project.verify(self.descriptor)

    def test_dirty_or_untracked_source_refused_even_with_override(self):
        for name in ("pcerecomp/logic.py", "runtime/untracked.cpp"):
            path = self.tool / name
            old = path.read_bytes() if path.exists() else None
            path.write_bytes(b"// changed source\n")
            with self.assertRaisesRegex(ValueError, "source digest mismatch"):
                self.verify()
            if old is None:
                path.unlink()
            else:
                path.write_bytes(old)

    def test_doc_and_cache_changes_do_not_change_code_identity(self):
        before = project.source_identity(self.tool)
        (self.tool / "pcerecomp/__pycache__").mkdir()
        (self.tool / "pcerecomp/__pycache__/unused.py").write_text("ignored")
        (self.tool / "README.md").write_text("documentation only")
        self.assertEqual(before, project.source_identity(self.tool))

    def test_enclosing_git_repository_is_not_export_revision(self):
        with patch.object(project.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, str(self.root))):
            self.assertIsNone(project.source_identity(self.tool)["revision"])

    def test_strict_schema_abi_and_fields(self):
        for old, new in (("schema = 1", "schema = true"), ("runtime_abi = 12", "runtime_abi = 13"),
                         ('name = "fixture"', 'name = "fixture"\nunrecognized = 1'),
                         ("steps = 200", "steps = true"), ("joypad = 2", "joypad = true"),
                         ("wall_seconds = 5", "wall_seconds = 601")):
            with self.subTest(new=new):
                self.replace(old, new)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_payload_mpr_and_extent_validation(self):
        for old, new in (("mpr = [255,248,128,129,130,131,132,0]", "mpr = [128]"),
                         ("physical_load = 1048576", "physical_load = 0"),
                         ("pc = 16384", "pc = 65536")):
            self.replace(old, new)
            with self.assertRaises(ValueError):
                self.verify()

    def test_file_hashes_and_manifest_abi_are_pinned(self):
        for name in ("program.bin", "module.cpp", "module.json"):
            path = self.root / name
            old = path.read_bytes()
            path.write_bytes(old + b" ")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                self.verify()
            path.write_bytes(old)
        path = self.root / "module.json"
        old_hash = project.sha256(path)
        path.write_text(json.dumps({"schema": 1, "runtime_abi": 13, "native_instructions_emitted": 2}))
        self.replace(old_hash, project.sha256(path))
        with self.assertRaisesRegex(ValueError, "Module schema/runtime ABI mismatch"):
            self.verify()

    def test_optional_bram_size_and_hash_validation(self):
        bram = self.root / "bram.bin"
        bram.write_bytes(b"short")
        self.descriptor.write_text(self.text + f'\n[bram]\npath = "bram.bin"\nsha256 = "{project.sha256(bram)}"\n')
        with self.assertRaisesRegex(ValueError, "exactly 2048"):
            self.verify()

    def test_manifest_rejects_nonobject_and_noninteger_abi(self):
        path = self.root / "module.json"
        old_hash = project.sha256(path)
        for manifest in ([], {"schema": 1, "runtime_abi": 12.0, "native_instructions_emitted": 2}):
            path.write_text(json.dumps(manifest))
            self.replace(old_hash, project.sha256(path))
            with self.assertRaisesRegex(ValueError, "Module schema/runtime ABI mismatch"):
                self.verify()

    def test_command_is_vector_and_keeps_explicit_profiles(self):
        checked = self.verify()
        command = project.command_for(checked, self.root / "binary path.exe", dev_port=0, start_paused=True)
        self.assertEqual(command[0], str(self.root / "binary path.exe"))
        self.assertEqual(command[4], "255,248,128,129,130,131,132,0")
        self.assertEqual(command[command.index("--cd-unknown-status") + 1], "fault")
        self.assertEqual(command[-4:], ["--dev-start-paused", "on", "--dev-memory-write", "off"])
        with self.assertRaises(ValueError):
            project.command_for(checked, Path("test"), memory_write=True)
        with self.assertRaises(ValueError):
            project.command_for(checked, Path("test"), capture_limit=10)
        captured = project.command_for(checked, Path("test"), code_capture=self.root / "capture.json", capture_limit=4096)
        self.assertEqual(captured[-2:], ["--capture-limit", "4096"])

    def build_fixture(self):
        checked = self.verify()
        directory = self.root / "build"
        binary = directory / "bin/fixture.exe"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"authored executable identity fixture")
        receipt = {"schema": 1, "kind": "pce-consumer-build", "binding": project._binding(checked),
                   "binary": str(binary), "binary_sha256": project.sha256(binary),
                   "output_files": {binary.name: project.sha256(binary)}, "desktop": False}
        (directory / "build-receipt.json").write_text(json.dumps(receipt))
        return directory, binary

    def test_stale_binary_or_descriptor_refused_before_execution(self):
        directory, binary = self.build_fixture()
        original = binary.read_bytes()
        binary.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "executable changed"):
            project.run(self.descriptor, directory, self.root / "run.json", allow_revision_override=True)
        binary.write_bytes(original)
        self.replace("steps = 200", "steps = 201")
        with self.assertRaisesRegex(ValueError, "does not match verified consumer"):
            project.run(self.descriptor, directory, self.root / "run.json", allow_revision_override=True)

    def test_receipt_preserves_actual_native_and_interpreted_work(self):
        directory, binary = self.build_fixture()
        # Mock only host execution; source identity Git queries remain real.
        actual_run = subprocess.run
        def execute(command, **kwargs):
            if command[0] == str(binary):
                return subprocess.CompletedProcess(command, 0, json.dumps({"stop": "step_limit", "native_steps": 7, "interpreter_steps": 93}))
            return actual_run(command, **kwargs)
        with patch.object(project.subprocess, "run", side_effect=execute):
            result = project.run(self.descriptor, directory, self.root / "run.json", allow_revision_override=True)
        self.assertTrue(result["qualified"])
        self.assertEqual(result["work"], {"native": 7, "interpreted": 93, "total": 100, "native_fraction": 0.07})
        self.assertEqual(result["result"]["stop"], "step_limit")
        with self.assertRaisesRegex(ValueError, "already exists"):
            project.run(self.descriptor, directory, self.root / "run.json", allow_revision_override=True)

    def test_cmake_path_injection_and_output_overwrite_refused(self):
        for value in ('folder;injection', 'folder$<expression>', 'folder"quote'):
            with self.assertRaises(ValueError):
                project._cmake_path(Path(value))
        with self.assertRaisesRegex(ValueError, "directory exists"):
            project.build(self.descriptor, self.root, allow_revision_override=True)

    def test_timeout_records_failure_instead_of_qualifying_partial_output(self):
        directory, binary = self.build_fixture()
        actual_run = subprocess.run
        def execute(command, **kwargs):
            if command[0] == str(binary):
                raise subprocess.TimeoutExpired(command, 15, output=b"{")
            return actual_run(command, **kwargs)
        with patch.object(project.subprocess, "run", side_effect=execute):
            result = project.run(self.descriptor, directory, self.root / "timeout.json", allow_revision_override=True)
        self.assertFalse(result["qualified"])
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["exit_code"], -1)

    def test_capture_receipt_checks_schema_and_retirement_total(self):
        directory, binary = self.build_fixture()
        actual_run = subprocess.run
        capture_path = self.root / "capture.json"
        capture = {"schema": 1, "runtime_abi": 12, "capacity": 4, "dropped_instructions": 0,
                   "unreadable_instructions": 0, "retired_instructions": 7, "complete": True,
                   "observations": [{"pc": 16384, "mpr": [255,248,128,129,130,131,132,0],
                                     "physical": [1048576], "data": [234], "native_hits": 7, "interpreted_hits": 0}]}
        def execute(command, **kwargs):
            if command[0] == str(binary):
                capture_path.write_text(json.dumps(capture))
                return subprocess.CompletedProcess(command, 0, json.dumps({"native_steps": 7, "interpreter_steps": 0}))
            return actual_run(command, **kwargs)
        with patch.object(project.subprocess, "run", side_effect=execute):
            result = project.run(self.descriptor, directory, self.root / "captured.json", allow_revision_override=True,
                                 code_capture=capture_path, capture_limit=4)
        self.assertTrue(result["qualified"])
        self.assertEqual(result["code_capture"]["observations"], 1)
        self.assertEqual(result["code_capture"]["sha256"], project.sha256(capture_path))


if __name__ == "__main__":
    unittest.main()
