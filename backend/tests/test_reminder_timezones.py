import pytest
from app.workspace import Workspace


def test_local_zone_conversion_and_dst_gap_rejection(tmp_path):
    store=Workspace(tmp_path/'db');owner,_=store.create_owner()
    store.add_reminder(owner,'India time','2027-12-01T09:00','Asia/Kolkata')
    assert store.reminders(owner)[0]['due_at']=='2027-12-01T03:30:00+00:00'
    with pytest.raises(ValueError):
        store.add_reminder(owner,'Invalid clock time','2027-03-14T02:30','America/New_York')
