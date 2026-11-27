import json
import pytest
from fastapi import HTTPException
from app.workspace import Workspace
from app.offline import Offline
from app.planning import Planning, instant
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
    with pytest.raises(ValueError):service.import_ics(a,ICS.replace('SUMMARY:Meeting','RRULE:FREQ=DAILY;COUNT=1001'))


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


def test_watch_open_rejects_swapped_parent_directory(tmp_path):
    import os
    from app.watchfolders import open_watch_file

    if os.open not in os.supports_dir_fd or not hasattr(os, 'O_NOFOLLOW'):
        pytest.skip('Directory-handle no-follow opens are unavailable')
    root = tmp_path.resolve()
    approved = root / 'approved'
    outside = root / 'outside'
    approved.mkdir()
    outside.mkdir()
    (approved / 'note.txt').write_text('approved fixture')
    (outside / 'note.txt').write_text('outside fixture')
    target = approved / 'note.txt'
    flags = os.O_RDONLY | os.O_NOFOLLOW
    with os.fdopen(open_watch_file(target, flags)) as source:
        assert source.read() == 'approved fixture'
    approved.rename(root / 'old-approved')
    approved.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        open_watch_file(target, flags)


def test_evaluation_retains_timeout_and_continues_suite(tmp_path, monkeypatch):
    import asyncio
    from app.runtime import Runtime

    store, owner, _ = setup(tmp_path)
    service = Evaluations(store)
    interrupt = Runtime.interrupt
    attempts = 0

    async def stall_once(runtime, announce=True):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await asyncio.Event().wait()
        await interrupt(runtime, announce)

    monkeypatch.setattr(Runtime, 'interrupt', stall_once)
    for title in ('First', 'Second'):
        service.save(owner, {
            'title': title, 'query': 'x = 1',
            'kind': 'python_diagnostics', 'expected_sources': [],
        })
    report = service.run_suite(owner)
    assert (report['passed'], report['failed']) == (1, 1)
    failed = next(run for run in service.list(owner)['runs'] if not run['value']['passed'])
    probe = failed['value']['cancellation_probe']
    assert probe['failure'] == 'Timed out during interruption'
    assert probe['latency_ms'] is None
    assert probe['event_types'] == ['stream_start', 'stream_chunk']


def test_exact_retrieval_checks_order_and_unexpected_sources(tmp_path):
    store, owner, _ = setup(tmp_path)
    service = Evaluations(store)
    first = store.save_record(owner, 'document', 'First', 'violet orange')
    second = store.save_record(owner, 'document', 'Second', 'violet')
    for expected in ([first, second], [second, first], [first]):
        service.save(owner, {
            'title': 'Ranked sources', 'query': 'violet orange',
            'kind': 'retrieval_exact', 'expected_sources': expected,
        })
    report = service.run_suite(owner)
    assert report['passed'] == 1
    assert report['reused_retrievals'] == 2
    assert all(run['actual_source_order'] == [first, second] for run in report['runs'])
    assert any(run['unexpected_sources'] == [second] for run in report['runs'])


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
    assert result['cancellation_probe']['ordered_events']
    assert result['cancellation_probe']['event_sequences'] == [1, 2, 3, 4]
    assert result['cancellation_probe']['event_types'] == [
        'stream_start', 'stream_chunk', 'interrupted', 'context_updated',
    ]
    for expected_line in (2, 3):
        located = service.save(a, {
            'title': 'Syntax location', 'kind': 'python_diagnostics',
            'query': 'x = 1\ndef broken(:', 'expect_error': True,
            'expected_sources': [], 'expected_line': expected_line,
        })
        result = service.run(a, located['id'])
        assert result['diagnostic']['line'] == 2
        assert result['passed'] == (expected_line == 2)


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
            return httpx.Response(503,json={})
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
        with pytest.raises(HTTPException) as failure:
            service.approve(a,proposal['id'])
        assert failure.value.status_code == 502
        events[proposal['id']]['summary'] = 'Unreviewed edit'
        with pytest.raises(HTTPException) as conflict:
            service.approve(a,proposal['id'])
        assert conflict.value.status_code == 409
        events[proposal['id']]['summary'] = 'Reviewed block'
        assert service.approve(a,proposal['id'])['status']=='completed'
        assert service.approve(a,proposal['id'])['status']=='completed'
        assert len(writes)==1
        service.disconnect(a)
        assert not Planning(store).events(a)
        with pytest.raises(HTTPException):service.sync(a)


def test_all_day_round_trip_blocks_dst_day(tmp_path):
    store, owner, other = setup(tmp_path)
    for identity in (owner, other):
        store.prefs(identity, {'timezone': 'America/New_York'})
    planner = Planning(store)
    calendar = ICS.replace('DTSTART:20270101T100000Z', 'DTSTART;VALUE=DATE:20270314').replace('DTEND:20270101T110000Z', 'DTEND;VALUE=DATE:20270315')
    planner.import_ics(owner, calendar)
    event = planner.events(owner)[0]
    assert event['start'] == '2027-03-14T05:00:00+00:00'
    assert event['end'] == '2027-03-15T04:00:00+00:00'
    exported = planner.export(owner)
    assert 'DTSTART;VALUE=DATE:20270314' in exported
    planner.import_ics(other, exported)
    assert planner.events(other) == [event]

def test_bounded_weekly_series_reimport_removes_obsolete_occurrences(tmp_path):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    calendar = ICS.replace('SUMMARY:Meeting', 'RRULE:FREQ=WEEKLY;COUNT=3\r\nSUMMARY:Meeting')
    planner.import_ics(owner, calendar)
    assert [event['start'][:10] for event in planner.events(owner)] == [
        '2027-01-01', '2027-01-08', '2027-01-15',
    ]
    planner.import_ics(owner, calendar.replace('COUNT=3', 'COUNT=2'))
    assert len(planner.events(owner)) == 2

def test_recurrence_extra_dates_and_exclusions(tmp_path):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    calendar = ICS.replace('SUMMARY:Meeting', '\r\n'.join([
        'RRULE:FREQ=WEEKLY;COUNT=3',
        'EXDATE:20270108T100000Z',
        'RDATE:20270105T100000Z,20270115T100000Z',
        'SUMMARY:Meeting',
    ]))
    planner.import_ics(owner, calendar)
    assert [event['start'][:10] for event in planner.events(owner)] == [
        '2027-01-01', '2027-01-05', '2027-01-15',
    ]

def test_moved_and_cancelled_occurrences_replace_original_slots(tmp_path):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    master = ICS.replace('SUMMARY:Meeting', 'RRULE:FREQ=WEEKLY;COUNT=3\r\nSUMMARY:Meeting')
    overrides = '\r\n'.join([
        'BEGIN:VEVENT', 'UID:fixture', 'RECURRENCE-ID:20270108T100000Z',
        'DTSTART:20270109T100000Z', 'DTEND:20270109T110000Z', 'END:VEVENT',
        'BEGIN:VEVENT', 'UID:fixture', 'RECURRENCE-ID:20270115T100000Z',
        'STATUS:CANCELLED', 'END:VEVENT', '',
    ])
    planner.import_ics(owner, master.replace('END:VCALENDAR', overrides + 'END:VCALENDAR'))
    assert [event['start'][:10] for event in planner.events(owner)] == ['2027-01-01', '2027-01-09']
    planner.import_ics(owner, master)
    assert [event['start'][:10] for event in planner.events(owner)] == ['2027-01-01', '2027-01-08', '2027-01-15']


def test_open_recurrence_expands_past_9000_occurrences(tmp_path):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    outcome = planner.import_ics(owner, ICS.replace('SUMMARY:Meeting', 'RRULE:FREQ=DAILY'))
    assert outcome['imported'] == 1000
    assert outcome['checked_until']
    proposal = planner.propose(owner, 'Future', '2060-01-01T10:00:00Z', '2060-01-01T12:00:00Z', 30)
    assert proposal['start'] == '2060-01-01T11:00:00+00:00'
    assert planner.approve(owner, proposal['id'])['status'] == 'applied'


def test_recurrence_budget_failure_preserves_existing_coverage(tmp_path, monkeypatch):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    original = planner.import_ics(owner, ICS.replace('SUMMARY:Meeting', 'RRULE:FREQ=DAILY'))
    clock = iter((0, 3))
    monkeypatch.setattr('app.planning.monotonic', lambda: next(clock))

    with pytest.raises(HTTPException, match='expansion budget'):
        planner.propose(owner, 'Future', '2060-01-01T10:00:00Z', '2060-01-01T12:00:00Z', 30)

    with store.db() as db:
        assert planner._checked_until(db, owner) == original['checked_until']
        assert len(planner._events(db, owner)) == 1000


def test_approval_rechecks_coverage_even_when_event_snapshot_is_unchanged(tmp_path):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    proposal = planner.propose(owner, 'Future', '2040-01-01T10:00:00Z', '2040-01-01T12:00:00Z', 30)
    with store.db() as db:
        db.execute('INSERT INTO calendar_coverage VALUES(?,?,?)', (owner, 'series', '2039-01-01T00:00:00+00:00'))
    with pytest.raises(HTTPException, match='coverage'):
        planner.approve(owner, proposal['id'])

def test_calendar_evaluation_distinguishes_dst_offsets_and_rejects_naive_time(tmp_path):
    store, owner, _ = setup(tmp_path)
    service = Evaluations(store)
    for query, expected, invalid, passed in [
        ('2027-11-07T01:30:00-04:00', '2027-11-07T05:30:00Z', False, True),
        ('2027-11-07T01:30:00-05:00', '2027-11-07T05:30:00Z', False, False),
        ('2027-11-07T01:30:00', None, True, True),
    ]:
        case = service.save(owner, {'title': 'Calendar offsets', 'kind': 'calendar_timezone',
            'query': query, 'expected_utc': expected, 'expect_error': invalid, 'expected_sources': []})
        result = service.run(owner, case['id'])
        assert result['passed'] is passed
        assert result['formula_version'] == 'calendar-timezone-v1'
    assert not Planning(store).events(owner)


def test_suite_reports_failures_and_only_runs_owned_cases(tmp_path):
    store, owner, other = setup(tmp_path)
    service = Evaluations(store)
    def save(identity, expect_error):
        return service.save(identity, {'title':'Syntax','kind':'python_diagnostics',
            'query':'def broken(:','expect_error':expect_error,'expected_sources':[]})['id']
    save(owner, True)
    failed = save(owner, False)
    save(other, False)
    result = service.run_suite(owner)
    assert (result['passed'], result['failed'], result['failed_case_ids']) == (1, 1, [failed])
    assert result['p95_ms'] >= result['median_ms'] >= 0
    assert len(service.list(owner)['runs']) == 2
    assert service.list(other)['runs'] == []

def test_retrieval_suite_loads_source_records_once(tmp_path, monkeypatch):
    store, owner, _ = setup(tmp_path)
    service = Evaluations(store)
    source = store.save_record(owner, 'document', 'Evidence', 'violet source')
    for title in ['First', 'Second']:
        service.save(owner, {'title': title, 'query': 'violet', 'expected_sources': [source]})
    reads = []
    records = store.records

    def count_reads(identity):
        reads.append(identity)
        return records(identity)

    monkeypatch.setattr(store, 'records', count_reads)
    report = service.run_suite(owner)
    assert report['passed'] == 2
    assert reads == [owner]
    assert report["reused_retrievals"] == 1
    assert [run["retrieval_reused"] for run in report["runs"]] == [False, True]

def test_google_oauth_state_is_single_use_and_disconnect_clears_grant(tmp_path, monkeypatch):
    import httpx
    from urllib.parse import parse_qs, urlsplit
    from app.google_calendar import GoogleCalendar
    store, owner, other = setup(tmp_path)
    monkeypatch.setenv('WEDNESDAY_GOOGLE_CLIENT_ID', 'fixture')
    monkeypatch.setenv('WEDNESDAY_GOOGLE_CLIENT_SECRET', 'fixture-secret')
    monkeypatch.setenv('WEDNESDAY_GOOGLE_REDIRECT_URI', 'http://localhost:8799/api/expansion/calendar/google/oauth/callback')
    from cryptography.fernet import Fernet
    monkeypatch.setenv('WEDNESDAY_GOOGLE_CREDENTIAL_KEY', Fernet.generate_key().decode())
    exchanges = []

    def exchange(request):
        assert request.url.host == 'oauth2.googleapis.com'
        if request.url.path == '/revoke':
            assert b'token=fixture-refresh' == request.content
            return httpx.Response(503)
        exchanges.append(request)
        return httpx.Response(200, json={'refresh_token': 'fixture-refresh'})

    with httpx.Client(transport=httpx.MockTransport(exchange)) as client:
        service = GoogleCalendar(store, client)
        state = parse_qs(urlsplit(service.begin_oauth(owner)['url']).query)['state'][0]
        service.finish_oauth(state, 'fixture-code')
        assert service.configured(owner) and not service.configured(other)
        with store.db() as db:
            stored = db.execute('SELECT refresh_token FROM google_oauth_credentials WHERE owner=?',(owner,)).fetchone()[0]
        assert stored.startswith('fernet:') and 'fixture-refresh' not in stored
        reopened = GoogleCalendar(Workspace(store.path), client)
        assert reopened.refresh_token(owner) == 'fixture-refresh'
        with pytest.raises(HTTPException, match='already used'):
            service.finish_oauth(state, 'fixture-code')
        pending = parse_qs(urlsplit(service.begin_oauth(owner)['url']).query)['state'][0]
        assert service.disconnect(owner) == {'disconnected':True,'google_revocation':'unconfirmed'}
        assert not service.configured(owner)
        with pytest.raises(HTTPException, match='already used'):
            service.finish_oauth(pending, 'fixture-code')
        assert len(exchanges) == 1

def test_google_oauth_http_callback_and_local_calendar_after_key_loss(tmp_path, monkeypatch):
    import httpx
    from cryptography.fernet import Fernet
    from fastapi.testclient import TestClient
    from urllib.parse import parse_qs, urlsplit
    from app import main

    monkeypatch.setattr(main, 'store', Workspace(tmp_path/'oauth.db'))
    for name, value in {
        'CLIENT_ID': 'fixture', 'CLIENT_SECRET': 'fixture-secret',
        'REDIRECT_URI': 'http://localhost/api/expansion/calendar/google/oauth/callback',
        'CREDENTIAL_KEY': Fernet.generate_key().decode(),
    }.items():
        monkeypatch.setenv('WEDNESDAY_GOOGLE_'+name, value)

    def exchange(url, **kwargs):
        assert url == 'https://oauth2.googleapis.com/token'
        assert kwargs['data']['code'] == 'fake-code'
        return httpx.Response(200, json={'refresh_token':'private-fixture'})

    monkeypatch.setattr(httpx, 'post', exchange)
    path = '/api/expansion/calendar'
    with TestClient(main.app) as browser:
        assert browser.post(path+'/google/oauth/start').status_code == 401
        browser.post('/api/session')
        response = browser.post(path+'/google/oauth/start')
        assert response.status_code == 200
        state = parse_qs(urlsplit(response.json()['url']).query)['state'][0]
        callback = path+'/google/oauth/callback'
        params = {'state':state,'code':'fake-code'}
        session_token = browser.cookies.get('wednesday_token')
        browser.cookies.delete('wednesday_token')
        response = browser.get(callback, params=params, follow_redirects=False)
        browser.cookies.set('wednesday_token', session_token)
        assert response.status_code == 303 and 'private-fixture' not in response.text
        assert response.headers['location'] == '/ui/?view=expansion&google=connected'
        assert browser.get(callback, params=params).status_code == 400
        pending = browser.post(path+'/google/oauth/start')
        cancelled_state = parse_qs(urlsplit(pending.json()['url']).query)['state'][0]
        cancelled = browser.get(callback, params={'state':cancelled_state,'error':'access_denied'}, follow_redirects=False)
        assert cancelled.status_code == 303
        assert cancelled.headers['location'] == '/ui/?view=expansion&google=cancelled'
        assert browser.get(callback, params={'state':cancelled_state,'code':'fake-code'}).status_code == 400
        assert browser.get(path).json()['google']['available']
        monkeypatch.delenv('WEDNESDAY_GOOGLE_CREDENTIAL_KEY')
        assert not browser.get(path).json()['google']['available']
        assert browser.post(path+'/proposals', json={
            'title':'Local block', 'start':'2027-01-01T10:00:00Z',
            'end':'2027-01-01T12:00:00Z', 'minutes':30,
        }).status_code == 200

def test_google_disconnect_during_exchange_prevents_reconnection(tmp_path, monkeypatch):
    import httpx
    from cryptography.fernet import Fernet
    from urllib.parse import parse_qs, urlsplit
    from app.google_calendar import GoogleCalendar

    store, owner, _ = setup(tmp_path)
    monkeypatch.setenv('WEDNESDAY_GOOGLE_CLIENT_ID', 'fixture')
    monkeypatch.setenv('WEDNESDAY_GOOGLE_CLIENT_SECRET', 'fixture-secret')
    monkeypatch.setenv('WEDNESDAY_GOOGLE_REDIRECT_URI', 'http://localhost/oauth')
    monkeypatch.setenv('WEDNESDAY_GOOGLE_CREDENTIAL_KEY', Fernet.generate_key().decode())

    def exchange(request):
        GoogleCalendar(store).disconnect(owner)
        return httpx.Response(200, json={'refresh_token':'late-token'})

    with httpx.Client(transport=httpx.MockTransport(exchange)) as client:
        service = GoogleCalendar(store, client)
        state = parse_qs(urlsplit(service.begin_oauth(owner)['url']).query)['state'][0]
        with pytest.raises(HTTPException, match='cancelled or replaced'):
            service.finish_oauth(state, 'code')
        assert not service.configured(owner)

def test_range_override_applies_to_later_occurrences(tmp_path):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    master = ICS.replace('SUMMARY:Meeting', 'RRULE:FREQ=WEEKLY;COUNT=3\r\nSUMMARY:Meeting')
    override = '\r\n'.join([
        'BEGIN:VEVENT', 'UID:fixture', 'RECURRENCE-ID;RANGE=THISANDFUTURE:20270108T100000Z',
        'DTSTART:20270108T120000Z', 'DTEND:20270108T140000Z', 'SUMMARY:Moved', 'END:VEVENT', '',
    ])
    planner.import_ics(owner, master.replace('END:VCALENDAR', override + 'END:VCALENDAR'))
    events = planner.events(owner)
    assert [row['start'][11:16] for row in events] == ['10:00', '12:00', '12:00']
    assert [row['end'][11:16] for row in events[-2:]] == ['14:00', '14:00']
    assert [row['title'] for row in events[-2:]] == ['Moved', 'Moved']

def test_range_override_preserves_wall_time_when_shift_crosses_dst(tmp_path):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    master = ICS.replace('DTSTART:20270101T100000Z','DTSTART;TZID=America/New_York:20270313T100000')
    master = master.replace('DTEND:20270101T110000Z','DTEND;TZID=America/New_York:20270313T110000')
    master = master.replace('SUMMARY:Meeting','RRULE:FREQ=DAILY;COUNT=3\r\nSUMMARY:Meeting')
    override = '\r\n'.join([
        'BEGIN:VEVENT','UID:fixture',
        'RECURRENCE-ID;TZID=America/New_York;RANGE=THISANDFUTURE:20270313T100000',
        'DTSTART;TZID=America/New_York:20270314T120000',
        'DTEND;TZID=America/New_York:20270314T130000','END:VEVENT','',
    ])
    planner.import_ics(owner,master.replace('END:VCALENDAR',override+'END:VCALENDAR'))
    assert [row['start'][:16] for row in planner.events(owner)] == [
        '2027-03-14T16:00','2027-03-15T16:00','2027-03-16T16:00',
    ]


def test_open_series_expands_after_workspace_restart(tmp_path):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    planner.import_ics(owner, ICS.replace('SUMMARY:Meeting', 'RRULE:FREQ=DAILY'))
    reopened = Planning(Workspace(store.path))
    proposal = reopened.propose(owner, 'Later', '2040-01-01T10:00:00Z', '2040-01-01T12:00:00Z', 30)
    assert proposal['start'] == '2040-01-01T11:00:00+00:00'
    assert reopened.approve(owner, proposal['id'])['status'] == 'applied'
    later = reopened.propose(owner, 'Again', '2041-01-01T10:00:00Z', '2041-01-01T12:00:00Z', 30)
    assert later['start'] == '2041-01-01T11:00:00+00:00'
    assert reopened.approve(owner, later['id'])['status'] == 'applied'

def test_recurrence_expansion_does_not_replace_newer_coverage(tmp_path):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    source = ICS.replace('SUMMARY:Meeting', 'RRULE:FREQ=DAILY')
    planner.import_ics(owner, source)
    planner.propose(owner, 'Later', '2041-01-01T10:00:00Z', '2041-01-01T12:00:00Z', 30)
    cutoff = planner.checked_until(owner)
    with store.db() as db:
        saved = db.execute('SELECT source FROM calendar_recurrence_sources WHERE owner=?', (owner,)).fetchone()[0]
    result = planner.import_ics(owner, saved, extend_uid='fixture', through=instant('2040-01-01T12:00:00Z'))
    assert result == {'imported': 0, 'checked_until': cutoff}
    assert planner.propose(owner, 'Again', '2041-01-01T10:00:00Z', '2041-01-01T12:00:00Z', 30)['start'] == '2041-01-01T11:00:00+00:00'


def test_export_round_trips_recurrence_without_attendees(tmp_path):
    store, owner, other = setup(tmp_path)
    planner = Planning(store)
    source = ICS.replace('SUMMARY:Meeting','RRULE:FREQ=WEEKLY;COUNT=3\r\nEXDATE:20270108T100000Z\r\nATTENDEE:mailto:private@example.test\r\nSUMMARY:Meeting')
    planner.import_ics(owner, source)
    exported = planner.export(owner)
    assert 'RRULE:FREQ=WEEKLY;COUNT=3' in exported
    assert exported.count('DTSTAMP:') == 1
    assert 'EXDATE:20270108T100000Z' in exported
    assert 'private@example.test' not in exported
    with store.db() as db:
        retained = db.execute('SELECT source FROM calendar_recurrence_sources WHERE owner=?', (owner,)).fetchone()[0]
    assert 'private@example.test' not in retained
    planner.import_ics(other, exported)
    assert planner.events(owner) == planner.events(other)

def test_legacy_recurrence_source_is_minimized_on_reopen(tmp_path):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    raw = ICS.replace('SUMMARY:Meeting','RRULE:FREQ=DAILY\r\nDESCRIPTION:Legacy private description\r\nSUMMARY:Meeting')
    planner.import_ics(owner, raw)
    with store.db() as db:
        db.execute('UPDATE calendar_recurrence_sources SET source=? WHERE owner=?',(raw,owner))
        db.execute('DELETE FROM calendar_migrations')
    reopened = Planning(Workspace(store.path))
    with store.db() as db:
        retained = db.execute('SELECT source FROM calendar_recurrence_sources WHERE owner=?',(owner,)).fetchone()[0]
    assert 'Legacy private description' not in retained
    assert 'RRULE:FREQ=DAILY' in retained
    proposal = reopened.propose(owner, 'Later','2040-01-01T10:00:00Z','2040-01-01T12:00:00Z',30)
    assert proposal['start'] == '2040-01-01T11:00:00+00:00'

def test_removed_folder_stops_before_extracting_next_file(tmp_path, monkeypatch):
    from app import watchfolders

    store, owner, _ = setup(tmp_path)
    root = tmp_path / 'removed-during-scan'
    root.mkdir()
    for name in ('one.pdf', 'two.pdf'):
        (root / name).write_bytes(b'fixture')
    monkeypatch.setenv('WEDNESDAY_WATCH_ROOTS', str(root))
    monkeypatch.setenv('WEDNESDAY_WATCH_OWNER', owner)
    watch = WatchFolders(store)
    identity = watch.add(owner, str(root), [])['id']
    attempts = []

    def remove_during_extraction(data):
        attempts.append(data)
        watch.remove(owner, identity)
        return 'This result must never be indexed'

    monkeypatch.setattr(watchfolders, 'extract_document', remove_during_extraction)
    watch.tick()
    assert attempts == [b'fixture']
    assert watch.list(owner) == []
    assert store.records(owner, 'document') == []


def test_pdf_worker_indexes_valid_document_through_watch_and_upload(tmp_path, monkeypatch):
    import sys
    from fastapi.testclient import TestClient
    from pypdf import PdfWriter
    from app import main

    if sys.platform == 'darwin':
        monkeypatch.setenv('WEDNESDAY_REQUIRE_PDF_ISOLATION', '1')
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    store, owner, _ = setup(tmp_path)
    root = tmp_path/'pdfs'
    root.mkdir()
    monkeypatch.setenv('WEDNESDAY_WATCH_ROOTS', str(root))
    monkeypatch.setenv('WEDNESDAY_WATCH_OWNER', owner)
    (root/'a-invalid.pdf').write_bytes(b'%PDF-1.4 broken fixture')
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=100)
    name = NameObject
    page[name('/Resources')] = DictionaryObject({name('/Font'): DictionaryObject({
        name('/F1'): DictionaryObject({name('/Type'): name('/Font'), name('/Subtype'): name('/Type1'),
                                      name('/BaseFont'): name('/Helvetica')}),
    })})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 20 40 Td (violet worker evidence) Tj ET')
    page[name('/Contents')] = writer._add_object(stream)
    with (root/'b-valid.pdf').open('wb') as document:
        writer.write(document)

    service = WatchFolders(store)
    service.add(owner, str(root), [])
    service.tick()
    files = {row['path']:row for row in service.list(owner)[0]['files']}
    assert files['a-invalid.pdf']['error']
    assert files['b-valid.pdf']['error'] is None
    assert [source['title'] for source in store.retrieve(owner,'violet')] == ['b-valid.pdf']
    monkeypatch.setattr(main, 'store', store)
    with TestClient(main.app) as client:
        assert client.post('/api/session').status_code == 200
        uploaded = client.post('/api/documents', files={
            'file': ('uploaded.pdf', (root/'b-valid.pdf').read_bytes(), 'application/pdf'),
        })
        assert uploaded.status_code == 200, uploaded.text
        result = client.get('/api/search', params={'q': 'violet'})
        assert [source['title'] for source in result.json()['sources']] == ['uploaded.pdf']

def test_google_partial_consent_does_not_store_credentials(tmp_path, monkeypatch):
    import httpx
    from cryptography.fernet import Fernet
    from urllib.parse import parse_qs, urlsplit
    from app.google_calendar import GoogleCalendar, GOOGLE_CALENDAR_SCOPES

    store, owner, _ = setup(tmp_path)
    monkeypatch.setenv('WEDNESDAY_GOOGLE_CLIENT_ID', 'fixture')
    monkeypatch.setenv('WEDNESDAY_GOOGLE_CLIENT_SECRET', 'fixture-secret')
    monkeypatch.setenv('WEDNESDAY_GOOGLE_REDIRECT_URI', 'http://localhost/oauth')
    monkeypatch.setenv('WEDNESDAY_GOOGLE_CREDENTIAL_KEY', Fernet.generate_key().decode())

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        'refresh_token':'partial-token', 'scope':GOOGLE_CALENDAR_SCOPES[0],
    }))
    with httpx.Client(transport=transport) as client:
        service = GoogleCalendar(store, client)
        params = parse_qs(urlsplit(service.begin_oauth(owner)['url']).query)
        assert tuple(params['scope'][0].split()) == GOOGLE_CALENDAR_SCOPES
        with pytest.raises(HTTPException, match='only part'):
            service.finish_oauth(params['state'][0], 'code')
        assert service.refresh_token(owner) is None

def test_google_picker_can_connect_a_calendar_on_second_page(tmp_path, monkeypatch):
    import httpx
    from app.google_calendar import GoogleCalendar

    store, owner, _ = setup(tmp_path)
    monkeypatch.setenv('WEDNESDAY_GOOGLE_OWNER',owner)
    monkeypatch.setenv('WEDNESDAY_GOOGLE_ACCESS_TOKEN','fixture')
    monkeypatch.delenv('WEDNESDAY_GOOGLE_REFRESH_TOKEN',raising=False)

    def fetch(request):
        if request.url.params.get('pageToken') == 'second':
            return httpx.Response(200,json={'items':[{'id':'second-calendar','summary':'Second'}]})
        return httpx.Response(200,json={'items':[{'id':'first-calendar'}],'nextPageToken':'second'})

    with httpx.Client(transport=httpx.MockTransport(fetch)) as client:
        service = GoogleCalendar(store,client)
        assert service.calendars(owner) == {'calendars':[
            {'id':'first-calendar','title':'Calendar','role':'reader'},
            {'id':'second-calendar','title':'Second','role':'reader'},
        ],'partial':False}
        assert service.connect(owner,'second-calendar')['connection']['calendar'] == 'second-calendar'

def test_pdf_worker_restricts_python_io(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    from app import extract_pdf

    fixture = tmp_path/'private.txt'
    fixture.write_text('fixture data')
    script = """
import socket
import subprocess
import sys
import runpy
worker = runpy.run_path(sys.argv[1])
worker['restrict_parser_io']()
for label, action in [
    ('file read', lambda: open(sys.argv[2], 'rb')),
    ('file write', lambda: open(sys.argv[2] + '.new', 'wb')),
    ('network socket', socket.socket),
    ('process launch', lambda: subprocess.Popen([sys.executable, '-c', 'pass'])),
]:
    try:
        action()
    except PermissionError:
        print(label)
    else:
        raise AssertionError(label + ' was allowed')
"""
    result = subprocess.run(
        [sys.executable, '-I', '-c', script, str(Path(extract_pdf.__file__)), str(fixture)],
        capture_output=True, text=True, timeout=10, check=True,
    )
    assert result.stdout.splitlines() == ['file read', 'file write', 'network socket', 'process launch']
    assert not fixture.with_suffix('.txt.new').exists()

@pytest.mark.parametrize('platform, policy', [
    ('linux', 'restrict_linux_filesystem'),
    ('darwin', 'restrict_macos_filesystem'),
])
def test_pdf_worker_rejects_native_file_access(tmp_path, platform, policy):
    import subprocess
    import sys
    from app import extract_pdf

    if sys.platform != platform:
        pytest.skip(f'{policy} applies to {platform} workers')
    fixture = tmp_path / 'private.txt'
    fixture.write_text('fixture')
    script = """
import ctypes
import errno
import os
import runpy
import sys
worker = runpy.run_path(sys.argv[1])
libc = ctypes.CDLL(None, use_errno=True)
path = os.fsencode(sys.argv[2])
assert libc.close(libc.open(path, os.O_RDONLY)) == 0
if not worker[sys.argv[3]]():
    sys.exit(77)
for flags in (os.O_RDONLY, os.O_WRONLY | os.O_TRUNC):
    assert libc.open(path, flags) == -1 and ctypes.get_errno() in (errno.EACCES, errno.EPERM)
"""
    result = subprocess.run([sys.executable, '-I', '-c', script,
                             extract_pdf.__file__, str(fixture), policy],
                            capture_output=True, text=True, timeout=10)
    if result.returncode == 77 and platform == 'linux':
        pytest.skip('Landlock unavailable on this kernel')
    assert result.returncode == 0, result.stderr
    assert fixture.read_text() == 'fixture'


@pytest.mark.parametrize('policy', ['WEDNESDAY_REQUIRE_PDF_LANDLOCK', 'WEDNESDAY_REQUIRE_PDF_ISOLATION'])
def test_pdf_worker_forwards_strict_isolation_policy(monkeypatch, policy):
    from subprocess import CalledProcessError
    from types import SimpleNamespace
    from app import extract_pdf

    monkeypatch.setenv(policy, '1')
    monkeypatch.setenv('WEDNESDAY_TEST_PRIVATE_TOKEN', 'fixture')

    def worker(*args, **kwargs):
        assert kwargs['env'][policy] == '1'
        assert 'WEDNESDAY_TEST_PRIVATE_TOKEN' not in kwargs['env']
        return SimpleNamespace(stdout=b'fixture')

    monkeypatch.setattr(extract_pdf.subprocess, 'run', worker)
    assert extract_pdf.extract_document(b'fixture') == 'fixture'

    def unavailable(*args, **kwargs):
        raise CalledProcessError(extract_pdf.ISOLATION_UNAVAILABLE_EXIT, args[0])

    monkeypatch.setattr(extract_pdf.subprocess, 'run', unavailable)
    with pytest.raises(extract_pdf.PDFIsolationUnavailable, match='requires OS filesystem isolation'):
        extract_pdf.extract_document(b'fixture', upload=True)


def test_upload_reports_parser_deadline_separately_from_busy_queue(tmp_path, monkeypatch):
    from subprocess import TimeoutExpired
    from fastapi.testclient import TestClient
    from app import extract_pdf, main

    store, _, _ = setup(tmp_path)
    monkeypatch.setattr(main, 'store', store)

    def timeout(command, **kwargs):
        raise TimeoutExpired(command, kwargs['timeout'])

    monkeypatch.setattr(extract_pdf.subprocess, 'run', timeout)
    with TestClient(main.app) as client:
        assert client.post('/api/session').status_code == 200
        response = client.post('/api/documents', files={
            'file': ('note.pdf', b'fixture', 'application/pdf'),
        })
        assert response.status_code == 422
        assert response.json()['detail'] == 'PDF extraction exceeded the 10-second limit.'
        assert client.get('/api/documents').json()['documents'] == []


@pytest.mark.parametrize('real_windows_worker', [False, True], ids=['simulated', 'windows-worker'])
def test_pdf_isolation_failure_does_not_index_upload_or_watched_file(tmp_path, monkeypatch, real_windows_worker):
    import sys
    from subprocess import CalledProcessError
    from fastapi.testclient import TestClient
    from app import extract_pdf, main

    store, owner, _ = setup(tmp_path)
    monkeypatch.setattr(main, 'store', store)

    def refuse(*args, **kwargs):
        raise CalledProcessError(extract_pdf.ISOLATION_UNAVAILABLE_EXIT, args[0])

    if real_windows_worker:
        if sys.platform != 'win32':
            pytest.skip('Requires a Windows worker without native PDF isolation')
        monkeypatch.delenv('WEDNESDAY_REQUIRE_PDF_LANDLOCK', raising=False)
        monkeypatch.setenv('WEDNESDAY_REQUIRE_PDF_ISOLATION', '1')
    else:
        monkeypatch.setattr(extract_pdf.subprocess, 'run', refuse)
    with TestClient(main.app) as client:
        client.post('/api/session')
        result = client.post('/api/documents', files={'file': ('note.pdf', b'fixture', 'application/pdf')})
        assert result.status_code == 503
        detail = result.json()['detail']
        assert 'requires OS filesystem isolation' in detail
        assert client.get('/api/documents').json()['documents'] == []

    root = tmp_path / 'strict-pdf'
    root.mkdir()
    (root / 'note.pdf').write_bytes(b'fixture')
    monkeypatch.setenv('WEDNESDAY_WATCH_ROOTS', str(root))
    monkeypatch.setenv('WEDNESDAY_WATCH_OWNER', owner)
    watch = WatchFolders(store)
    watch.add(owner, str(root), [])
    watch.tick()
    assert watch.list(owner)[0]['files'][0]['error'] == detail
    assert store.records(owner, 'document') == []


def test_pdf_upload_and_watch_share_two_worker_slots(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event, Lock
    from types import SimpleNamespace
    from app import extract_pdf

    start = Barrier(4)
    both_running = Event()
    release_workers = Event()
    lock = Lock()
    active = 0
    peak = 0

    def launch(arguments, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                both_running.set()
        try:
            assert release_workers.wait(5)
            return SimpleNamespace(stdout=b'extracted')
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(extract_pdf.subprocess, 'run', launch)

    def extract(upload):
        start.wait(timeout=5)
        return extract_pdf.extract_document(b'fixture', upload=upload)

    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(extract, upload) for upload in (True, False, True, False)]
        try:
            assert both_running.wait(5)
        finally:
            release_workers.set()
        assert [job.result(timeout=5) for job in jobs] == ['extracted'] * 4
    assert peak == 2

def test_watch_retries_pdf_after_worker_queue_is_busy(tmp_path, monkeypatch):
    from app import watchfolders

    store, owner, _ = setup(tmp_path)
    root = tmp_path/'pdf-retry'
    root.mkdir()
    monkeypatch.setenv('WEDNESDAY_WATCH_ROOTS', str(root))
    monkeypatch.setenv('WEDNESDAY_WATCH_OWNER', owner)
    document = root/'note.pdf'
    document.write_bytes(b'initial fixture')
    service = WatchFolders(store)
    service.add(owner, str(root), [])
    monkeypatch.setattr(watchfolders, 'extract_document', lambda _: 'violet original')
    service.tick()

    def busy(_):
        raise TimeoutError('PDF workers are busy')

    monkeypatch.setattr(watchfolders, 'extract_document', busy)
    service.tick()
    assert store.retrieve(owner, 'violet')
    document.write_bytes(b'updated fixture')
    service.tick()
    assert 'retry on the next scan' in service.list(owner)[0]['files'][0]['error']
    assert not store.retrieve(owner, 'violet')
    monkeypatch.setattr(watchfolders, 'extract_document', lambda _: 'coral replacement')
    service.tick()
    assert store.retrieve(owner, 'coral')
    assert service.list(owner)[0]['files'][0]['error'] is None

def test_calendar_snapshot_ignores_tied_row_order_and_detects_edits():
    first = {'id':'a','title':'A','start':'2027-01-01T10:00:00+00:00','end':'2027-01-01T11:00:00+00:00'}
    second = dict(first,id='b',title='B')
    reviewed = Planning.digest([first,second])
    assert Planning.matches_snapshot([second,first],reviewed)
    assert not Planning.matches_snapshot([second,dict(first,title='Changed')],reviewed)

def test_calendar_alarm_fields_do_not_override_parent_event(tmp_path):
    store, owner, _ = setup(tmp_path)
    calendar = ICS.replace('END:VEVENT', '\r\n'.join([
        'BEGIN:VALARM', 'ACTION:EMAIL', 'TRIGGER:-PT15M',
        'SUMMARY:Reminder email', 'END:VALARM', 'END:VEVENT',
    ]))
    planner = Planning(store)
    planner.import_ics(owner, calendar)
    assert [event['title'] for event in planner.events(owner)] == ['Meeting']
    assert 'Reminder email' not in planner.export(owner)

def test_calendar_duration_round_trips_recurring_timed_events(tmp_path):
    store, owner, other = setup(tmp_path)
    planner = Planning(store)
    source = ICS.replace('DTEND:20270101T110000Z','DURATION:PT90M')
    source = source.replace('SUMMARY:Meeting','RRULE:FREQ=DAILY;COUNT=2\r\nSUMMARY:Meeting')
    planner.import_ics(owner, source)
    assert [event['end'][11:16] for event in planner.events(owner)] == ['11:30','11:30']
    exported = planner.export(owner)
    assert 'DURATION:PT90M' in exported
    planner.import_ics(other, exported)
    assert planner.events(owner) == planner.events(other)

def test_calendar_cancelled_master_removes_previously_imported_series(tmp_path):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    planner.import_ics(owner, ICS.replace('SUMMARY:Meeting','RRULE:FREQ=DAILY\r\nSUMMARY:Meeting'))
    assert planner.checked_until(owner)
    cancellation = '\r\n'.join([
        'BEGIN:VCALENDAR','VERSION:2.0','METHOD:CANCEL','BEGIN:VEVENT',
        'UID:fixture','END:VEVENT','END:VCALENDAR','',
    ])
    assert planner.import_ics(owner,cancellation)['imported'] == 0
    assert planner.events(owner) == []
    assert planner.checked_until(owner) is None
    assert 'UID:fixture' not in planner.export(owner)

def test_standalone_calendar_cancellation_survives_reopen(tmp_path):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    planner.import_ics(owner, ICS.replace('SUMMARY:Meeting','RRULE:FREQ=WEEKLY;COUNT=3\r\nSUMMARY:Meeting'))
    cancellation = '\r\n'.join([
        'BEGIN:VCALENDAR','VERSION:2.0','METHOD:CANCEL','BEGIN:VEVENT','UID:fixture',
        'RECURRENCE-ID:20270108T100000Z','END:VEVENT','END:VCALENDAR',
    ])
    planner.import_ics(owner,cancellation)
    reopened = Planning(Workspace(store.path))
    assert [event['start'][:10] for event in reopened.events(owner)] == ['2027-01-01','2027-01-15']
    assert 'STATUS:CANCELLED' in reopened.export(owner)

def test_standalone_calendar_move_replaces_saved_override(tmp_path):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    planner.import_ics(owner, ICS.replace('SUMMARY:Meeting','RRULE:FREQ=WEEKLY;COUNT=3\r\nSUMMARY:Meeting'))
    update = '\r\n'.join([
        'BEGIN:VCALENDAR','VERSION:2.0','METHOD:REQUEST','BEGIN:VEVENT','UID:fixture',
        'RECURRENCE-ID:20270108T100000Z','DTSTART:20270109T100000Z',
        'DTEND:20270109T110000Z','END:VEVENT','END:VCALENDAR',
    ])
    planner.import_ics(owner,update)
    planner.import_ics(owner,update.replace('20270109','20270110'))
    assert [row['start'][:10] for row in planner.events(owner)] == ['2027-01-01','2027-01-10','2027-01-15']

def test_standalone_cancellation_applies_beyond_initial_coverage(tmp_path):
    store, owner, _ = setup(tmp_path)
    planner = Planning(store)
    planner.import_ics(owner, ICS.replace('SUMMARY:Meeting','RRULE:FREQ=DAILY\r\nSUMMARY:Meeting'))
    planner.propose(owner,'Initial','2040-01-01T10:00:00Z','2040-01-01T12:00:00Z',30)
    cutoff = planner.checked_until(owner)
    planner.import_ics(owner, '\r\n'.join([
        'BEGIN:VCALENDAR','METHOD:CANCEL','BEGIN:VEVENT','UID:fixture',
        'RECURRENCE-ID:20400101T100000Z','END:VEVENT','END:VCALENDAR',
    ]))
    assert planner.checked_until(owner) == cutoff
    proposal = planner.propose(owner,'Available','2040-01-01T10:00:00Z','2040-01-01T12:00:00Z',30)
    assert proposal['start'] == '2040-01-01T10:00:00+00:00'

def test_task_plan_priorities_conflicts_and_atomic_approval(tmp_path):
    store, owner, other = setup(tmp_path)
    planner = Planning(store)
    planner.import_ics(owner,ICS)
    tasks = [{'title':'Low','minutes':60,'priority':0},{'title':'High','minutes':30,'priority':8}]
    proposal = planner.propose_tasks(owner,'2027-01-01T09:00:00Z','2027-01-01T13:00:00Z',tasks)
    assert [(block['title'],block['start'][11:16]) for block in proposal['blocks']] == [('High','09:00'),('Low','11:00')]
    with pytest.raises(HTTPException):
        planner.approve(other,proposal['id'])
    planner.approve(owner,proposal['id'])
    planner.approve(owner,proposal['id'])
    assert len(planner.events(owner)) == 3
