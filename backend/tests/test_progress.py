from app.workspace import Workspace
from app.routines import RoutineService,Definition,Step
from app.meetings import Meetings
from app.progress import Progress

def test_owned_reconnect_and_changed_progress(tmp_path):
    store=Workspace(tmp_path/'workspace.db');RoutineService(store);Meetings(store)
    with store.db() as db:
        db.execute("INSERT INTO routine_runs VALUES(?,?,?,?,?,?,?,?,?,?)",('run','owner','routine','{}','queued',0,'[]',-1,'2026-10-16','2026-10-16'))
    observer=Progress(store)
    assert observer.changes('other')==[]
    first=observer.changes('owner');assert first[0]['status']=='queued'
    assert set(first[0])=={'type','id','status','updated_at','cursor'}
    assert observer.changes('owner')==[]
    with store.db() as db:db.execute("UPDATE routine_runs SET status='completed',updated_at='later' WHERE id='run'")
    assert observer.changes('owner')[0]['status']=='completed'
    assert Progress(store).changes('owner')[0]['status']=='completed'
