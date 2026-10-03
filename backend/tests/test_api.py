from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest
from app import main
from app.workspace import Workspace
from app.llm.client import LLMClient


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


def test_selected_context_is_cleared_explicitly_and_on_new_conversation(client,monkeypatch):
    prompts=[]
    async def stream(self,*args,**kwargs):
        prompts.append(kwargs['system_prompt'])
        yield 'A fixture response.'
    monkeypatch.setattr(LLMClient,'stream_response',stream)
    client.post('/api/session')
    with client.websocket_connect('/ws') as socket:
        socket.receive_json()
        socket.send_json({'type':'code_context','file':'private.py','content':'sensitive_marker'})
        assert socket.receive_json()['type']=='context_updated'
        def ask():
            socket.send_json({'type':'text','content':'Explain'})
            while socket.receive_json()['type']!='stream_end':pass
        ask();assert 'sensitive_marker' in prompts[-1]
        socket.send_json({'type':'code_context','file':'','content':''});socket.receive_json()
        ask();assert 'sensitive_marker' not in prompts[-1]
        socket.send_json({'type':'code_context','file':'private.py','content':'sensitive_marker'});socket.receive_json()
        socket.send_json({'type':'clear'});assert socket.receive_json()['type']=='cleared'
        ask();assert 'sensitive_marker' not in prompts[-1]


def test_request_ids_structured_errors_and_timezone_preferences(client):
    denied=client.get('/api/memories',headers={'X-Request-ID':'manual-check-42'})
    assert denied.status_code==401
    assert denied.headers['X-Request-ID']=='manual-check-42'
    assert denied.json()['error']['request_id']=='manual-check-42'
    assert denied.json()['error']['code']=='http_401'
    client.post('/api/session')
    assert client.patch('/api/preferences',json={'timezone':'Europe/London','persona':'Explain tradeoffs.'}).status_code==200
    assert client.get('/api/preferences').json()['timezone']=='Europe/London'
    invalid=client.patch('/api/preferences',json={'timezone':'not-a-zone'})
    assert invalid.status_code==422 and invalid.json()['detail'].startswith('Choose a valid')
    assert invalid.json()['error']['request_id']==invalid.headers['X-Request-ID']
    malformed=client.post('/api/reminders',json={'text':''})
    assert malformed.json()['error']['code']=='invalid_request'


@pytest.mark.parametrize('zone',['/invalid',' ','','../Europe/London'])
def test_invalid_timezone_is_structured_and_does_not_replace_preferences(client,zone):
    client.post('/api/session')
    previous=client.get('/api/preferences').json()['timezone']
    response=client.patch('/api/preferences',json={'timezone':zone},headers={'X-Request-ID':'timezone-validation'})
    assert response.status_code==422
    assert response.json()['error']['request_id']==response.headers['X-Request-ID']=='timezone-validation'
    assert client.get('/api/preferences').json()['timezone']==previous


def test_wake_listener_stop_is_private(client,monkeypatch):
    class Listener:
        stopped=False
        def stop(self):self.stopped=True
    client.post('/api/session')
    identity=main.store.authenticate(client.cookies['wednesday_token'])
    listener=Listener()
    monkeypatch.setattr(main,'wake_listener',listener)
    monkeypatch.setattr(main,'wake_owner',identity)
    client.cookies.clear();client.post('/api/session')
    assert client.post('/api/wake-word/stop').status_code==403
    assert not listener.stopped
    monkeypatch.setattr(main,'wake_owner',main.store.authenticate(client.cookies['wednesday_token']))
    assert client.post('/api/wake-word/stop').status_code==200 and listener.stopped


@pytest.mark.parametrize('failed_start',[True,False])
def test_cancelled_wake_start_cannot_clear_another_owners_listener(client,monkeypatch,failed_start):
    import threading
    import sys
    import types
    entered=threading.Event(); release=threading.Event(); created=[]
    class Listener:
        def __init__(self,callback):
            self.number=len(created); created.append(self)
        def start(self):
            if self.number==0:
                entered.set()
                if not release.wait(5):raise RuntimeError('Fixture startup timed out')
                if failed_start:raise RuntimeError('Fixture startup failed')
        def stop(self):pass
    module=types.ModuleType('app.speech.wake_word'); module.WakeWordListener=Listener
    monkeypatch.setitem(sys.modules,'app.speech.wake_word',module)
    original_find_spec=main.importlib.util.find_spec
    monkeypatch.setattr(main.importlib.util,'find_spec',lambda name:object() if name in {'openwakeword','pyaudio'} else original_find_spec(name))
    monkeypatch.setattr(main.settings,'DEMO_MODE',False)
    monkeypatch.setattr(main,'wake_listener',None); monkeypatch.setattr(main,'wake_owner',None)
    first=client.post('/api/session').json()['token']; client.cookies.clear()
    second=client.post('/api/session').json()['token']; client.cookies.clear()
    responses=[]
    worker=threading.Thread(target=lambda:responses.append(client.post('/api/wake-word/start',headers={'Authorization':'Bearer '+first})))
    worker.start()
    try:
        assert entered.wait(3)
        assert client.post('/api/wake-word/stop',headers={'Authorization':'Bearer '+first}).status_code==200
        assert client.post('/api/wake-word/start',headers={'Authorization':'Bearer '+second}).status_code==200
    finally:
        release.set(); worker.join(5)
    assert responses[0].status_code==(503 if failed_start else 409)
    assert main.wake_listener is created[1]
    assert main.wake_owner==main.store.authenticate(second)
