"""Bounded, durable routines. Each consequential step has a separate confirmation gate."""
import asyncio
import json
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from app.workspace import timestamp


class Step(BaseModel):
    tool: Literal['time', 'search', 'weather', 'assistant', 'reminder']
    argument: str = Field(default='', max_length=2000)
    input_step: int | None = Field(default=None, ge=0, le=19)
    condition: Literal['always', 'previous_success', 'previous_failure'] = 'always'
    failure: Literal['stop', 'continue'] = 'stop'
    due_at: datetime | None = None
    timezone: str = Field(default='UTC', max_length=100)

    @model_validator(mode='after')
    def valid(self):
        if self.tool == 'reminder':
            if not self.argument.strip() or not self.due_at or not self.due_at.tzinfo:
                raise ValueError('Reminders need text and a timezone-aware due date')
            try:ZoneInfo(self.timezone)
            except (ZoneInfoNotFoundError, ValueError):raise ValueError('Choose a valid IANA timezone')
        return self


class Definition(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    steps: list[Step] = Field(min_length=1, max_length=20)
    revision: int = Field(default=0, ge=0)

    @model_validator(mode='after')
    def backward_refs(self):
        for i, step in enumerate(self.steps):
            if step.input_step is not None and step.input_step >= i:
                raise ValueError('Input references must point to an earlier step')
        return self


class RoutineService:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS routines(id TEXT PRIMARY KEY,owner TEXT NOT NULL,title TEXT NOT NULL,
              steps TEXT NOT NULL,revision INTEGER NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS routine_runs(id TEXT PRIMARY KEY,owner TEXT NOT NULL,routine TEXT NOT NULL,
              snapshot TEXT NOT NULL,status TEXT NOT NULL,cursor INTEGER NOT NULL,results TEXT NOT NULL,
              confirmed INTEGER NOT NULL DEFAULT -1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            ''')

    def definitions(self, owner):
        with self.store.db() as db:
            result=[dict(r) for r in db.execute('SELECT * FROM routines WHERE owner=? ORDER BY updated_at DESC', (owner,))]
        for r in result:r['steps']=json.loads(r['steps'])
        return result

    def save(self, owner, body, identity=None):
        identity=identity or uuid4().hex
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM routines WHERE id=?',(identity,)).fetchone()
            if row and row['owner']!=owner:raise KeyError(identity)
            if (row['revision'] if row else 0)!=body.revision:raise HTTPException(409,'Routine changed; reload before saving')
            db.execute('INSERT INTO routines VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,steps=excluded.steps,revision=excluded.revision,updated_at=excluded.updated_at',
                       (identity,owner,body.title,json.dumps([s.model_dump(mode='json') for s in body.steps]),body.revision+1,timestamp()))
        return next(r for r in self.definitions(owner) if r['id']==identity)

    def definition(self, owner, identity):
        row=next((r for r in self.definitions(owner) if r['id']==identity),None)
        if not row:raise KeyError(identity)
        return row

    def preview(self, owner, identity):
        row=self.definition(owner,identity)
        return {'revision':row['revision'],'steps':[{'index':i,**s,'confirmation_required':s['tool'] in ('assistant','reminder')}
                for i,s in enumerate(row['steps'])],'executes':False}

    def start(self, owner, identity, revision):
        row=self.definition(owner,identity)
        if row['revision']!=revision:raise HTTPException(409,'Review the current routine before running')
        rid,now=uuid4().hex,timestamp()
        with self.store.db() as db:
            db.execute('INSERT INTO routine_runs VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (rid,owner,identity,json.dumps(row),'queued',0,'[]',-1,now,now))
        return self.run(owner,rid)

    def run(self, owner, identity):
        with self.store.db() as db:
            row=db.execute('SELECT * FROM routine_runs WHERE id=? AND owner=?',(identity,owner)).fetchone()
        if not row:raise KeyError(identity)
        row=dict(row);row['snapshot']=json.loads(row['snapshot']);row['results']=json.loads(row['results'])
        return row

    def runs(self, owner):
        with self.store.db() as db:ids=[r['id'] for r in db.execute('SELECT id FROM routine_runs WHERE owner=? ORDER BY created_at DESC LIMIT 50',(owner,))]
        return [self.run(owner,r) for r in ids]

    def confirm(self, owner, identity, cursor):
        with self.store.db() as db:
            if not db.execute("UPDATE routine_runs SET confirmed=cursor,status='queued',updated_at=? WHERE id=? AND owner=? AND status='awaiting_confirmation' AND cursor=?",
                              (timestamp(),identity,owner,cursor)).rowcount:raise HTTPException(409,'This step is no longer waiting for confirmation')
        return self.run(owner,identity)

    def stop(self, owner, identity):
        self.run(owner,identity)
        with self.store.db() as db:
            db.execute("UPDATE routine_runs SET status='cancelled',updated_at=? WHERE id=? AND owner=? AND status IN ('queued','running','awaiting_confirmation')",(timestamp(),identity,owner))
        return self.run(owner,identity)

    def recover(self):
        # Never replay an ambiguous external operation after a crash.
        with self.store.db() as db:
            db.execute("UPDATE routine_runs SET status='interrupted',updated_at=? WHERE status='running'",(timestamp(),))

    async def tick(self, execute):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM routine_runs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:return
            row=dict(row)
            db.execute("UPDATE routine_runs SET status='running',updated_at=? WHERE id=?",(timestamp(),row['id']))
        snapshot=json.loads(row['snapshot']);results=json.loads(row['results']);cursor=row['cursor']
        step=snapshot['steps'][cursor]
        condition=step['condition']
        previous=results[-1].get('success',False) if results else False
        skip=(condition=='previous_success' and not previous) or (condition=='previous_failure' and previous)
        if not skip and step['tool'] in ('assistant','reminder') and row['confirmed']!=cursor:
            with self.store.db() as db:
                db.execute("UPDATE routine_runs SET status='awaiting_confirmation',updated_at=? WHERE id=? AND status='running'",(timestamp(),row['id']))
            return
        if skip:result={'success':True,'skipped':True,'content':'Condition not met'}
        else:
            argument=step['argument']
            if step['input_step'] is not None:
                argument+='\n'+str(results[step['input_step']].get('content',''))[:4000]
            try:
                if step['tool']=='reminder':
                    # Same transaction as receipt/result update; Stop is checked before the write.
                    result={'success':True,'content':argument}
                else:result=await asyncio.wait_for(execute(row['owner'],step['tool'],argument),timeout=60)
            except asyncio.CancelledError:
                raise
            except Exception:
                result={'success':False,'content':'Step failed or timed out; check provider configuration.'}
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT status FROM routine_runs WHERE id=?',(row['id'],)).fetchone()
            if current['status']!='running':return
            if not skip and step['tool']=='reminder':
                reminder=uuid4().hex
                db.execute('INSERT INTO reminders(id,owner,text,due_at,timezone) VALUES(?,?,?,?,?)',
                           (reminder,row['owner'],argument,datetime.fromisoformat(step['due_at']).astimezone(timezone.utc).isoformat(),step['timezone']))
                result['reminder_id']=reminder
            receipt=uuid4().hex
            db.execute('INSERT INTO receipts VALUES(?,?,?,?,?)',(receipt,row['owner'],'routine:'+step['tool'],json.dumps(result),timestamp()))
            results.append({**result,'step':cursor,'receipt_id':receipt})
            status='failed' if not result['success'] and step['failure']=='stop' else ('completed' if cursor+1==len(snapshot['steps']) else 'queued')
            db.execute('UPDATE routine_runs SET status=?,cursor=?,results=?,updated_at=? WHERE id=?',
                       (status,cursor+1,json.dumps(results),timestamp(),row['id']))


def router(get_store,owner):
    routes=APIRouter(prefix='/api/routines',tags=['Routines'])
    def service():return RoutineService(get_store())

    @routes.get('')
    def definitions(identity=Depends(owner)):return {'routines':service().definitions(identity)}
    @routes.post('')
    def create(body:Definition,identity=Depends(owner)):return service().save(identity,body)
    @routes.put('/{rid}')
    def update(rid:str,body:Definition,identity=Depends(owner)):return service().save(identity,body,rid)
    @routes.get('/runs')
    def runs(identity=Depends(owner)):return {'runs':service().runs(identity)}
    @routes.get('/runs/{rid}')
    def run(rid:str,identity=Depends(owner)):return service().run(identity,rid)
    @routes.post('/{rid}/preview')
    def preview(rid:str,identity=Depends(owner)):return service().preview(identity,rid)
    class Start(BaseModel):
        revision:int=Field(ge=1)
    @routes.post('/{rid}/runs')
    def start(rid:str,body:Start,identity=Depends(owner)):return service().start(identity,rid,body.revision)
    class Confirm(BaseModel):
        cursor:int=Field(ge=0,le=19)
    @routes.post('/runs/{rid}/confirm')
    def confirm(rid:str,body:Confirm,identity=Depends(owner)):return service().confirm(identity,rid,body.cursor)
    @routes.post('/runs/{rid}/stop')
    def stop(rid:str,identity=Depends(owner)):return service().stop(identity,rid)
    return routes
