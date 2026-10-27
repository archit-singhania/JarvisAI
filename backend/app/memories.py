"""User-controlled memory provenance. No inference or automatic memory creation."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from app.workspace import timestamp


def metadata(value):
    return {"version": 1, "origin": "source_unavailable", "source": None,
            "scope": "workspace", "conversation_id": None,
            "last_confirmed_at": None, "expires_at": None, **value}


def eligible(value, conversation_id=None):
    value = metadata(value)
    if value['scope'] == 'conversation' and value['conversation_id'] != conversation_id:
        return False
    if value['expires_at']:
        try:
            expires = datetime.fromisoformat(value['expires_at'].replace('Z', '+00:00'))
            if not expires.tzinfo or expires <= datetime.now(timezone.utc):
                return False
        except (ValueError, TypeError):
            return False
    return True


class Memories:
    def __init__(self, store):
        self.store = store

    def save(self, owner, data, identity=None):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = None
            if identity:
                old = db.execute("SELECT * FROM records WHERE id=? AND owner=? AND kind='memory'", (identity, owner)).fetchone()
                if not old:
                    raise KeyError(identity)
            previous = metadata(json.loads(old['metadata'])) if old else None
            if previous and data.get('expected_version') not in (None, previous['version']):
                raise HTTPException(409, 'Memory changed. Reload and reconcile your edit before saving.')
            if previous and any(data.get(k) is not None for k in ('origin', 'source_message_id', 'source_conversation_id')):
                raise HTTPException(422, 'Corrections preserve the original provenance. Create a new memory for a different source.')
            value = dict(previous) if previous else metadata({})
            if not previous:
                origin = data.get('origin') or 'explicit_user'
                value['origin'] = origin
                if origin in ('selected_conversation', 'approved_suggestion'):
                    source = db.execute('SELECT m.* FROM messages m JOIN conversations c ON c.id=m.conversation WHERE m.id=? AND c.id=? AND c.owner=?', (data.get('source_message_id'), data.get('source_conversation_id'), owner)).fetchone()
                    if not source:
                        raise KeyError('Source message')
                    if origin == 'approved_suggestion' and (source['role'] != 'assistant' or data.get('confirmed') is not True):
                        raise HTTPException(422, 'Approve a selected assistant message explicitly before saving a suggestion.')
                    value['source'] = {'conversation_id': source['conversation'], 'message_id': source['id'], 'role': source['role'], 'sha256': hashlib.sha256(source['content'].encode()).hexdigest()}
                elif data.get('source_message_id') is not None or data.get('source_conversation_id'):
                    raise HTTPException(422, 'Choose a conversation origin when attaching a source.')
            if data.get('scope') is not None:
                value['scope'] = data['scope']
            if 'conversation_id' in data:
                value['conversation_id'] = data['conversation_id']
            if value['scope'] == 'conversation':
                if not db.execute('SELECT 1 FROM conversations WHERE id=? AND owner=?', (value['conversation_id'], owner)).fetchone():
                    raise KeyError('Scope conversation')
            else:
                value['conversation_id'] = None
            if 'expires_at' in data:
                expiry = data['expires_at']
                if expiry:
                    try:
                        parsed = datetime.fromisoformat(expiry.replace('Z', '+00:00'))
                        if not parsed.tzinfo:
                            raise ValueError()
                        expiry = parsed.astimezone(timezone.utc).isoformat()
                    except (ValueError, TypeError):
                        raise HTTPException(422, 'Expiry requires an ISO timestamp with timezone, or no expiry.')
                value['expires_at'] = expiry or None
            value['last_confirmed_at'] = timestamp()
            value['version'] = previous['version'] + 1 if previous else 1
            identity = identity or uuid4().hex
            if old:
                # Preserve an existing pre-provenance record honestly before its first correction.
                db.execute('INSERT OR IGNORE INTO memory_revisions VALUES(?,?,?,?,?,?)', (identity, previous['version'], old['title'], old['content'], json.dumps(previous), old['created_at']))
                db.execute('UPDATE records SET title=?,content=?,metadata=? WHERE id=?', (data['title'], data['content'], json.dumps(value), identity))
            else:
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?)', (identity, owner, 'memory', data['title'], data['content'], json.dumps(value), timestamp()))
            db.execute('INSERT INTO memory_revisions VALUES(?,?,?,?,?,?)', (identity, value['version'], data['title'], data['content'], json.dumps(value), timestamp()))
        return {'id': identity, 'version': value['version']}

    def inspect(self, owner, identity):
        with self.store.db() as db:
            row = db.execute("SELECT * FROM records WHERE id=? AND owner=? AND kind='memory'", (identity, owner)).fetchone()
            if not row:
                raise KeyError(identity)
            current = dict(row)
            current['metadata'] = metadata(json.loads(current['metadata']))
            rows = db.execute('SELECT * FROM memory_revisions WHERE memory_id=? ORDER BY version', (identity,)).fetchall()
            history = [{**dict(r), 'metadata': json.loads(r['metadata'])} for r in rows]
            if not history:
                history = [{'version': 1, 'title': current['title'], 'content': current['content'], 'metadata': current['metadata'], 'recorded_at': current['created_at']}]
            source = current['metadata']['source']
            source_message = None
            if source:
                found = db.execute('SELECT m.id,m.conversation,m.role,m.content,m.created_at FROM messages m JOIN conversations c ON c.id=m.conversation WHERE m.id=? AND c.id=? AND c.owner=?', (source['message_id'], source['conversation_id'], owner)).fetchone()
                if found:
                    source_message = dict(found)
            return {'memory': current, 'revisions': history, 'source_message': source_message,
                    'source_status': 'available' if source_message else 'unavailable' if source else 'not_attached'}

    def export(self, owner):
        return [self.inspect(owner, row['id']) for row in self.store.records(owner, 'memory')]
