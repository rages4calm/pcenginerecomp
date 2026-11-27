"""Operation-local reuse of admitted project derivations, with fresh raw checks.

An epoch is a scoped capability, never a timestamp or persistent validation
cache. Every hit and successful scope exit rereads its admitted raw closure.
Package/compiler/permit verification remains the caller's responsibility.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import os
from pathlib import Path

from .snapshots import SnapshotStore


_current = ContextVar('pce_verified_input_epoch', default=None)


class VerifiedInputEpoch:
    def __init__(self):
        self._entries = {}
        self._closed = False
        self._failed = False

    def _active(self):
        if self._closed or self._failed:
            raise ValueError('Verified input epoch is closed or failed')

    def key(self, descriptor, allow_revision_override):
        self._active()
        return (os.path.abspath(os.fspath(descriptor)), allow_revision_override)

    def lookup(self, key):
        self._active()
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._validate(entry)
        return deepcopy(entry[0])

    def admit(self, key, checked, descriptor_store, callbacks):
        self._active()
        store = SnapshotStore()
        for name, path in checked['files'].items():
            store.bind(path, expected_sha256=checked['identities'][name])
        if 'title_adapter' in checked['config']:
            root = checked['files']['title_adapter_source'].parent
            members = {path for name, path in checked['files'].items()
                       if name.startswith('title_adapter_')}
            def title_membership():
                actual = set()
                for path in root.rglob('*'):
                    if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
                        raise ValueError('Title input graph contains a new link')
                    if path.is_file():
                        actual.add(path)
                if actual != members:
                    raise ValueError('Title input graph membership changed within epoch')
            callbacks = (*callbacks, title_membership)
        entry = (deepcopy(checked), descriptor_store, store, tuple(callbacks))
        self._validate(entry)
        self._entries[key] = entry

    def _validate(self, entry):
        try:
            checked, descriptor, files, callbacks = entry
            descriptor.revalidate()
            files.revalidate()
            for callback in callbacks:
                callback()
            from .project import source_identity
            if source_identity(checked['tool_root']) != checked['tool_identity']:
                raise ValueError('Tool source identity changed within verified input epoch')
            descriptor.revalidate()
        except BaseException:
            self._failed = True
            raise

    def revalidate(self):
        self._active()
        for entry in self._entries.values():
            self._validate(entry)


def current_epoch():
    epoch = _current.get()
    if epoch is not None:
        epoch._active()
    return epoch


@contextmanager
def verified_input_epoch():
    """Reuse parsed project graphs only inside this explicit operation scope.

    Nested scopes share the capability. Any escaping nested exception poisons
    it even if an outer caller catches that exception. A closed capability
    cannot be used again; no entry survives the outermost scope.
    """
    active = current_epoch()
    if active is not None:
        try:
            yield active
            active.revalidate()
        except BaseException:
            active._failed = True
            raise
        return
    epoch = VerifiedInputEpoch()
    token = _current.set(epoch)
    try:
        yield epoch
        epoch.revalidate()
    except BaseException:
        epoch._failed = True
        raise
    finally:
        epoch._closed = True
        epoch._entries.clear()
        _current.reset(token)
