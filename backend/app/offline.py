"""Idempotent local edits; never replays tools or external writes."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import HTTPException
from app.workspace import timestamp


class Offline:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS local_edits(owner TEXT NOT NULL,id TEXT NOT NULL,kind TEXT NOT NULL,value TEXT NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(owner,id));
            CREATE TABLE IF NOT EXISTS offline_operations(owner TEXT NOT NULL,id TEXT NOT NULL,fingerprint TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(owner,id));
            ''')

    def list(self, owner):
        with self.store.db() as db:
            return [dict(r, value=json.loads(r['value'])) for r in db.execute('SELECT * FROM local_edits WHERE owner=?', (owner,))]

    def apply(self, owner, body):
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM offline_operations WHERE owner=? AND id=?', (owner, body['operation_id'])).fetchone()
            if prior:
                if prior['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'Operation ID was already used with different content')
                return json.loads(prior['result'])
            current = db.execute('SELECT * FROM local_edits WHERE owner=? AND id=?', (owner, body['id'])).fetchone()
            revision = current['revision'] if current else 0
            memory = None
            if body['kind'] == 'memory':
                from app.memories import metadata
                memory = db.execute("SELECT * FROM records WHERE id=? AND owner=? AND kind='memory'", (body['id'], owner)).fetchone()
                if not memory:
                    raise HTTPException(404, 'Memory unavailable; offline edits cannot create implicit memories')
                previous = metadata(json.loads(memory['metadata']))
                revision = previous['version']
            if revision != body['expected_revision']:
                actual = {'value': {'title': memory['title'], 'content': memory['content']}, 'revision': revision} if memory else (dict(current, value=json.loads(current['value'])) if current else None)
                return {'status': 'conflicted', 'submitted': body, 'current': actual}
            if current and current['kind'] != body['kind']:
                raise HTTPException(409, 'Record type cannot change')
            value = body['value']
            if memory:
                db.execute('INSERT OR IGNORE INTO memory_revisions VALUES(?,?,?,?,?,?)', (body['id'],revision,memory['title'],memory['content'],json.dumps(previous),memory['created_at']))
                previous.update(version=revision+1,last_confirmed_at=timestamp())
                db.execute('UPDATE records SET title=?,content=?,metadata=? WHERE id=? AND owner=?',(value['title'],value['content'],json.dumps(previous),body['id'],owner))
                db.execute('INSERT INTO memory_revisions VALUES(?,?,?,?,?,?)',(body['id'],revision+1,value['title'],value['content'],json.dumps(previous),timestamp()))
            if body['kind'] == 'note':
                identity = hashlib.sha256((owner + ':note:' + body['id']).encode()).hexdigest()
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,content=excluded.content', (identity,owner,'document',value['title'],value['content'],json.dumps({'bytes':len(value['content'].encode()),'origin':'offline_note'}),timestamp()))
            if body['kind'] == 'reminder':
                due = datetime.fromisoformat(value['due_at'].replace('Z', '+00:00'))
                if not due.tzinfo:
                    raise HTTPException(422, 'Reminder requires an explicit UTC offset')
                identity = hashlib.sha256((owner + ':' + body['id']).encode()).hexdigest()
                db.execute("INSERT INTO reminders VALUES(?,?,?,?,?,'scheduled') ON CONFLICT(id) DO UPDATE SET text=excluded.text,due_at=excluded.due_at,timezone=excluded.timezone,status='scheduled'", (identity, owner, value['content'], due.astimezone(timezone.utc).isoformat(), 'UTC'))
            db.execute('INSERT INTO local_edits VALUES(?,?,?,?,?) ON CONFLICT(owner,id) DO UPDATE SET value=excluded.value,revision=excluded.revision', (owner, body['id'], body['kind'], json.dumps(value), revision+1))
            result = {'status': 'completed', 'id': body['id'], 'revision': revision+1}
            db.execute('INSERT INTO offline_operations VALUES(?,?,?,?,?)', (owner, body['operation_id'], fingerprint, json.dumps(result), timestamp()))
            return result
