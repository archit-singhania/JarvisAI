from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest
from app import main
from app.workspace import Workspace


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'store',Workspace(tmp_path/'isolated.db'))
    with TestClient(main.app) as client:
        yield client


def test_owned_roundtrip_upload_edit_and_export(client):
    assert client.get('/api/memories').status_code==401
    session=client.post('/api/session').json()
    conversation=client.post('/api/conversations',json={}).json()
    memory=client.post('/api/memories',json={'title':'Focus','content':'Violet is my project.'}).json()
    assert client.patch('/api/memories/'+memory['id'],json={'title':'Focus','content':'Violet uses Python.'}).status_code==200
    document=client.post('/api/documents',files={'file':('notes.md',b'Violet deployment evidence','text/markdown')})
    assert document.status_code==200
    assert client.get('/api/search?q=violet').json()['sources']
    assert client.get('/api/export').json()['records']
    client.cookies.clear();client.post('/api/session')
    assert client.get('/api/conversations/'+conversation['id']).status_code==404
    assert client.delete('/api/records/'+memory['id']).status_code==404
    assert client.get('/api/memories').json()['memories']==[]
    assert session['token'] not in str(client.get('/api/export').json())


def test_validation_diagnostics_permissions_and_workflow(client,monkeypatch):
    client.post('/api/session')
    assert client.post('/api/documents',files={'file':('bad.pdf',b'not a PDF')}).status_code==422
    assert client.post('/api/documents',files={'file':('bad.exe',b'payload')}).status_code==415
    diagnostics=client.post('/api/code/diagnostics',json={'code':'def missing(:','language':'python'}).json()
    assert diagnostics['diagnostics'][0]['severity']=='error'
    assert client.post('/api/tools/execute',json={'tool':'open_app','argument':'notepad'}).status_code==409
    monkeypatch.setattr(main.settings,'DEMO_MODE',True)
    assert client.post('/api/tools/execute',json={'tool':'open_app','argument':'notepad','confirmed':True}).status_code==403
    workflow=client.post('/api/workflows',json={'title':'Time check','steps':[{'tool':'time'}]}).json()
    result=client.post('/api/workflows/'+workflow['id']+'/run').json()
    assert result['results'][0]['success']
    assert client.get('/api/receipts').json()['receipts']
    assert client.post('/api/memories',json={'title':'x','content':'x'},headers={'Origin':'https://untrusted.example'}).status_code==403


def test_socket_rejects_unknown_owner_and_loads_saved_session(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws') as socket:
            socket.receive_json()
    client.post('/api/session')
    with client.websocket_connect('/ws') as socket:
        session=socket.receive_json()
        assert session['type']=='session' and session['version']==1
        socket.send_json({'type':'interrupt'})
        assert socket.receive_json()['type']=='interrupted'
        socket.send_json({'type':'audio','audio_b64':'invalid!'})
        assert socket.receive_json()['code']=='invalid_audio'
