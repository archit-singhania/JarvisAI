"""Private meeting jobs. Raw audio is removed only after a durable transcript commit."""
import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from app.workspace import timestamp


class Notes(BaseModel):
    revision:int=Field(ge=0)
    notes:str=Field(default='',max_length=100000)
    decisions:list[str]=Field(default_factory=list,max_length=100)
    proposed_reminders:list[str]=Field(default_factory=list,max_length=100)


class Meetings:
    def __init__(self,store):
        self.store=store;self.root=store.path.parent/'meeting-audio'
        self.root.mkdir(exist_ok=True)
        if self.root.is_symlink():raise RuntimeError('Meeting storage must be private local storage')
        with store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS meetings(
              id TEXT PRIMARY KEY,owner TEXT NOT NULL,title TEXT NOT NULL,filename TEXT NOT NULL,
              retain INTEGER NOT NULL,status TEXT NOT NULL,transcript TEXT NOT NULL DEFAULT '[]',
              error TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '{}',revision INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,updated_at TEXT NOT NULL);''')

    def capability(self):
        model=os.environ.get('WEDNESDAY_MEETING_MODEL','')
        ready=bool(model and Path(model).is_dir() and importlib.util.find_spec('faster_whisper'))
        return {'available':ready,'engine':'faster-whisper local','detail':'Install the speech dependencies and provision a local model directory; set WEDNESDAY_MEETING_MODEL. No models are downloaded automatically.'}

    def path(self,row):
        path=self.root/row['filename']
        if path.parent!=self.root or path.is_symlink():raise RuntimeError('Invalid private audio path')
        return path

    def get(self,owner,identity):
        with self.store.db() as db:row=db.execute('SELECT * FROM meetings WHERE id=? AND owner=?',(identity,owner)).fetchone()
        if not row:raise KeyError(identity)
        row=dict(row);row['transcript']=json.loads(row['transcript']);row['notes']=json.loads(row['notes']);row['audio_present']=self.path(row).is_file();row.pop('filename')
        return row

    def list(self,owner):
        with self.store.db() as db:ids=[r['id'] for r in db.execute('SELECT id FROM meetings WHERE owner=? ORDER BY created_at DESC LIMIT 100',(owner,))]
        return [self.get(owner,i) for i in ids]

    async def upload(self,owner,title,file,retain,consent):
        if not consent:raise HTTPException(422,'Confirm participant consent before importing or recording a meeting')
        suffix=Path(file.filename or '').suffix.lower()
        if suffix not in ('.wav','.mp3','.m4a','.ogg','.webm','.flac'):raise HTTPException(415,'Choose WAV, MP3, M4A, OGG, WebM or FLAC audio')
        identity=uuid4().hex;filename=identity+suffix;path=self.root/filename
        count=0
        try:
            with path.open('xb') as target:
                os.chmod(path,0o600)
                while chunk:=await file.read(1024*1024):
                    count+=len(chunk)
                    if count>100*1024*1024:raise HTTPException(413,'Meeting audio limit is 100 MB')
                    target.write(chunk)
            if not count:raise HTTPException(422,'Audio file is empty')
            now=timestamp()
            with self.store.db() as db:
                db.execute('INSERT INTO meetings(id,owner,title,filename,retain,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                           (identity,owner,title[:200],filename,int(retain),'queued',now,now))
        except BaseException:
            path.unlink(missing_ok=True);raise
        finally:await file.close()
        return self.get(owner,identity)

    def save_notes(self,owner,identity,body):
        self.get(owner,identity)
        with self.store.db() as db:
            changed=db.execute('UPDATE meetings SET notes=?,revision=revision+1,updated_at=? WHERE id=? AND owner=? AND revision=?',
                               (json.dumps(body.model_dump(exclude={'revision'})),timestamp(),identity,owner,body.revision)).rowcount
        if not changed:raise HTTPException(409,'Meeting notes changed; reload before saving')
        return self.get(owner,identity)

    def retry(self,owner,identity):
        self.get(owner,identity)
        with self.store.db() as db:
            if not db.execute("UPDATE meetings SET status='queued',error='',updated_at=? WHERE id=? AND owner=? AND status IN ('failed','interrupted')",(timestamp(),identity,owner)).rowcount:
                raise HTTPException(409,'Only failed or interrupted jobs can retry')
        return self.get(owner,identity)

    def delete(self,owner,identity):
        self.get(owner,identity)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM meetings WHERE id=? AND owner=?',(identity,owner)).fetchone()
            if row:self.path(row).unlink(missing_ok=True)
            db.execute('DELETE FROM meetings WHERE id=? AND owner=?',(identity,owner))

    def recover(self):
        with self.store.db() as db:db.execute("UPDATE meetings SET status='queued' WHERE status='processing'")

    async def tick(self,transcribe):
        # Finish deferred deletion even when a process stopped after transcript persistence.
        with self.store.db() as db:
            cleanup=[dict(r) for r in db.execute("SELECT * FROM meetings WHERE status='completed' AND retain=0")]
        for r in cleanup:
            try:self.path(r).unlink(missing_ok=True)
            except OSError:pass
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM meetings WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:return
            row=dict(row);db.execute("UPDATE meetings SET status='processing',updated_at=? WHERE id=?",(timestamp(),row['id']))
        try:
            segments=await transcribe(self.path(row))
            if not isinstance(segments,list) or len(segments)>100000:raise ValueError('Invalid transcript')
            previous=0
            for s in segments:
                if not isinstance(s.get('text'),str) or not 0<=s['start']<=s['end']<=86400 or s['start']<previous:raise ValueError('Invalid timestamps')
                previous=s['start']
            with self.store.db() as db:
                changed=db.execute("UPDATE meetings SET status='completed',transcript=?,error='',updated_at=? WHERE id=? AND status='processing'",
                                   (json.dumps(segments),timestamp(),row['id'])).rowcount
            if changed and not row['retain']:self.path(row).unlink(missing_ok=True)
        except asyncio.CancelledError:raise
        except Exception:
            with self.store.db() as db:
                db.execute("UPDATE meetings SET status='failed',error='Transcription unavailable or failed. Audio is retained until success or explicit deletion.',updated_at=? WHERE id=? AND status='processing'",(timestamp(),row['id']))


async def local_transcribe(path):
    model=os.environ.get('WEDNESDAY_MEETING_MODEL','')
    if not model or not Path(model).is_dir() or not importlib.util.find_spec('faster_whisper'):
        raise RuntimeError('Local meeting engine not configured')
    output=path.with_suffix('.transcript.json')
    process=await asyncio.create_subprocess_exec(sys.executable,'-m','app.meeting_worker',str(path),str(output),model,
                                                stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(process.wait(),1200)
        if process.returncode:raise RuntimeError('Local transcription failed')
        if output.stat().st_size>16*1024*1024:raise RuntimeError('Transcript too large')
        return json.loads(output.read_text(encoding='utf-8'))
    finally:
        if process.returncode is None:process.kill();await process.wait()
        output.unlink(missing_ok=True)


def router(get_store,owner):
    routes=APIRouter(prefix='/api/meetings',tags=['Meetings'])
    def service():return Meetings(get_store())
    @routes.get('')
    def listing(identity=Depends(owner)):return {'meetings':service().list(identity),'capability':service().capability()}
    @routes.post('')
    async def upload(file:UploadFile=File(...),title:str=Form('Meeting'),retain:bool=Form(False),consent:bool=Form(False),identity=Depends(owner)):
        return await service().upload(identity,title,file,retain,consent)
    @routes.get('/{mid}')
    def get(mid:str,identity=Depends(owner)):return service().get(identity,mid)
    @routes.patch('/{mid}')
    def notes(mid:str,body:Notes,identity=Depends(owner)):return service().save_notes(identity,mid,body)
    @routes.post('/{mid}/retry')
    def retry(mid:str,identity=Depends(owner)):return service().retry(identity,mid)
    @routes.delete('/{mid}')
    def delete(mid:str,identity=Depends(owner)):service().delete(identity,mid);return {'deleted':True}
    return routes
