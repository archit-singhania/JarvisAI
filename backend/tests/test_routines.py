import asyncio
import pytest
from pydantic import ValidationError
from app.workspace import Workspace
from app.routines import Definition, RoutineService


@pytest.mark.asyncio
async def test_confirmed_reminder_and_stop_are_durable(tmp_path):
    store=Workspace(tmp_path/'routines.db');owner,_=store.create_owner();other,_=store.create_owner()
    service=RoutineService(store)
    body=Definition(title='Review',steps=[{'tool':'time'},{'tool':'reminder','argument':'Review notes','due_at':'2030-01-01T12:00:00Z'},{'tool':'time'}])
    definition=service.save(owner,body)
    assert service.preview(owner,definition['id'])['executes'] is False
    run=service.start(owner,definition['id'],1)
    async def execute(*args):return {'success':True,'content':'Fixture time'}
    await service.tick(execute);await service.tick(execute)
    assert service.run(owner,run['id'])['status']=='awaiting_confirmation'
    assert not store.reminders(owner)
    with pytest.raises(KeyError):service.run(other,run['id'])
    service.confirm(owner,run['id'],1);await service.tick(execute)
    assert len(store.reminders(owner))==1
    assert service.run(owner,run['id'])['results'][1]['reminder_id']==store.reminders(owner)[0]['id']
    service.stop(owner,run['id']);await service.tick(execute)
    restored=RoutineService(Workspace(store.path)).run(owner,run['id'])
    assert restored['status']=='cancelled' and len(restored['results'])==2
    assert len(store.receipts(owner))==2


@pytest.mark.asyncio
async def test_cancellation_while_reading_prevents_remaining_writes(tmp_path):
    store=Workspace(tmp_path/'routine.db');owner,_=store.create_owner();service=RoutineService(store)
    definition=service.save(owner,Definition(title='Read',steps=[{'tool':'time'},{'tool':'time'}]))
    run=service.start(owner,definition['id'],1);entered=asyncio.Event();release=asyncio.Event()
    async def execute(*args):entered.set();await release.wait();return {'success':True,'content':'Read'}
    task=asyncio.create_task(service.tick(execute));await entered.wait();service.stop(owner,run['id']);release.set();await task
    assert service.run(owner,run['id'])['status']=='cancelled'
    assert not store.receipts(owner)


@pytest.mark.asyncio
async def test_failure_conditions_and_recovery_do_not_replay(tmp_path):
    store=Workspace(tmp_path/'routine.db');owner,_=store.create_owner();service=RoutineService(store)
    definition=service.save(owner,Definition(title='Fallback',steps=[{'tool':'time','failure':'continue'},{'tool':'search','input_step':0,'condition':'previous_failure'}]))
    run=service.start(owner,definition['id'],1);calls=[]
    async def execute(owner,tool,arg):calls.append(arg);return {'success':tool!='time','content':'Unavailable' if tool=='time' else 'Found'}
    await service.tick(execute);await service.tick(execute)
    assert service.run(owner,run['id'])['status']=='completed' and 'Unavailable' in calls[1]
    pending=service.start(owner,definition['id'],1)
    with store.db() as db:db.execute("UPDATE routine_runs SET status='running' WHERE id=?",(pending['id'],))
    service.recover();await service.tick(execute)
    assert service.run(owner,pending['id'])['status']=='interrupted' and len(calls)==2


@pytest.mark.parametrize('steps',[[{'tool':'open_app'}],[{'tool':'time','input_step':0}],[{'tool':'reminder','due_at':'2030-01-01','argument':'x'}]])
def test_unsafe_or_unbounded_steps_rejected(steps):
    with pytest.raises(ValidationError):Definition(title='Invalid',steps=steps)
