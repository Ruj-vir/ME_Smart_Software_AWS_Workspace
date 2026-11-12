"""ONLYOFFICE coordination for the single-process backend.

Session keys and acknowledged force-save copies survive backend restarts. The
per-document export lock is deliberately separate from the callback lock: a
worker waiting for a callback must never prevent that callback from running.
"""
from contextlib import contextmanager
from hashlib import md5
from pathlib import Path
import sqlite3
from threading import Event, Lock, RLock
from uuid import uuid4


class OfficeSaveError(RuntimeError):
    pass


class OfficeSessions:
    def __init__(self, database, timeout=90):
        self.database = str(database)
        self.timeout = timeout
        self.guard = Lock()
        self.locks = {}
        self.export_locks = {}
        self.pending = {}
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS sessions (
                name TEXT PRIMARY KEY, key TEXT NOT NULL, state TEXT NOT NULL,
                uncertain INTEGER NOT NULL DEFAULT 0, data BLOB, filetype TEXT,
                source_etag TEXT, revision INTEGER NOT NULL DEFAULT 0
            )''')

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.database, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def lock(self, name, export=False):
        with self.guard:
            locks = self.export_locks if export else self.locks
            return locks.setdefault(name, RLock())

    def state(self, name):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM sessions WHERE name=?', (name,)).fetchone()
            return dict(row) if row else None

    def key(self, name, etag):
        with self.lock(name):
            state = self.state(name)
            if (state and state['state'] != 'saved'
                    and not (state['state'] in ('new', 'idle')
                             and state['source_etag'] != etag)):
                return state['key']
            # Adopt the previous integration's key on first use so already-open
            # editors can finish saving during a rolling backend replacement.
            key = (uuid4().hex if state else
                   md5(f'{name}:{etag}'.encode(), usedforsecurity=False).hexdigest())
            with self.connection() as conn:
                conn.execute('INSERT OR REPLACE INTO sessions(name,key,state,source_etag) VALUES(?,?,?,?)',
                             (name, key, 'new', etag))
            return key

    def source(self, name, read):
        # A force-save copy is durable even before the final storage write.
        # Document Server may request the source again after its own restart.
        with self.lock(name):
            state = self.state(name)
            if state and state['data'] is not None:
                return state['data'], state['filetype']
            return read(), name.rsplit('.', 1)[-1].lower()

    def callback(self, name, body, download, save, legacy_etag):
        key, status = body.get('key'), body.get('status')
        if not key or status not in (1, 2, 3, 4, 6, 7):
            raise OfficeSaveError('Invalid ONLYOFFICE callback')
        with self.lock(name):
            state = self.state(name)
            if state is None:
                self.key(name, legacy_etag())
                state = self.state(name)
            if state['key'] != key:
                raise OfficeSaveError('Callback belongs to an older editing session')
            if state['state'] == 'saved':
                # Final save wins over every delayed force-save callback.
                return
            request_id = body.get('userdata')
            pending = self.pending.get(request_id) if isinstance(request_id, str) else None
            if pending and (pending['name'], pending['key']) != (name, key):
                pending = None
            if status in (3, 7):
                with self.connection() as conn:
                    conn.execute('UPDATE sessions SET uncertain=1, revision=revision+1 WHERE name=?', (name,))
                if pending:
                    pending['error'] = 'ONLYOFFICE could not save the document'
                    pending['event'].set()
                return
            if status == 1:
                with self.connection() as conn:
                    conn.execute("UPDATE sessions SET state='editing' WHERE name=?", (name,))
                return
            if status == 4:
                # No edits: this key can be reused, including reconnects.
                with self.connection() as conn:
                    conn.execute("UPDATE sessions SET state='idle' WHERE name=?", (name,))
                return
            own_export = (status == 6 and isinstance(request_id, str)
                          and request_id.startswith('me-export:'))
            if own_export and not pending:
                # Timed-out/restarted requests must not overwrite newer data.
                return
            try:
                if not body.get('url'):
                    raise OfficeSaveError('Save callback is missing the document URL')
                data = download(body['url'])
                if not data:
                    raise OfficeSaveError('ONLYOFFICE returned an empty document')
                filetype = body.get('filetype') or name.rsplit('.', 1)[-1].lower()
                if not own_export:
                    save(data)
                with self.connection() as conn:
                    conn.execute('''UPDATE sessions SET state=?, uncertain=?,
                                    data=?, filetype=?, revision=revision+1 WHERE name=?''',
                                 ('saved' if status == 2 else 'editing',
                                  int(status == 6 and not own_export),
                                  data if own_export else None, filetype, name))
                    # Unsolicited force saves have no ordering token. They may
                    # arrive after a newer export; require fresh confirmation
                    # before reusing a cached copy on command error=4.
                if pending:
                    pending['result'] = (data, filetype)
                    pending['event'].set()
                if status == 2:
                    # Closing the editor can race the force-save request. Its
                    # final save is also a confirmed snapshot for this key.
                    for waiting in list(self.pending.values()):
                        if (waiting['name'], waiting['key']) == (name, key):
                            waiting['result'] = (data, filetype)
                            waiting['event'].set()
            except Exception as exc:
                with self.connection() as conn:
                    conn.execute('UPDATE sessions SET uncertain=1, revision=revision+1 WHERE name=?', (name,))
                if pending:
                    pending['error'] = str(exc)
                    pending['event'].set()
                raise

    def snapshot(self, name, etag, read, command):
        """Return immutable bytes, never silently fall back after a failed save."""
        with self.lock(name, export=True):
            with self.lock(name):
                state = self.state(name)
                if state and state['state'] == 'saved':
                    return read(), name.rsplit('.', 1)[-1].lower()
                key = self.key(name, etag())
                before = self.state(name)
                request_id = 'me-export:' + uuid4().hex
                pending = dict(name=name, key=key, event=Event(), result=None, error=None)
                self.pending[request_id] = pending
                # Persist before issuing the command. A restart/timeout cannot
                # accidentally turn an unacknowledged save into a safe fallback.
                with self.connection() as conn:
                    conn.execute('UPDATE sessions SET uncertain=1 WHERE name=?', (name,))
            try:
                error = command(key, request_id)
                if error in (1, 4):
                    with self.lock(name):
                        current = self.state(name)
                        if current['key'] != key:
                            raise OfficeSaveError('Editing session changed; generate again')
                        if current['state'] == 'saved':
                            return read(), name.rsplit('.', 1)[-1].lower()
                        # error=1 is only safe when this session never became
                        # active, or closed without edits. Do not hide DS loss.
                        if ((current['uncertain'] and (before['uncertain']
                                 or current['revision'] != before['revision']))
                                or (error == 1 and current['state'] == 'editing')):
                            raise OfficeSaveError('Cannot confirm the latest saved version; retry Generate')
                        with self.connection() as conn:
                            conn.execute('UPDATE sessions SET uncertain=0 WHERE name=?', (name,))
                        if current['data'] is not None:
                            return current['data'], current['filetype']
                        return read(), name.rsplit('.', 1)[-1].lower()
                if error != 0:
                    raise OfficeSaveError(f'ONLYOFFICE force-save failed (error {error})')
                if not pending['event'].wait(self.timeout):
                    raise OfficeSaveError('Timed out waiting for ONLYOFFICE to confirm saving; retry Generate')
                if pending['error']:
                    raise OfficeSaveError(pending['error'])
                return pending['result']
            finally:
                with self.lock(name):
                    self.pending.pop(request_id, None)


class SnapshotStore:
    """Short-lived, unguessable download handles; removed after conversion."""
    def __init__(self):
        self.lock = Lock()
        self.items = {}

    def add(self, data, filetype):
        token = uuid4().hex + uuid4().hex
        with self.lock:
            self.items[token] = (data, filetype)
        return token

    def get(self, token):
        with self.lock:
            return self.items.get(token)

    def remove(self, token):
        with self.lock:
            self.items.pop(token, None)
