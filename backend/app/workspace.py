"""Owned, durable local workspaces. No models or network required to store work."""
import hashlib
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Workspace:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS owners(id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'assistant', created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, conversation TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reminders(id TEXT PRIMARY KEY, owner TEXT NOT NULL, text TEXT NOT NULL, due_at TEXT NOT NULL, timezone TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'scheduled');
            CREATE TABLE IF NOT EXISTS preferences(owner TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, owner TEXT NOT NULL, tool TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS owned_conversations ON conversations(owner,created_at);
            CREATE INDEX IF NOT EXISTS owned_records ON records(owner,kind);
            ''')

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_owner(self):
        token, owner = secrets.token_urlsafe(32), uuid4().hex
        with self.db() as db:
            db.execute('INSERT INTO owners VALUES(?,?,?)', (owner, hashlib.sha256(token.encode()).hexdigest(), timestamp()))
        return owner, token

    def authenticate(self, token):
        if not token or len(token) > 200:
            return None
        with self.db() as db:
            row = db.execute('SELECT id FROM owners WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        return row['id'] if row else None

    def conversation(self, owner, conversation_id=None, title='New conversation', mode='assistant'):
        with self.db() as db:
            if conversation_id:
                row = db.execute('SELECT * FROM conversations WHERE id=? AND owner=?', (conversation_id, owner)).fetchone()
                if not row:
                    raise KeyError('Conversation not found')
                return dict(row)
            identity = uuid4().hex
            db.execute('INSERT INTO conversations VALUES(?,?,?,?,?)', (identity, owner, title[:100], mode, timestamp()))
            return dict(db.execute('SELECT * FROM conversations WHERE id=?', (identity,)).fetchone())

    def conversations(self, owner, query=''):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT DISTINCT c.* FROM conversations c LEFT JOIN messages m ON m.conversation=c.id WHERE c.owner=? AND (c.title LIKE ? OR m.content LIKE ?) ORDER BY c.created_at DESC LIMIT 100', (owner, f'%{query}%', f'%{query}%'))]

    def history(self, owner, identity):
        self.conversation(owner, identity)
        with self.db() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM messages WHERE conversation=? ORDER BY id', (identity,))]
        for row in rows:
            row['sources'] = json.loads(row['sources'])
        return rows

    def message(self, owner, identity, role, content, sources=None):
        self.conversation(owner, identity)
        with self.db() as db:
            db.execute('INSERT INTO messages(conversation,role,content,sources,created_at) VALUES(?,?,?,?,?)', (identity, role, content, json.dumps(sources or []), timestamp()))
            if role == 'user':
                db.execute("UPDATE conversations SET title=? WHERE id=? AND title='New conversation'", (content[:70], identity))

    def delete_conversation(self, owner, identity):
        self.conversation(owner, identity)
        with self.db() as db:
            db.execute('DELETE FROM conversations WHERE id=? AND owner=?', (identity, owner))

    def records(self, owner, kind=None):
        with self.db() as db:
            rows = db.execute('SELECT * FROM records WHERE owner=? AND (? IS NULL OR kind=?) ORDER BY created_at DESC LIMIT 500', (owner, kind, kind))
            result = [dict(r) for r in rows]
        for row in result:
            row['metadata'] = json.loads(row['metadata'])
        return result

    def save_record(self, owner, kind, title, content, metadata=None, identity=None):
        identity = identity or uuid4().hex
        with self.db() as db:
            existing = db.execute('SELECT owner FROM records WHERE id=?', (identity,)).fetchone()
            if existing and existing['owner'] != owner:
                raise KeyError('Record not found')
            db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,content=excluded.content,metadata=excluded.metadata', (identity, owner, kind, title[:200], content, json.dumps(metadata or {}), timestamp()))
        return identity

    def delete_record(self, owner, identity):
        with self.db() as db:
            return db.execute('DELETE FROM records WHERE id=? AND owner=?', (identity, owner)).rowcount > 0

    def retrieve(self, owner, query, limit=3):
        words = set(re.findall(r'\w+', query.lower())) - {'the', 'is', 'a', 'of', 'and', 'to', 'what', 'my'}
        ranked = []
        for record in self.records(owner):
            if record['kind'] not in ('document', 'memory'):
                continue
            for offset in range(0, len(record['content']), 1200):
                chunk = record['content'][offset:offset+1500]
                matched = words.intersection(re.findall(r'\w+', chunk.lower()))
                if matched:
                    ranked.append((len(matched), {'id': record['id'], 'title': record['title'], 'content': chunk, 'offset': offset}))
        return [r[1] for r in sorted(ranked, key=lambda x: x[0], reverse=True)[:limit]]

    def prefs(self, owner, patch=None):
        defaults = {'theme': 'system', 'palette': 'amethyst', 'reduce_motion': False, 'reduce_transparency': False, 'high_contrast': False, 'focus': 'assistant', 'persona':'', 'language': 'en', 'timezone':'Asia/Kolkata', 'tts': False, 'llm_provider':'ollama', 'llm_model':'llama-3.1-8b-instant', 'ollama_model':'llama3.1:8b'}
        with self.db() as db:
            row = db.execute('SELECT value FROM preferences WHERE owner=?', (owner,)).fetchone()
            defaults.update(json.loads(row['value']) if row else {})
            if patch:
                defaults.update({k:v for k,v in patch.items() if k in defaults})
                db.execute('INSERT INTO preferences VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET value=excluded.value', (owner,json.dumps(defaults)))
        return defaults

    def add_reminder(self, owner, text, due_at, zone):
        due = datetime.fromisoformat(due_at.replace('Z','+00:00'))
        if not due.tzinfo:
            from zoneinfo import ZoneInfo
            zone_info = ZoneInfo(zone)
            due = due.replace(tzinfo=zone_info)
            # A round trip rejects nonexistent local times during a DST jump.
            if due.astimezone(timezone.utc).astimezone(zone_info).replace(tzinfo=None)!=due.replace(tzinfo=None):
                raise ValueError('Local time does not exist in the selected timezone')
        identity = uuid4().hex
        with self.db() as db:
            db.execute('INSERT INTO reminders(id,owner,text,due_at,timezone) VALUES(?,?,?,?,?)', (identity,owner,text,due.astimezone(timezone.utc).isoformat(),zone))
        return identity

    def reminders(self, owner):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM reminders WHERE owner=? ORDER BY due_at', (owner,))]

    def cancel_reminder(self, owner, identity):
        with self.db() as db:
            return db.execute("UPDATE reminders SET status='cancelled' WHERE id=? AND owner=? AND status='scheduled'", (identity,owner)).rowcount > 0

    def due_reminders(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM reminders WHERE due_at<=? AND status='scheduled'", (timestamp(),))]

    def acknowledge_reminder(self, owner, identity):
        with self.db() as db:
            return db.execute("UPDATE reminders SET status='delivered' WHERE id=? AND owner=? AND status='scheduled'", (identity, owner)).rowcount > 0

    def receipt(self, owner, tool, result):
        identity = uuid4().hex
        with self.db() as db:
            db.execute('INSERT INTO receipts VALUES(?,?,?,?,?)', (identity,owner,tool,json.dumps(result),timestamp()))
        return identity

    def receipts(self, owner):
        with self.db() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM receipts WHERE owner=? ORDER BY created_at DESC LIMIT 100', (owner,))]
        for row in rows:
            row['result'] = json.loads(row['result'])
        return rows

    def export(self, owner):
        conversations = self.conversations(owner)
        return {'version':1, 'exported_at':timestamp(), 'conversations':[{**c,'messages':self.history(owner,c['id'])} for c in conversations], 'records':self.records(owner), 'reminders':self.reminders(owner), 'preferences':self.prefs(owner), 'receipts':self.receipts(owner)}
