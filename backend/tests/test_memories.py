from datetime import datetime, timedelta, timezone
import pytest
from fastapi import HTTPException
from app.workspace import Workspace
from app.memories import Memories


def test_legacy_correction_restart_stale_write_and_delete(tmp_path):
    path = tmp_path / 'owned.db'
    store = Workspace(path)
    owner, _ = store.create_owner()
    legacy = store.save_record(owner, 'memory', 'Legacy', 'violet original')
    service = Memories(store)
    assert service.inspect(owner, legacy)['memory']['metadata']['origin'] == 'source_unavailable'
    assert service.inspect(owner, legacy)['memory']['metadata']['last_confirmed_at'] is None
    service.save(owner, {'title': 'Corrected', 'content': 'violet revised', 'expected_version': 1}, legacy)
    service = Memories(Workspace(path))
    result = service.inspect(owner, legacy)
    assert [r['content'] for r in result['revisions']] == ['violet original', 'violet revised']
    with pytest.raises(HTTPException) as error:
        service.save(owner, {'title': 'Stale', 'content': 'bad', 'expected_version': 1}, legacy)
    assert error.value.status_code == 409
    assert store.delete_record(owner, legacy)
    assert not store.retrieve(owner, 'violet')
    with store.db() as db:
        assert db.execute('SELECT count(*) FROM memory_revisions').fetchone()[0] == 0


def test_source_scope_expiry_and_ownership(tmp_path):
    store = Workspace(tmp_path / 'owned.db')
    service = Memories(store)
    owner, _ = store.create_owner()
    other, _ = store.create_owner()
    chat = store.conversation(owner)['id']
    other_chat = store.conversation(other)['id']
    store.message(owner, chat, 'assistant', 'violet suggested preference')
    message = store.history(owner, chat)[0]
    payload = {'title': 'Preference', 'content': 'violet preference', 'origin': 'approved_suggestion',
               'source_conversation_id': chat, 'source_message_id': message['id'], 'scope': 'conversation', 'conversation_id': chat}
    with pytest.raises(HTTPException): service.save(owner, payload)
    with pytest.raises(KeyError): service.save(other, {**payload, 'confirmed': True})
    with pytest.raises(KeyError): service.save(owner, {**payload, 'confirmed': True, 'conversation_id': other_chat})
    identity = service.save(owner, {**payload, 'confirmed': True})['id']
    assert not store.retrieve(owner, 'violet')
    found = store.retrieve(owner, 'violet', conversation_id=chat)
    assert found[0]['memory_origin'] == 'approved_suggestion' and found[0]['memory_version'] == 1
    assert not store.retrieve(other, 'violet', conversation_id=chat)
    with pytest.raises(KeyError): service.inspect(other, identity)
    expires = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    service.save(owner, {'title': 'Preference', 'content': 'violet preference', 'expires_at': expires, 'expected_version': 1}, identity)
    assert not store.retrieve(owner, 'violet', conversation_id=chat)
    assert service.inspect(owner, identity)['source_status'] == 'available'
    store.delete_conversation(owner, chat)
    assert service.inspect(owner, identity)['source_status'] == 'unavailable'
    assert len(service.export(owner)[0]['revisions']) == 2


def test_api_contract_and_malformed_expiry(tmp_path, monkeypatch):
    from app import main
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, 'store', Workspace(tmp_path / 'api.db'))
    with TestClient(main.app) as client:
        client.post('/api/session')
        created = client.post('/api/memories', json={'title': 'Entry', 'content': 'violet user entry'}).json()
        detail = client.get('/api/memories/' + created['id']).json()
        assert detail['memory']['metadata']['origin'] == 'explicit_user'
        assert client.patch('/api/memories/' + created['id'], json={'title': 'Entry', 'content': 'x', 'expires_at': '2026-01-01T12:00:00'}).status_code == 422
        assert len(client.get('/api/memories/export').json()['memories']) == 1
        client.cookies.clear()
        client.post('/api/session')
        assert client.get('/api/memories/' + created['id']).status_code == 404
        assert client.get('/api/memories/export').json()['memories'] == []
