"""Opt-in raw development-protocol evidence; private files, never replay commands."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path


class JournalError(OSError):
    """A journal cannot durably retain another record; stop its connection."""


class WireJournal:
    """Exclusive per-connection JSONL file, flushed and fsynced per record.

    A request is an intent, not proof of delivery. A response is raw evidence,
    not proof of protocol, semantic or gameplay acceptance. No append/replay or
    automatic filename replacement is provided. Keep journals private: they may
    contain memory bytes, screenshots and command arguments.
    """

    def __init__(self, path, *, host, port):
        self._stream = None
        self._failed = False
        self._sequence = 0
        self._stream = Path(path).open('xb', buffering=0)
        try:
            self.record('session', host=host, port=port)
        except BaseException:
            self.close()
            raise

    def record(self, event, **fields):
        if self._stream is None or self._failed:
            raise JournalError('wire journal is closed or failed')
        value = dict(schema=1, sequence=self._sequence, event=event, **fields)
        data = (json.dumps(value, ensure_ascii=True, allow_nan=False,
                           separators=(',', ':')) + '\n').encode('ascii')
        try:
            view = memoryview(data)
            while view:
                count = self._stream.write(view)
                if count is None or count <= 0:
                    raise OSError('wire journal write made no progress')
                view = view[count:]
            self._stream.flush()
            os.fsync(self._stream.fileno())
        except OSError as error:
            self._failed = True
            raise JournalError('wire journal write/flush/fsync failed') from error
        self._sequence += 1

    def wire(self, event, identity, data):
        self.record(event, request_id=identity,
                    wire_base64=base64.b64encode(data).decode('ascii'))

    def failure(self, identity, error, partial=b'', *, phase='request'):
        self.record('failure', request_id=identity, phase=phase,
                    error_type=type(error).__name__, error=str(error),
                    partial_base64=base64.b64encode(partial).decode('ascii'))

    def close(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.close()
