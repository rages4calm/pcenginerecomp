"""Explicit, isolated BRAM sessions; no guest formatting or implicit save root.

The caller chooses an existing directory, a namespace and a content-compatibility
digest. This digest describes media/firmware/mod save compatibility, not a
compiler ABI. A session holds a process lock until it closes. Only an explicit
``commit()`` publishes a successful host's raw 2048-byte export.

Locks coordinate users of this interface. Entry checks also detect accidental
external edits before publication; they do not protect against a malicious
process replacing directory components or racing a non-cooperating write.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile


BRAM_BYTES = 2048
MAX_SAVE_BYTES = 8192
_NAMESPACE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}
_FIELDS = {"schema", "kind", "namespace", "compatibility_sha256",
           "payload_sha256", "payload_base64"}


def _namespace(value: str) -> str:
    if (not isinstance(value, str) or not _NAMESPACE.fullmatch(value)
            or value.endswith(".") or value.split(".", 1)[0] in _RESERVED):
        raise ValueError("Save namespace requires 1..64 lowercase safe filename characters")
    return value


def _digest(value: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ValueError("Save compatibility requires a lowercase SHA256 digest")
    return value


def _reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _directory(path: Path) -> None:
    # Inspect the supplied spelling before resolve() could erase links/junctions.
    for component in (path, *path.parents):
        info = component.lstat()
        if _reparse(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("Save root and its parents must be ordinary directories")


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _entry(path: Path) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if _reparse(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Save entries must be ordinary files without extra hardlinks")
    return info


def _read(path: Path, limit: int, *, missing: bool = False) -> bytes | None:
    entry = _entry(path)
    if entry is None:
        if missing:
            return None
        raise ValueError("Save session output is missing")
    if entry.st_size > limit:
        raise ValueError("Save file exceeds its bounded size")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (_identity(opened) != _identity(entry) or not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1):
            raise ValueError("Save file changed while opening")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        final = _entry(path)
        if (final is None or _identity(final) != _identity(opened)
                or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                or len(raw) != after.st_size):
            raise ValueError("Save file changed while reading")
    if len(raw) > limit:
        raise ValueError("Save file exceeds its bounded size")
    return raw


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate save metadata field")
        result[key] = value
    return result


def _decode(raw: bytes, namespace: str, compatibility_sha256: str) -> tuple[bytes, str]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("Invalid save metadata") from error
    if (not isinstance(value, dict) or set(value) != _FIELDS
            or type(value["schema"]) is not int or value["schema"] != 1
            or value["kind"] != "pce-bram-save"
            or value["namespace"] != namespace
            or value["compatibility_sha256"] != compatibility_sha256):
        raise ValueError("Save schema, namespace or compatibility differs")
    expected = value["payload_sha256"]
    if not isinstance(expected, str) or not _DIGEST.fullmatch(expected):
        raise ValueError("Invalid save payload digest")
    encoded = value["payload_base64"]
    if not isinstance(encoded, str):
        raise ValueError("Invalid save payload encoding")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Invalid save payload encoding") from error
    if (len(payload) != BRAM_BYTES or base64.b64encode(payload).decode("ascii") != encoded
            or hashlib.sha256(payload).hexdigest() != expected):
        raise ValueError("Save payload size or checksum differs")
    return payload, expected


def _encode(payload: bytes, namespace: str, compatibility_sha256: str) -> bytes:
    return (json.dumps({"schema": 1, "kind": "pce-bram-save", "namespace": namespace,
                        "compatibility_sha256": compatibility_sha256,
                        "payload_sha256": hashlib.sha256(payload).hexdigest(),
                        "payload_base64": base64.b64encode(payload).decode("ascii")},
                       sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class BramSession:
    """Hold one namespace and publish BRAM only following caller qualification.

    ``seed_path`` is None for an absent save; otherwise it names a read-only
    isolated copy. ``output_path`` is a new filename for ``--bram-out``. Root
    must already exist and must not contain symlink/junction components. No
    migration, raw import, guest formatting, recovery guessing or auto-commit
    occurs. ``previous_payload_sha256`` is None for a new namespace.

    Publication flushes file bytes, atomically creates/replaces one envelope,
    and flushes the containing directory on POSIX. Windows uses file fsync plus
    os.replace's atomic replacement; no power-loss guarantee is made for the
    directory entry. A post-publication directory-flush failure cannot undo an
    already visible atomic replacement and is reported to the caller.
    """

    def __init__(self, root: Path, namespace: str, compatibility_sha256: str):
        self.root = Path(os.path.abspath(root))
        self.namespace = _namespace(namespace)
        self.compatibility_sha256 = _digest(compatibility_sha256)
        self.save_path = self.root / (self.namespace + ".bram.json")
        self.seed_path: Path | None = None
        self.output_path: Path | None = None
        self.previous_payload_sha256: str | None = None
        self._lock = None
        self._lock_identity = None
        self._directory: Path | None = None
        self._session_identity = None
        self._seed_identity = None
        self._output_identity = None
        self._original: bytes | None = None
        self._started = False
        self._active = False
        self._committed = False

    def __enter__(self) -> BramSession:
        if self._started:
            raise ValueError("Save session cannot be reused")
        self._started = True
        _directory(self.root)
        lock_path = self.root / (self.namespace + ".lock")
        _entry(lock_path)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, 0o600)
        self._lock = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            opened, entry = os.fstat(descriptor), _entry(lock_path)
            if entry is None or _identity(opened) != _identity(entry):
                raise ValueError("Save lock changed while opening")
            self._lock_identity = _identity(opened)
            if os.name == "nt":
                import msvcrt
                self._lock.seek(0)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._active = True
            self._original = _read(self.save_path, MAX_SAVE_BYTES, missing=True)
            payload = None
            if self._original is not None:
                payload, self.previous_payload_sha256 = _decode(
                    self._original, self.namespace, self.compatibility_sha256)
            self._directory = Path(tempfile.mkdtemp(prefix=f".{self.namespace}.session-", dir=self.root))
            self._session_identity = _identity(self._directory.lstat())
            self.output_path = self._directory / "output.bram"
            if payload is not None:
                self.seed_path = self._directory / "initial.bram"
                with self.seed_path.open("xb") as stream:
                    stream.write(payload)
                self._seed_identity = _identity(self.seed_path.lstat())
                self.seed_path.chmod(0o400)
            return self
        except BaseException as error:
            acquired = self._active
            self.__exit__(type(error), error, error.__traceback__)
            if isinstance(error, OSError) and not acquired:
                raise ValueError("Save namespace is busy or its lock is unavailable") from error
            raise

    @property
    def committed(self) -> bool:
        """Whether atomic publication happened, including a later durability error."""
        return self._committed

    def commit(self) -> dict:
        if not self._active or self._directory is None or self.output_path is None:
            raise ValueError("Save session is not active")
        if self._committed:
            raise ValueError("Save session is already committed")
        self._check_session_directory()
        output_entry = _entry(self.output_path)
        if output_entry is not None:
            self._output_identity = _identity(output_entry)
        payload = _read(self.output_path, BRAM_BYTES)
        if payload is None or len(payload) != BRAM_BYTES:
            raise ValueError("Save export must contain exactly 2048 raw bytes")
        if self.seed_path is not None:
            seed = _read(self.seed_path, BRAM_BYTES)
            if seed is None or hashlib.sha256(seed).hexdigest() != self.previous_payload_sha256:
                raise ValueError("Save session initial snapshot changed")
        envelope = _encode(payload, self.namespace, self.compatibility_sha256)
        staging = self._directory / "publication.json"
        staging_identity = None
        try:
            descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                staging_identity = _identity(os.fstat(stream.fileno()))
                stream.write(envelope)
                stream.flush()
                os.fsync(stream.fileno())
            _directory(self.root)
            lock_entry = _entry(self.root / (self.namespace + ".lock"))
            if lock_entry is None or _identity(lock_entry) != self._lock_identity:
                raise ValueError("Held save lock entry changed")
            if _read(self.save_path, MAX_SAVE_BYTES, missing=True) != self._original:
                raise ValueError("Save changed outside the held session")
            if self._original is None:
                # Atomic create-new: an unrelated creator must never be overwritten.
                os.link(staging, self.save_path)
                self._committed = True
                self._unlink_known(staging, staging_identity)
            else:
                os.replace(staging, self.save_path)
            self._committed = True
            if os.name != "nt":
                descriptor = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            if staging_identity is not None:
                self._unlink_known(staging, staging_identity)
        return {"schema": 1, "namespace": self.namespace,
                "compatibility_sha256": self.compatibility_sha256,
                "previous_payload_sha256": self.previous_payload_sha256,
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": BRAM_BYTES, "created": self._original is None}

    def _check_session_directory(self):
        if self._directory is None:
            raise ValueError("Save session directory is unavailable")
        info = self._directory.lstat()
        if (_reparse(info) or not stat.S_ISDIR(info.st_mode)
                or _identity(info) != self._session_identity):
            raise ValueError("Save session directory changed")

    @staticmethod
    def _unlink_known(path, identity, *, readonly=False):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        if _reparse(info) or not stat.S_ISREG(info.st_mode) or _identity(info) != identity:
            raise ValueError("Save session entry was replaced; preserving it")
        if readonly:
            if info.st_nlink != 1:
                raise ValueError("Save session initial snapshot gained a hardlink; preserving it")
            path.chmod(0o600)
        path.unlink()

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self._directory is not None:
                try:
                    self._check_session_directory()
                except (OSError, ValueError):
                    if exc_type is None:
                        raise
                    return False
                for path, identity, readonly in ((self.seed_path, self._seed_identity, True),
                                                 (self.output_path, self._output_identity, False)):
                    if path is None:
                        continue
                    try:
                        if identity is None:
                            # output.bram is a reserved, session-owned export slot.
                            # Before a commit attempt it has no observed inode;
                            # adopt only an ordinary singly linked file here.
                            info = _entry(path)
                            if info is None:
                                continue
                            identity = _identity(info)
                        self._unlink_known(path, identity, readonly=readonly)
                    except FileNotFoundError:
                        pass
                    except (OSError, ValueError):
                        if exc_type is None:
                            raise
                try:
                    self._directory.rmdir()  # Never recursively remove unexpected entries.
                except OSError:
                    if exc_type is None:
                        raise
        finally:
            if self._lock is not None:
                self._lock.close()  # OS releases lock, including after process termination.
                self._lock = None
            self._active = False
        return False
