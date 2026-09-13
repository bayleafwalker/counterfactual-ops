"""Append-only hash-chained events and content-addressed artifacts.

Git replication provides durability. This detects edits and missing referenced
artifacts, not an adversary rewriting the entire chain or truncating its tail;
compare against the committed ledger for those cases.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import uuid
from .model import canonical, digest, require


class Store:
    def __init__(self, root):
        self.root = Path(root)

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def read(self):
        with self.locked():
            return self._read()

    def _read(self):
        path = self.root / 'events.jsonl'
        events, previous = [], None
        if not path.exists():
            return events
        for line in path.read_bytes().splitlines():
            event = json.loads(line)
            signature = event.pop('hash')
            require(event['previous'] == previous and digest(event) == signature, 'ledger integrity failure')
            event['hash'] = signature
            for ref in event['data'].get('artifacts', []):
                self.artifact(ref)
            events.append(event)
            previous = signature
        return events

    def artifact(self, ref):
        require(isinstance(ref, str) and len(ref) == 64 and all(c in '0123456789abcdef' for c in ref), 'invalid artifact reference')
        data = (self.root / 'objects' / ref).read_bytes()
        require(hashlib.sha256(data).hexdigest() == ref, 'artifact integrity failure')
        return data

    def put(self, data):
        with self.locked():
            return self._put(data)

    def _put(self, data):
        ref = hashlib.sha256(data).hexdigest()
        objects = self.root / 'objects'
        objects.mkdir(parents=True, exist_ok=True)
        path = objects / ref
        try:
            with path.open('xb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except FileExistsError:
            self.artifact(ref)
        return ref

    def append(self, kind, data):
        with self.locked():
            events = self._read()
            event = {'id': uuid.uuid4().hex, 'time': datetime.now(timezone.utc).isoformat(), 'kind': kind,
                     'previous': events[-1]['hash'] if events else None, 'data': data}
            event['hash'] = digest(event)
            with (self.root / 'events.jsonl').open('ab') as f:
                f.write(canonical(event) + b'\n')
                f.flush()
                os.fsync(f.fileno())
            return event
