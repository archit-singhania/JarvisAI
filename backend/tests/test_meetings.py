import io
import pytest
from fastapi import HTTPException, UploadFile
from app.workspace import Workspace
from app.meetings import Meetings,Notes


@pytest.mark.asyncio
async def test_success_deletes_only_after_durable_transcription(tmp_path):
    store=Workspace(tmp_path/'work.db');owner,_=store.create_owner();other,_=store.create_owner();jobs=Meetings(store)
    audio=UploadFile(filename='sample.wav',file=io.BytesIO(b'fixture audio'))
    job=await jobs.upload(owner,'QA meeting',audio,False,True)
    assert job['audio_present'] and job['status']=='queued'
    async def engine(path):assert path.is_file();return [{'start':0.0,'end':1.0,'text':'Illustrative meeting'}]
    await jobs.tick(engine)
    done=Meetings(Workspace(store.path)).get(owner,job['id'])
    assert done['status']=='completed' and not done['audio_present']
    assert done['transcript'][0]['text']=='Illustrative meeting'
    with pytest.raises(KeyError):jobs.get(other,job['id'])
    jobs.save_notes(owner,job['id'],Notes(revision=0,notes='Reviewed',decisions=['Proceed'],proposed_reminders=['Check release']))
    with pytest.raises(HTTPException):jobs.save_notes(owner,job['id'],Notes(revision=0,notes='Stale'))
    assert not store.reminders(owner) # A proposal never creates an actual reminder.


@pytest.mark.asyncio
async def test_failure_retains_retry_and_explicit_retention(tmp_path):
    store=Workspace(tmp_path/'work.db');owner,_=store.create_owner();jobs=Meetings(store)
    job=await jobs.upload(owner,'Failed',UploadFile(filename='sample.wav',file=io.BytesIO(b'fixture')),False,True)
    async def failed(path):raise RuntimeError('No configured engine')
    await jobs.tick(failed)
    assert jobs.get(owner,job['id'])['audio_present'] and jobs.get(owner,job['id'])['status']=='failed'
    jobs.retry(owner,job['id'])
    async def invalid(path):return [{'start':5,'end':1,'text':'Invalid'}]
    await jobs.tick(invalid)
    assert jobs.get(owner,job['id'])['audio_present']
    jobs.delete(owner,job['id']);assert not list(jobs.root.iterdir())
    retained=await jobs.upload(owner,'Retained',UploadFile(filename='sample.mp3',file=io.BytesIO(b'fixture')),True,True)
    async def successful(path):return []
    await jobs.tick(successful)
    assert jobs.get(owner,retained['id'])['audio_present']
    jobs.delete(owner,retained['id']);assert not list(jobs.root.iterdir())


@pytest.mark.asyncio
async def test_consent_required_before_private_file_write(tmp_path):
    store=Workspace(tmp_path/'work.db');owner,_=store.create_owner();jobs=Meetings(store)
    with pytest.raises(HTTPException):await jobs.upload(owner,'No consent',UploadFile(filename='x.wav',file=io.BytesIO(b'fixture')),False,False)
    assert not list(jobs.root.iterdir()) and not jobs.list(owner)
