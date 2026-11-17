import json
import pytest
from fastapi import HTTPException
from app.workspace import Workspace
from app.offline import Offline
from app.planning import Planning
from app.watchfolders import WatchFolders
from app.evaluations import Evaluations


def setup(tmp_path):
    store=Workspace(tmp_path/'workspace.db')
    a,_=store.create_owner(); b,_=store.create_owner()
    return store,a,b


def test_offline_retry_conflict_restart_and_isolation(tmp_path):
    store,a,b=setup(tmp_path); service=Offline(store)
    body={'operation_id':'one','id':'note','kind':'note','expected_revision':0,'value':{'title':'Note','content':'violet evidence'}}
    result=service.apply(a,body)
    assert result==Offline(Workspace(store.path)).apply(a,body)
    assert len(store.retrieve(a,'violet'))==1
    assert not store.retrieve(b,'violet')
    conflict=service.apply(a,{**body,'operation_id':'two'})
    assert conflict['status']=='conflicted' and conflict['current']['revision']==1
    with pytest.raises(HTTPException): service.apply(a,{**body,'value':{'title':'Changed','content':'other'}})
    assert service.list(b)==[]


def test_offline_memory_preserves_provenance_and_reminder_is_single(tmp_path):
    from app.memories import Memories
    store,a,b=setup(tmp_path); service=Offline(store)
    memory=Memories(store).save(a,{'title':'Original','content':'violet','scope':'workspace'})
    body={'operation_id':'memory','id':memory['id'],'kind':'memory','expected_revision':1,'value':{'title':'Corrected','content':'violet corrected'}}
    assert service.apply(a,body)['revision']==2
    assert service.apply(a,body)['revision']==2
    assert Memories(store).inspect(a,memory['id'])['memory']['metadata']['origin']=='explicit_user'
    with pytest.raises(HTTPException):service.apply(b,body)
    reminder={**body,'kind':'reminder','id':'reminder','operation_id':'reminder','expected_revision':0,'value':{'title':'Check','content':'Review','due_at':'2027-01-01T10:00:00+05:30'}}
    service.apply(a,reminder);service.apply(a,reminder)
    assert len(store.reminders(a))==1


ICS='BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:fixture\r\nDTSTART:20270101T100000Z\r\nDTEND:20270101T110000Z\r\nSUMMARY:Meeting\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'


def test_calendar_import_roundtrip_proposal_stale_and_retry(tmp_path):
    store,a,b=setup(tmp_path); service=Planning(store)
    service.import_ics(a,ICS);service.import_ics(a,ICS)
    assert len(service.events(a))==1 and not service.events(b)
    proposal=service.propose(a,'Work','2027-01-01T15:30:00+05:30','2027-01-01T13:00:00Z',30)
    assert proposal['start']=='2027-01-01T11:00:00+00:00'
    with pytest.raises(HTTPException):service.approve(b,proposal['id'])
    service.approve(a,proposal['id']);service.approve(a,proposal['id'])
    assert len(service.events(a))==2
    pending=service.propose(a,'Later','2027-01-01T12:00:00Z','2027-01-01T14:00:00Z',30)
    service.import_ics(a,ICS.replace('Meeting','Changed'))
    with pytest.raises(HTTPException):service.approve(a,pending['id'])
    service.import_ics(b,service.export(a))
    assert len(service.events(b))==2
    with pytest.raises(ValueError):service.import_ics(a,ICS.replace('SUMMARY:Meeting','RRULE:FREQ=DAILY'))


def test_calendar_timezone_dst_and_unicode_folding(tmp_path):
    store,a,b=setup(tmp_path); service=Planning(store)
    zoned=ICS.replace('DTSTART:20270101T100000Z','DTSTART;TZID=America/New_York:20270101T100000').replace('DTEND:20270101T110000Z','DTEND;TZID=America/New_York:20270101T110000')
    service.import_ics(a,zoned.replace('SUMMARY:Meeting','SUMMARY:'+'é'*80))
    assert service.events(a)[0]['start']=='2027-01-01T15:00:00+00:00'
    exported=service.export(a)
    assert all(len(line.encode())<=75 for line in exported.splitlines())
    service.import_ics(b,exported);assert service.events(b)[0]['title']=='é'*80
    with pytest.raises(ValueError):service.import_ics(a,zoned.replace('20270101T100000','20270314T023000'))
    with pytest.raises(ValueError):service.import_ics(a,zoned.replace('20270101T100000','20271107T013000'))


def test_watch_changed_deleted_excluded_and_root_revocation(tmp_path,monkeypatch):
    store,a,b=setup(tmp_path); root=tmp_path/'approved';root.mkdir()
    monkeypatch.setenv('WEDNESDAY_WATCH_ROOTS',str(root))
    monkeypatch.setenv('WEDNESDAY_WATCH_OWNER',a)
    (root/'note.md').write_text('violet original');(root/'secret.txt').write_text('secret')
    service=WatchFolders(store); folder=service.add(a,str(root),['secret*'])
    with pytest.raises(ValueError):service.add(a,str(tmp_path),[])
    service.tick(); first=store.retrieve(a,'violet')[0]['id'];assert not store.retrieve(b,'violet');assert not store.retrieve(a,'secret')
    service.tick();assert store.retrieve(a,'violet')[0]['id']==first
    (root/'note.md').write_text('coral revised');service.tick();assert not store.retrieve(a,'violet');assert store.retrieve(a,'coral')
    (root/'note.md').unlink();service.tick();assert not store.retrieve(a,'coral')
    (root/'note.md').write_text('violet returned');service.tick()
    monkeypatch.setenv('WEDNESDAY_WATCH_ROOTS','');service.tick();assert not store.retrieve(a,'violet');assert service.list(a)[0]['status']=='failed'
    with pytest.raises(KeyError):service.remove(b,folder['id'])


def test_evaluations_detect_missing_sources_without_tools(tmp_path):
    store,a,b=setup(tmp_path); service=Evaluations(store)
    identity=store.save_record(a,'document','Evidence','violet source')
    if isinstance(identity,dict):identity=identity['id']
    case=service.save(a,{'title':'Redacted','query':'violet','expected_sources':[identity],'confirmed':True})
    assert service.run(a,case['id'])['passed']
    with pytest.raises(KeyError):service.run(b,case['id'])
    with store.db() as db:db.execute('DELETE FROM records WHERE id=?',(identity,))
    assert not service.run(a,case['id'])['passed']
    assert len(Evaluations(Workspace(store.path)).list(a)['runs'])==2
    service.delete(a,case['id']);assert service.list(a)=={'cases':[],'runs':[]}
    diagnostic=service.save(a,{'title':'Syntax fixture','kind':'python_diagnostics','query':'def broken(:','expect_error':True,'expected_sources':[]})
    result=service.run(a,diagnostic['id'])
    assert result['passed'] and result['diagnostic']['line']==1
    assert result['cancellation_probe']['passed']


def test_expansion_api_rejects_commands_unauthorized_and_missing_confirmation(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main,'store',Workspace(tmp_path/'api.db'))
    with TestClient(main.app) as client:
        assert client.get('/api/expansion/offline').status_code==401
        client.post('/api/session')
        body={'operation_id':'a','id':'a','kind':'note','expected_revision':0,'value':{'title':'Title','content':'source'}}
        assert client.post('/api/expansion/offline',json=body).json()['status']=='completed'
        assert client.post('/api/expansion/offline',json={**body,'kind':'command'}).status_code==422
        assert client.post('/api/expansion/offline',json={**body,'kind':'reminder'}).status_code==422
        assert client.post('/api/expansion/calendar/proposals/missing/approve',json={'confirmed':False}).status_code==422
        assert client.post('/api/expansion/folders',json={'root':str(tmp_path),'confirmed':True}).status_code==422
        client.cookies.clear();client.post('/api/session')
        assert client.get('/api/expansion/offline').json()['records']==[]


def test_google_incremental_reset_idempotent_writes_and_owner_boundary(tmp_path,monkeypatch):
    import httpx
    from app.google_calendar import GoogleCalendar
    store,a,b=setup(tmp_path)
    monkeypatch.setenv('WEDNESDAY_GOOGLE_OWNER',a)
    monkeypatch.setenv('WEDNESDAY_GOOGLE_ACCESS_TOKEN','fixture-only')
    events={};writes=[];reset=[False]
    def handler(request):
        assert request.headers['Authorization']=='Bearer fixture-only'
        if request.url.path.endswith('/calendarList'):
            return httpx.Response(200,json={'items':[{'id':'fixture@example.test','summary':'Fixture','accessRole':'owner'}]})
        if request.method=='POST':
            value=json.loads(request.content);assert 'attendees' not in value
            assert request.url.params['sendUpdates']=='none'
            writes.append(value['id']);events[value['id']]=value
            return httpx.Response(201,json=value)
        if request.url.path.endswith('/events'):
            if reset[0] and request.url.params.get('syncToken'):
                reset[0]=False;return httpx.Response(410,json={})
            return httpx.Response(200,json={'items':list(events.values()),'nextSyncToken':'fixture-checkpoint','timeZone':'UTC'})
        identity=request.url.path.rsplit('/',1)[-1]
        return httpx.Response(200,json=events[identity]) if identity in events else httpx.Response(404,json={})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        service=GoogleCalendar(store,client)
        with pytest.raises(HTTPException):service.calendars(b)
        service.connect(a,'fixture@example.test');assert service.sync(a)['full_sync']
        assert not service.sync(a)['full_sync']
        reset[0]=True;assert service.sync(a)['full_sync']
        proposal=Planning(store).propose(a,'Reviewed block','2027-01-01T10:00:00Z','2027-01-01T12:00:00Z',30)
        assert service.approve(a,proposal['id'])['status']=='completed'
        assert service.approve(a,proposal['id'])['status']=='completed'
        assert len(writes)==1
        service.disconnect(a)
        assert not Planning(store).events(a)
        with pytest.raises(HTTPException):service.sync(a)
