"""Explicit offline cache of immutable, complete host binary packages.

The caller supplies the complete compilation contract. This module does not
infer compiler identity, authorize source execution, or cache run receipts.
Locks coordinate this interface; checks detect external replacement and ordinary
concurrent edits, not a malicious process controlling the filesystem or kernel.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


MAX_FILES = 64
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_CONTRACT_BYTES = 256 * 1024
MAX_COMPILED_INPUT_BYTES = 64 * 1024 * 1024
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.+\-]{0,127}\Z')
_RESERVED = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1,10)),
             *(f'lpt{i}' for i in range(1,10))}


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _canonical(value):
    def check(item, depth=0):
        _require(depth <= 64, 'Cache contract nesting exceeds bound')
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float:
            _require(math.isfinite(item), 'Cache JSON numbers must be finite')
            return
        if type(item) is list:
            for child in item:
                check(child, depth+1)
            return
        if type(item) is dict:
            for key, child in item.items():
                _require(type(key) is str, 'Cache JSON object keys must be strings')
                check(child, depth+1)
            return
        raise ValueError('Cache contract requires strict JSON values')
    check(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError('Invalid cache JSON') from error


def contract_identity(contract: dict) -> dict:
    """Identify a complete audited producer contract without embedding its graph.

    The caller must retain and revalidate the full contract in its own receipt.
    No input is omitted: names, source/header hashes, effective options, compiler
    and SDK identities all participate in the canonical strict-JSON digest.
    This helper changes neither the generic cache format nor its size limits.
    """
    _require(type(contract) is dict, 'Compiled input contract must be a JSON object')
    raw = _canonical(contract)
    _require(len(raw) <= MAX_COMPILED_INPUT_BYTES, 'Compiled input contract exceeds bound')
    return dict(schema=1, producer='pce-compiled-input-sha256-v1',
                sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'Duplicate cache JSON key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Non-finite cache JSON number')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('Invalid cache manifest JSON') from error


def _reparse(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _id(info):
    return info.st_dev, info.st_ino


def _stamp(info):
    # Windows lstat infers executable bits from .exe, whereas fstat does not.
    # They are not filesystem permissions there; retain actual POSIX modes.
    mode = info.st_mode & ~0o111 if os.name == 'nt' else info.st_mode
    # Windows Python versions can expose birth time through path stat and
    # metadata-change time through fstat as st_ctime. They are not comparable.
    change_time = None if os.name == 'nt' else info.st_ctime_ns
    return (_id(info), mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, change_time)


def _directory(path):
    for component in (path, *path.parents):
        info = component.lstat()
        _require(not _reparse(info) and stat.S_ISDIR(info.st_mode),
                 'Cache paths and parents must be ordinary directories')
    return path.lstat()


def _regular(path):
    info = path.lstat()
    _require(not _reparse(info) and stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
             'Cache artifacts must be ordinary files without extra hardlinks')
    return info


def _exists(path):
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def _name(name):
    _require(type(name) is str and _NAME.fullmatch(name) is not None and
             not name.endswith('.') and name.split('.',1)[0].lower() not in _RESERVED,
             'Unsafe cache artifact name')
    # Cache complete host packages, never generated source, assets or receipts.
    lowered = name.lower()
    _require('.' not in name or lowered.endswith(('.exe', '.dll', '.dylib')) or
             re.fullmatch(r'.+\.so(?:\.[0-9]+)*', lowered) is not None,
             'Only host executable/shared-library package artifacts may be cached')
    return name


def _file(path, destination=None, owned=None):
    """Hash a stable opened file; optional copy is also verified by its caller."""
    before = _regular(path)
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags)
    output = None
    try:
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            _require(_stamp(opened) == _stamp(before), 'Cache artifact changed while opening')
            if destination is not None:
                output = destination.open('xb')
                if owned is not None:
                    owned[destination.name] = _id(os.fstat(output.fileno()))
            digest = hashlib.sha256()
            size = 0
            signature = b''
            while block := stream.read(1024*1024):
                if not signature:
                    signature = block[:4]
                digest.update(block)
                size += len(block)
                if output is not None:
                    output.write(block)
            after = os.fstat(stream.fileno())
            _require(_stamp(opened) == _stamp(after) == _stamp(_regular(path)) and size == after.st_size,
                     'Cache artifact changed while reading')
            _require(signature.startswith(b'MZ') or signature in (
                b'\x7fELF', b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe',
                b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe',
                b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'),
                'Cache artifact lacks a host executable/shared-library signature')
            executable = bool(before.st_mode & 0o111)
            if output is not None:
                output.flush()
                os.fsync(output.fileno())
                output.close()
                output = None
                destination.chmod(0o700 if executable else 0o600)
            return dict(name=path.name, bytes=size, sha256=digest.hexdigest(), executable=executable), _stamp(after)
    finally:
        if output is not None:
            output.close()


def _scan(path, *, manifest=False):
    start = _directory(path)
    names = sorted(child.name for child in path.iterdir())
    expected_manifest = ['manifest.json'] if manifest else []
    artifacts = [name for name in names if name not in expected_manifest]
    _require(1 <= len(artifacts) <= MAX_FILES, 'Cache package file count exceeds bound or is empty')
    _require(len({name.lower() for name in artifacts}) == len(artifacts),
             'Case-insensitive duplicate cache artifact names')
    rows, identities = [], {}
    for name in artifacts:
        _name(name)
        row, identity = _file(path/name)
        _require(row['bytes'] > 0, 'Empty host package artifact')
        rows.append(row)
        identities[name] = identity
    _require(names == sorted(child.name for child in path.iterdir()) and
             _stamp(start) == _stamp(_directory(path)), 'Cache package directory changed while reading')
    return rows, (_stamp(start), identities)


def _read_manifest(path):
    before = _regular(path)
    _require(before.st_size <= MAX_MANIFEST_BYTES, 'Cache manifest exceeds bound')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        _require(_stamp(before) == _stamp(opened), 'Cache manifest changed while opening')
        raw = stream.read(MAX_MANIFEST_BYTES+1)
        _require(len(raw) <= MAX_MANIFEST_BYTES and len(raw) == opened.st_size and
                 _stamp(opened) == _stamp(os.fstat(stream.fileno())) == _stamp(_regular(path)),
                 'Cache manifest changed while reading')
    return raw, _stamp(opened)


def _rename_new(source, destination):
    """Atomic create-new directory publication, without replacing another path."""
    if os.name == 'nt':
        os.rename(source, destination)  # Windows refuses any existing destination.
        return
    if sys.platform.startswith('linux'):
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, 'renameat2', None)
        _require(rename is not None, 'Atomic create-new cache publication is unavailable')
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
        return
    raise ValueError('Atomic create-new cache publication is unsupported on this platform')


def _cleanup_owned(path, identity, owned):
    """Remove only registered files in an unchanged private staging directory."""
    if not _exists(path) or _id(_directory(path)) != identity:
        return
    for name, file_identity in owned.items():
        target = path/name
        if _exists(target) and _id(_regular(target)) == file_identity:
            target.unlink()
    if not list(path.iterdir()) and _id(_directory(path)) == identity:
        path.rmdir()


class BuildCache:
    """Hold a per-contract OS lock and verify immutable binary package entries.

    Root and restore-parent directories must already exist. A miss returns None
    without creating the destination. Corruption/interrupted publication raises;
    it is never silently repaired. No run or execution receipt is cached.
    """
    def __init__(self, root: Path, contract: dict):
        _require(type(contract) is dict, 'Cache contract must be a JSON object')
        self._contract_bytes = _canonical(contract)
        _require(len(self._contract_bytes) <= MAX_CONTRACT_BYTES, 'Cache contract exceeds bound')
        self.contract = _json(self._contract_bytes)
        self._key = hashlib.sha256(self._contract_bytes).hexdigest()
        self.root = Path(os.path.abspath(root))
        self._lock = None
        self._active = self._started = False
        self._root_id = self._lock_id = None
        self._baseline = None

    @property
    def key(self):
        return self._key

    @property
    def entry(self):
        return self.root/self.key

    def __enter__(self):
        _require(not self._started, 'Cache session cannot be reused')
        self._started = True
        self._root_id = _id(_directory(self.root))
        lock = self.root/(self.key+'.lock')
        if _exists(lock):
            _regular(lock)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        descriptor = os.open(lock, flags, 0o600)
        self._lock = os.fdopen(descriptor, 'r+b', buffering=0)
        try:
            self._lock_id = _id(os.fstat(descriptor))
            _require(self._lock_id == _id(_regular(lock)), 'Cache lock changed while opening')
            if os.name == 'nt':
                import msvcrt
                self._lock.seek(0)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._active = True
            _require(not any(child.name.startswith('.'+self.key+'.publish-') for child in self.root.iterdir()),
                     'Interrupted cache publication exists; explicit review required')
            self._baseline = self._verify()
            return self
        except BaseException as error:
            acquired = self._active
            self.__exit__(type(error), error, error.__traceback__)
            if isinstance(error, OSError) and not acquired:
                raise ValueError('Cache key is busy or its lock is unavailable') from error
            raise

    def _held(self):
        _require(self._active, 'Cache operation requires a held session')
        _require(_id(_directory(self.root)) == self._root_id and
                 _id(_regular(self.root/(self.key+'.lock'))) == self._lock_id,
                 'Held cache root or lock changed')
        _require(_canonical(self.contract) == self._contract_bytes,
                 'Cache contract changed during session')

    def _verify(self):
        self._held()
        if not _exists(self.entry):
            return None
        _directory(self.entry)
        raw, manifest_stamp = _read_manifest(self.entry/'manifest.json')
        value = _json(raw)
        _require(type(value) is dict and set(value) == {'schema','kind','key','contract','files'} and
                 type(value['schema']) is int and value['schema'] == 1 and
                 value['kind'] == 'pce-build-package' and value['key'] == self.key and
                 _canonical(value['contract']) == self._contract_bytes,
                 'Cache entry contract or schema differs')
        _require(type(value['files']) is list and 1 <= len(value['files']) <= MAX_FILES,
                 'Invalid cache artifact manifest extent')
        for row in value['files']:
            _require(type(row) is dict and set(row) == {'name','bytes','sha256','executable'},
                     'Cache artifact fields differ')
            _name(row['name'])
            _require(type(row['bytes']) is int and 0 <= row['bytes'] <= 2**63-1 and
                     type(row['sha256']) is str and _DIGEST.fullmatch(row['sha256']) is not None and
                     type(row['executable']) is bool, 'Invalid cache artifact metadata')
        actual, identities = _scan(self.entry, manifest=True)
        _require(value['files'] == actual, 'Cache artifact hashes, sizes, modes or names differ')
        _require(_stamp(_regular(self.entry/'manifest.json')) == manifest_stamp,
                 'Cache manifest changed during package verification')
        return value, (manifest_stamp, identities)

    def _current(self):
        current = self._verify()
        _require(current == self._baseline, 'Cache entry changed during held session')
        return current

    def restore(self, destination_dir: Path) -> dict | None:
        destination = Path(os.path.abspath(destination_dir))
        _directory(destination.parent)
        _require(not _exists(destination), 'Cache restore requires a new destination')
        current = self._current()
        if current is None:
            return None
        value = current[0]
        staging = Path(tempfile.mkdtemp(prefix='.'+destination.name+'.cache-', dir=destination.parent))
        identity, owned = _id(_directory(staging)), {}
        try:
            for row in value['files']:
                target = staging/row['name']
                copied, _ = _file(self.entry/row['name'], target, owned)
                _require(copied == row, 'Cache source changed while copying')
            copied, _ = _scan(staging)
            _require(copied == value['files'], 'Restored cache package differs')
            self._current()
            _directory(destination.parent)
            _require(not _exists(destination), 'Cache restore destination appeared')
            _rename_new(staging, destination)
            restored, _ = _scan(destination)
            _require(restored == value['files'], 'Published restore changed')
            return _json(_canonical(value))
        finally:
            _cleanup_owned(staging, identity, owned)

    def publish(self, package_dir: Path) -> dict:
        current = self._current()
        package = Path(os.path.abspath(package_dir))
        _require(package != self.entry, 'Publish requires a separate package directory')
        files, package_identity = _scan(package)
        value = dict(schema=1, kind='pce-build-package', key=self.key,
                     contract=_json(self._contract_bytes), files=files)
        raw = _canonical(value)+b'\n'
        _require(len(raw) <= MAX_MANIFEST_BYTES, 'Cache manifest exceeds bound')
        if current is not None:
            _require(current[0] == value, 'Existing immutable cache entry differs from package')
            self._current()
            return _json(_canonical(value))
        staging = Path(tempfile.mkdtemp(prefix='.'+self.key+'.publish-', dir=self.root))
        identity, owned = _id(_directory(staging)), {}
        try:
            for row in files:
                target = staging/row['name']
                copied, _ = _file(package/row['name'], target, owned)
                _require(copied == row, 'Publish source changed while copying')
            copied, _ = _scan(staging)
            _require(copied == files and _scan(package) == (files, package_identity),
                     'Publish package changed during copying')
            manifest = staging/'manifest.json'
            with manifest.open('xb') as stream:
                owned['manifest.json'] = _id(os.fstat(stream.fileno()))
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self._current()
            _require(not _exists(self.entry), 'Cache publication destination appeared')
            _rename_new(staging, self.entry)
            self._baseline = self._verify()
            _require(self._baseline[0] == value, 'Published cache entry differs')
            return _json(_canonical(value))
        finally:
            _cleanup_owned(staging, identity, owned)

    def __exit__(self, kind, error, traceback):
        if self._lock is not None:
            try:
                if self._active:
                    if os.name == 'nt':
                        import msvcrt
                        self._lock.seek(0)
                        msvcrt.locking(self._lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self._lock.fileno(), fcntl.LOCK_UN)
            finally:
                self._active = False
                self._lock.close()
                self._lock = None
