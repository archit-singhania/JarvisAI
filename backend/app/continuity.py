"""Owned continuity resources. Additive schema; no changes to assistant history semantics."""
import json
from datetime import datetime, timezone
from uuid import uuid4

from app.workspace import timestamp


class Continuity:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS branches(
              conversation TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
              owner TEXT NOT NULL, parent TEXT NOT NULL, message_id INTEGER NOT NULL,
              snapshot TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS layouts(
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, client TEXT NOT NULL,
              title TEXT NOT NULL, value TEXT NOT NULL, revision INTEGER NOT NULL,
              updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS digests(
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, value TEXT NOT NULL, created_at TEXT NOT NULL);
            ''')

    def branch(self, owner, conversation, message_id, title):
        # Snapshot and copied history are committed together. No global memories are copied.
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            parent = db.execute('SELECT * FROM conversations WHERE id=? AND owner=?',
                                (conversation, owner)).fetchone()
            if not parent:
                raise KeyError(conversation)
            history = [dict(r) for r in db.execute(
                'SELECT * FROM messages WHERE conversation=? AND id<=? ORDER BY id',
                (conversation, message_id))]
            if not history or history[-1]['id'] != message_id:
                raise KeyError(message_id)
            identity, now = uuid4().hex, timestamp()
            db.execute('INSERT INTO conversations VALUES(?,?,?,?,?)',
                       (identity, owner, title, parent['mode'], now))
            for message in history:
                db.execute('INSERT INTO messages(conversation,role,content,sources,created_at) VALUES(?,?,?,?,?)',
                           (identity, message['role'], message['content'], message['sources'], message['created_at']))
            db.execute('INSERT INTO branches VALUES(?,?,?,?,?,?)',
                       (identity, owner, conversation, message_id, json.dumps(history), now))
        return self.store.conversation(owner, identity)

    def provenance(self, owner, conversation):
        self.store.conversation(owner, conversation)
        with self.store.db() as db:
            row = db.execute('SELECT * FROM branches WHERE conversation=? AND owner=?',
                             (conversation, owner)).fetchone()
            children = [dict(r) for r in db.execute(
                'SELECT conversation,message_id,created_at FROM branches WHERE parent=? AND owner=?',
                (conversation, owner))]
        parent = dict(row) if row else None
        if parent:
            parent['snapshot'] = json.loads(parent['snapshot'])
            for message in parent['snapshot']:
                message['sources'] = json.loads(message['sources'])
        return {'parent': parent, 'children': children}

    def layouts(self, owner, client):
        with self.store.db() as db:
            rows = [dict(r) for r in db.execute(
                'SELECT * FROM layouts WHERE owner=? AND client=? ORDER BY updated_at DESC', (owner, client))]
        for row in rows:
            row['value'] = json.loads(row['value'])
        return rows

    def layout(self, owner, client, identity, title, value, revision):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM layouts WHERE id=?', (identity,)).fetchone()
            if existing and (existing['owner'] != owner or existing['client'] != client):
                raise KeyError(identity)
            if (existing['revision'] if existing else 0) != revision:
                raise ValueError('Layout changed. Reload before saving.')
            db.execute('INSERT INTO layouts VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                       'title=excluded.title,value=excluded.value,revision=excluded.revision,updated_at=excluded.updated_at',
                       (identity, owner, client, title, json.dumps(value), revision + 1, timestamp()))
        return next(r for r in self.layouts(owner, client) if r['id'] == identity)

    def digest(self, owner, conversation_ids, reminder_ids, receipt_ids, since):
        # Inputs are explicit allowlists, never "all sessions" inferred from a query.
        items = []
        for identity in conversation_ids:
            conversation = self.store.conversation(owner, identity)
            history = self.store.history(owner, identity)
            for message in history:
                if message['created_at'] >= since:
                    items.append({'kind': 'conversation', 'source_id': identity, 'message_id': message['id'],
                                  'title': conversation['title'], 'text': message['content'][:600],
                                  'created_at': message['created_at'], 'role': message['role']})
        for kind, identities, records in (
            ('reminder', reminder_ids, self.store.reminders(owner)),
            ('receipt', receipt_ids, self.store.receipts(owner))):
            available = {r['id']: r for r in records}
            for identity in identities:
                if identity not in available:
                    raise KeyError(identity)
                row = available[identity]
                created = row.get('created_at', row.get('due_at'))
                if created >= since:
                    items.append({'kind': kind, 'source_id': identity, 'title': row.get('tool', kind),
                                  'text': row.get('text', json.dumps(row.get('result', {})))[:600],
                                  'created_at': created})
        items.sort(key=lambda r: r['created_at'], reverse=True)
        value = {'version': 1, 'method': 'deterministic excerpts', 'partial_coverage': True,
                 'coverage': 'Only selected sources; excerpts limited to 600 characters, newest 300 items.',
                 'selection': {'conversations': conversation_ids, 'reminders': reminder_ids, 'receipts': receipt_ids},
                 'since': since, 'items': items[:300], 'omitted_items': max(0, len(items)-300)}
        identity, now = uuid4().hex, timestamp()
        with self.store.db() as db:
            db.execute('INSERT INTO digests VALUES(?,?,?,?)', (identity, owner, json.dumps(value), now))
        return {'id': identity, 'created_at': now, **value}

    def digests(self, owner):
        with self.store.db() as db:
            return [{'id': r['id'], 'created_at': r['created_at'], **json.loads(r['value'])}
                    for r in db.execute('SELECT * FROM digests WHERE owner=? ORDER BY created_at DESC LIMIT 50', (owner,))]
