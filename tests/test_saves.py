"""Authored BRAM session data: isolation, publication, corruption and contention."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp.saves import BramSession, MAX_SAVE_BYTES


class BramSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contract = hashlib.sha256(b"authored firmware/media/save layout v1").hexdigest()
        self.payload = bytes((i * 17 + 29) & 255 for i in range(2048))
        self.save = self.root / "fixture.bram.json"

    def session(self, **kwargs):
        return BramSession(kwargs.get("root", self.root), kwargs.get("namespace", "fixture"),
                           kwargs.get("contract", self.contract))

    def publish(self, payload=None):
        with self.session() as session:
            session.output_path.write_bytes(self.payload if payload is None else payload)
            return session.commit()

    def test_first_save_reload_and_explicit_successful_replacement(self):
        with self.session() as session:
            self.assertIsNone(session.seed_path)
            self.assertIsNone(session.previous_payload_sha256)
            self.assertFalse(session.output_path.exists())
            session.output_path.write_bytes(self.payload)
            report = session.commit()
            self.assertTrue(report["created"])
            self.assertEqual(report["payload_sha256"], hashlib.sha256(self.payload).hexdigest())
            self.assertNotIn(str(self.root), json.dumps(report))
            with self.assertRaisesRegex(ValueError, "already committed"):
                session.commit()
        self.assertEqual(set(p.name for p in self.root.iterdir()), {"fixture.bram.json", "fixture.lock"})
        value = json.loads(self.save.read_bytes())
        self.assertEqual(value["schema"], 1)
        self.assertEqual(value["kind"], "pce-bram-save")
        self.assertEqual(value["namespace"], "fixture")
        self.assertEqual(value["compatibility_sha256"], self.contract)
        self.assertEqual(base64.b64decode(value["payload_base64"]), self.payload)
        with self.session() as session:
            self.assertEqual(session.seed_path.read_bytes(), self.payload)
            self.assertEqual(session.previous_payload_sha256, hashlib.sha256(self.payload).hexdigest())
            session.output_path.write_bytes(bytes(2048))
            report = session.commit()
            self.assertFalse(report["created"])
            self.assertEqual(report["previous_payload_sha256"], hashlib.sha256(self.payload).hexdigest())
        with self.session() as session:
            self.assertEqual(session.seed_path.read_bytes(), bytes(2048))

    def test_no_auto_publication_on_normal_exit_exception_or_missing_output(self):
        for raises in (False, True):
            with self.subTest(raises=raises):
                try:
                    with self.session() as session:
                        session.output_path.write_bytes(self.payload)
                        if raises:
                            raise RuntimeError("authored guest failure")
                except RuntimeError:
                    pass
                self.assertFalse(self.save.exists())
        self.publish()
        original = self.save.read_bytes()
        with self.session() as session:
            with self.assertRaisesRegex(ValueError, "missing"):
                session.commit()
        self.assertEqual(original, self.save.read_bytes())

    def test_invalid_export_lengths_do_not_touch_existing_save(self):
        self.publish()
        original = self.save.read_bytes()
        for size in (0, 1, 2047, 2049, MAX_SAVE_BYTES + 1):
            with self.subTest(size=size), self.session() as session:
                session.output_path.write_bytes(bytes(size))
                with self.assertRaises(ValueError):
                    session.commit()
                self.assertEqual(original, self.save.read_bytes())

    def test_namespace_and_compatibility_refusals(self):
        for name in ("", ".", "..", "../x", "x/y", "x\\y", "A", "x ", "x.", "x" * 65,
                     "con", "con.any", "prn", "aux", "nul", "com1", "lpt9", None, 3):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.session(namespace=name)
        for digest in ("", "1" * 63, "A" * 64, "g" * 64, None, 3):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                self.session(contract=digest)
        for name in ("profile-1", "profile_2", "profile.3", "x" * 64):
            with self.subTest(name=name), self.session(namespace=name) as session:
                self.assertIsNone(session.seed_path)
        self.publish()
        original = self.save.read_bytes()
        with self.assertRaisesRegex(ValueError, "compatibility"):
            with self.session(contract="f" * 64):
                pass
        self.assertEqual(original, self.save.read_bytes())

    def test_separate_namespaces_have_separate_contents(self):
        self.publish()
        with self.session(namespace="other") as session:
            self.assertIsNone(session.seed_path)
            session.output_path.write_bytes(bytes(2048))
            session.commit()
        with self.session() as first, self.session(namespace="other") as other:
            self.assertEqual(first.seed_path.read_bytes(), self.payload)
            self.assertEqual(other.seed_path.read_bytes(), bytes(2048))

    def test_malformed_metadata_never_falls_back_or_overwrites(self):
        self.publish()
        valid = json.loads(self.save.read_bytes())
        cases = [b"", b"\xff", b"{}", b"[]", b"null", b"{" + b" " * MAX_SAVE_BYTES,
                 b"[" * 1500, b'{"schema":1,"schema":1}']
        for key in valid:
            value = dict(valid)
            del value[key]
            cases.append(json.dumps(value).encode())
        for key, bad in (("schema", True), ("schema", 2), ("schema", 1.0),
                         ("kind", "different"), ("namespace", "other"),
                         ("compatibility_sha256", "e" * 64), ("payload_sha256", "a" * 64),
                         ("payload_sha256", 42), ("payload_base64", 42),
                         ("payload_base64", "!"), ("payload_base64", base64.b64encode(bytes(2047)).decode()),
                         ("payload_base64", base64.b64encode(bytes(2049)).decode())):
            value = dict(valid)
            value[key] = bad
            cases.append(json.dumps(value).encode())
        extra = dict(valid, unknown=0)
        cases.append(json.dumps(extra).encode())
        duplicate = json.dumps(valid)[:-1] + ',"namespace":"fixture"}'
        cases.append(duplicate.encode())
        for raw in cases:
            with self.subTest(raw=raw[:60]):
                self.save.write_bytes(raw)
                with self.assertRaises(ValueError):
                    with self.session():
                        pass
                self.assertEqual(self.save.read_bytes(), raw)

    def test_noncanonical_base64_is_rejected_even_when_decoded_bytes_match(self):
        self.publish()
        value = json.loads(self.save.read_bytes())
        encoded = value["payload_base64"]
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        index = alphabet.index(encoded[-2])
        self.assertEqual(index & 3, 0)  # One unused pair of bits for 2048 bytes.
        value["payload_base64"] = encoded[:-2] + alphabet[index | 1] + "="
        self.assertEqual(base64.b64decode(value["payload_base64"]), self.payload)
        self.save.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum"):
            with self.session():
                pass

    def test_external_save_modification_or_removal_refuses_commit(self):
        self.publish()
        for change in ("edit", "remove"):
            if self.save.exists():
                self.save.unlink()
            self.publish()
            with self.subTest(change=change), self.session() as session:
                session.output_path.write_bytes(bytes(2048))
                if change == "edit":
                    self.save.write_bytes(b"external edit retained")
                else:
                    self.save.unlink()
                with self.assertRaisesRegex(ValueError, "changed outside"):
                    session.commit()
                self.assertEqual(self.save.read_bytes() if self.save.exists() else None,
                                 b"external edit retained" if change == "edit" else None)

    def test_external_creation_and_atomic_create_race_never_overwrite(self):
        with self.session() as session:
            session.output_path.write_bytes(self.payload)
            self.save.write_bytes(b"created externally")
            with self.assertRaisesRegex(ValueError, "changed outside"):
                session.commit()
            self.assertEqual(self.save.read_bytes(), b"created externally")
        self.save.unlink()
        real_link = os.link
        def racing_link(source, target):
            Path(target).write_bytes(b"created at publication")
            return real_link(source, target)
        with self.session() as session:
            session.output_path.write_bytes(self.payload)
            with patch("pcerecomp.saves.os.link", side_effect=racing_link), self.assertRaises(FileExistsError):
                session.commit()
            self.assertEqual(self.save.read_bytes(), b"created at publication")

    def test_failed_flush_and_replace_preserve_original(self):
        self.publish()
        original = self.save.read_bytes()
        for operation in ("fsync", "replace"):
            with self.subTest(operation=operation), self.session() as session:
                session.output_path.write_bytes(bytes(2048))
                with patch("pcerecomp.saves.os." + operation, side_effect=OSError("authored I/O failure")):
                    with self.assertRaises(OSError):
                        session.commit()
                self.assertEqual(self.save.read_bytes(), original)

    def test_initial_snapshot_modification_refuses_commit(self):
        self.publish()
        original = self.save.read_bytes()
        with self.session() as session:
            session.seed_path.chmod(0o600)
            session.seed_path.write_bytes(bytes(2048))
            session.output_path.write_bytes(self.payload)
            with self.assertRaisesRegex(ValueError, "initial snapshot changed"):
                session.commit()
        self.assertEqual(self.save.read_bytes(), original)

    def test_root_requires_existing_ordinary_directory(self):
        for path in (self.root / "absent", self.root / "regular"):
            if path.name == "regular":
                path.write_bytes(b"file")
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                with self.session(root=path):
                    pass

    def test_hardlinked_save_lock_and_export_are_rejected(self):
        other = self.root / "authored other"
        other.write_bytes(self.payload)
        for target in (self.save, self.root / "fixture.lock"):
            with self.subTest(target=target):
                if target.exists():
                    target.unlink()
                os.link(other, target)
                try:
                    with self.assertRaises(ValueError):
                        with self.session():
                            pass
                finally:
                    target.unlink()
                self.assertEqual(other.read_bytes(), self.payload)
        with self.session() as session:
            os.link(other, session.output_path)
            try:
                with self.assertRaises(ValueError):
                    session.commit()
            finally:
                session.output_path.unlink()
        self.assertEqual(other.read_bytes(), self.payload)

    def test_symlink_save_lock_export_and_root_are_rejected(self):
        other = self.root / "authored target"
        other.write_bytes(self.payload)
        probe = self.root / "probe-link"
        try:
            probe.symlink_to(other)
        except OSError as error:
            # Windows may disable ordinary-user symlink creation. Hardlink and
            # regular-file cases remain unconditional; this case is explicit.
            self.skipTest(f"Symlink creation unavailable: {error.winerror if hasattr(error, 'winerror') else error.errno}")
        probe.unlink()
        for target in (self.save, self.root / "fixture.lock"):
            with self.subTest(target=target):
                if target.exists():
                    target.unlink()
                target.symlink_to(other)
                try:
                    with self.assertRaises(ValueError):
                        with self.session():
                            pass
                finally:
                    target.unlink()
        with self.session() as session:
            session.output_path.symlink_to(other)
            try:
                with self.assertRaises(ValueError):
                    session.commit()
            finally:
                session.output_path.unlink()
        linked_root = self.root / "linked root"
        linked_root.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            with self.session(root=linked_root):
                pass
        linked_root.unlink()
        self.assertEqual(other.read_bytes(), self.payload)

    def test_session_cannot_be_reentered_or_committed_after_close(self):
        session = self.session()
        with self.assertRaises(ValueError):
            session.commit()
        with session:
            with self.assertRaises(ValueError):
                session.__enter__()
        with self.assertRaises(ValueError):
            session.commit()
        with self.assertRaises(ValueError):
            session.__enter__()

    def test_contention_across_processes_and_lock_release_after_kill(self):
        script = ("from pathlib import Path; from pcerecomp.saves import BramSession; import sys; "
                  "s=BramSession(Path(sys.argv[1]),'fixture',sys.argv[2]); s.__enter__(); "
                  "print('locked',flush=True); sys.stdin.read()")
        process = subprocess.Popen([sys.executable, "-c", script, str(self.root), self.contract],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            for contract in (self.contract, "f" * 64):
                with self.subTest(contract=contract), self.assertRaisesRegex(ValueError, "busy"):
                    with self.session(contract=contract):
                        pass
            with self.session(namespace="independent"):
                pass
        finally:
            process.kill()
            process.communicate(timeout=10)
        with self.session() as session:
            self.assertIsNone(session.seed_path)

    def test_unexpected_session_file_is_not_recursively_deleted(self):
        session_directory = None
        with self.assertRaises(OSError):
            with self.session() as session:
                session_directory = session.output_path.parent
                (session_directory / "not-owned").write_bytes(b"retained")
        self.assertEqual((session_directory / "not-owned").read_bytes(), b"retained")
        with self.session():
            pass  # Lock was released even when cleanup could not remove directory.

    def test_publication_flag_survives_post_publication_cleanup_failure(self):
        with self.session() as session:
            self.assertFalse(session.committed)
            session.output_path.write_bytes(self.payload)
            with patch.object(session, "_unlink_known", side_effect=OSError("authored late cleanup failure")):
                with self.assertRaises(OSError):
                    session.commit()
            self.assertTrue(session.committed)
            self.assertEqual(base64.b64decode(json.loads(self.save.read_bytes())["payload_base64"]), self.payload)
            # This is the caller's authored failure fixture, not automatic orphan cleanup.
            (session.output_path.parent / "publication.json").unlink()
        with self.session() as session:
            self.assertEqual(session.seed_path.read_bytes(), self.payload)

    def test_replaced_seed_is_preserved_during_cleanup(self):
        self.publish()
        directory = None
        with self.assertRaisesRegex(ValueError, "entry was replaced"):
            with self.session() as session:
                directory = session.seed_path.parent
                session.seed_path.chmod(0o600)
                session.seed_path.rename(directory / "original-seed")
                session.seed_path.write_bytes(b"replacement must survive")
        self.assertEqual((directory / "initial.bram").read_bytes(), b"replacement must survive")
        self.assertEqual((directory / "original-seed").read_bytes(), self.payload)
        with self.session():
            pass

    def test_replaced_session_directory_is_not_used_or_cleaned(self):
        moved = None
        replacement = None
        with self.assertRaisesRegex(ValueError, "directory changed"):
            with self.session() as session:
                replacement = session.output_path.parent
                moved = replacement.with_name(replacement.name + "-moved")
                replacement.rename(moved)
                replacement.mkdir()
                session.output_path.write_bytes(b"not the owned directory")
                session.commit()
        self.assertEqual((replacement / "output.bram").read_bytes(), b"not the owned directory")
        self.assertTrue(moved.is_dir())
        self.assertFalse(self.save.exists())
        with self.session():
            pass


if __name__ == "__main__":
    unittest.main()
