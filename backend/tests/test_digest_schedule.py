from datetime import datetime,timezone,timedelta
from app.workspace import Workspace
from app.continuity import Continuity


def test_daily_schedule_slot_idempotency_and_restart(tmp_path):
    store=Workspace(tmp_path/'schedule.db');owner,_=store.create_owner();service=Continuity(store)
    selected=store.conversation(owner)['id'];excluded=store.conversation(owner)['id'];store.message(owner,selected,'user','Included');store.message(owner,excluded,'user','EXCLUDED')
    value={'enabled':True,'period':'daily','timezone':'Asia/Kolkata','hour':9,'minute':0,'weekday':0,'conversation_ids':[selected],'reminder_ids':[],'receipt_ids':[]}
    config=service.schedule(owner,value);due=datetime.fromisoformat(config['next_due'])
    service.due_digests(due);assert len(service.digests(owner))==1;assert 'EXCLUDED' not in str(service.digests(owner))
    # Simulate a crash after persisting the slot but before moving the schedule.
    with store.db() as db:db.execute('UPDATE digest_schedules SET next_due=? WHERE owner=?',(due.isoformat(),owner))
    Continuity(Workspace(store.path)).due_digests(due);assert len(service.digests(owner))==1
    assert datetime.fromisoformat(service.schedule(owner)['next_due'])>due
    value['enabled']=False;service.schedule(owner,value);service.due_digests(due+timedelta(days=10));assert len(service.digests(owner))==1


def test_missing_source_disables_schedule_without_replacement(tmp_path):
    store=Workspace(tmp_path/'schedule.db');owner,_=store.create_owner();service=Continuity(store);chat=store.conversation(owner)['id']
    value={'enabled':True,'period':'weekly','timezone':'UTC','hour':9,'minute':0,'weekday':0,'conversation_ids':[chat],'reminder_ids':[],'receipt_ids':[]}
    schedule=service.schedule(owner,value);store.delete_conversation(owner,chat);service.due_digests(datetime.fromisoformat(schedule['next_due']))
    assert not service.schedule(owner)['configuration']['enabled'];assert service.schedule(owner)['error'];assert not service.digests(owner)


def test_nonexistent_dst_time_is_skipped():
    value={'period':'daily','timezone':'America/New_York','hour':2,'minute':30,'weekday':0}
    after=datetime(2026,3,8,5,tzinfo=timezone.utc)
    assert Continuity.next_due(value,after).startswith('2026-03-09')
