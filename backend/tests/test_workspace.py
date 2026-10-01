from datetime import datetime, timedelta, timezone
import pytest
from app.workspace import Workspace


def test_ownership_persistence_and_search(tmp_path):
    path=tmp_path/'work.db'
    store=Workspace(path)
    alice,token=store.create_owner(); bob,_=store.create_owner()
    assert store.authenticate(token)==alice
    assert store.authenticate('wrong') is None
    chat=store.conversation(alice)
    store.message(alice,chat['id'],'user','Explain my violet deployment')
    assert store.conversations(alice,'violet')[0]['id']==chat['id']
    with pytest.raises(KeyError): store.history(bob,chat['id'])
    doc=store.save_record(alice,'document','Architecture','Violet deployment uses isolated containers.')
    assert store.retrieve(alice,'violet')[0]['id']==doc
    assert not store.retrieve(bob,'violet')
    assert not store.delete_record(bob,doc)
    with pytest.raises(KeyError): store.save_record(bob,'memory','Hack','bad',identity=doc)
    reopened=Workspace(path)
    assert reopened.history(alice,chat['id'])[0]['content']=='Explain my violet deployment'
    reopened.delete_conversation(alice,chat['id'])
    assert not reopened.conversations(alice)


def test_reminder_due_time_does_not_move_on_poll(tmp_path):
    store=Workspace(tmp_path/'work.db'); owner,_=store.create_owner()
    due=datetime.now(timezone.utc)-timedelta(seconds=1)
    identity=store.add_reminder(owner,'Review release',due.isoformat(),'Asia/Kolkata')
    assert store.due_reminders()[0]['id']==identity
    assert store.due_reminders()[0]['due_at']==due.isoformat()
    assert store.acknowledge_reminder(owner,identity)
    assert not store.due_reminders()
    with pytest.raises(ValueError):store.add_reminder(owner,'Bad','not-a-date','Asia/Kolkata')


def test_preferences_export_and_receipts(tmp_path):
    store=Workspace(tmp_path/'work.db'); owner,_=store.create_owner()
    store.prefs(owner,{'theme':'light','llm_provider':'groq','unknown':'ignored'})
    store.receipt(owner,'time',{'success':True,'content':'12:00'})
    export=store.export(owner)
    assert export['preferences']['theme']=='light'
    assert export['preferences']['llm_provider']=='groq'
    assert 'unknown' not in export['preferences']
    assert export['receipts'][0]['result']['success']
