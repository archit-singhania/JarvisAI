"""Explicit redacted local retrieval cases. Never invokes a model or tool."""
import hashlib
import json
import time
import ast
import asyncio
from uuid import uuid4
from app.workspace import timestamp


class Evaluations:
    def __init__(self, store):
        self.store=store
        with store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS evaluation_cases(id TEXT PRIMARY KEY,owner TEXT NOT NULL,value TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evaluation_runs(id TEXT PRIMARY KEY,owner TEXT NOT NULL,value TEXT NOT NULL,created_at TEXT NOT NULL);''')

    def list(self, owner):
        with self.store.db() as db:
            return {key:[dict(r,value=json.loads(r['value'])) for r in db.execute('SELECT id,value,created_at FROM '+table+' WHERE owner=? ORDER BY created_at DESC LIMIT 100',(owner,))] for key,table in [('cases','evaluation_cases'),('runs','evaluation_runs')]}

    def save(self, owner, value):
        allowed={r['id'] for r in self.store.records(owner)}
        if not set(value['expected_sources']).issubset(allowed): raise ValueError('Choose source IDs owned by this workspace')
        identity=uuid4().hex
        with self.store.db() as db: db.execute('INSERT INTO evaluation_cases VALUES(?,?,?,?)',(identity,owner,json.dumps(value),timestamp()))
        return {'id':identity}

    def run(self, owner, identity):
        with self.store.db() as db: row=db.execute('SELECT * FROM evaluation_cases WHERE id=? AND owner=?',(identity,owner)).fetchone()
        if not row: raise KeyError(identity)
        case=json.loads(row['value']); started=time.perf_counter()
        kind=case.get('kind','retrieval')
        sources=self.store.retrieve(owner,case['query']) if kind=='retrieval' else []
        found={r['id'] for r in sources}
        expected=set(case['expected_sources'])
        result={'case_id':identity,'formula_version':'local-retrieval-v1','case_sha256':hashlib.sha256(row['value'].encode()).hexdigest(),'provider':'local','model':None,'latency_ms':round((time.perf_counter()-started)*1000,3),'passed':expected.issubset(found),'missing_sources':sorted(expected-found),'sources':[{'id':r['id'],'sha256':hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest()} for r in sources],'coverage':'Local retrieval source availability only; tool correctness, model quality and cancellation are not measured.'}
        if kind=='python_diagnostics':
            diagnostic=None
            try:ast.parse(case['query'])
            except SyntaxError as error:diagnostic={'line':error.lineno,'message':error.msg}
            result.update(formula_version='python-diagnostics-v1',passed=bool(diagnostic)==case.get('expect_error',False),diagnostic=diagnostic,coverage='Python syntax diagnostic correctness; code is parsed, never executed.')
        async def cancellation_probe():
            from app.runtime import Runtime
            class Socket:
                def __init__(self):self.events=[]
                async def send_json(self,event):self.events.append(event)
            socket=Socket();runtime=Runtime(socket,self.store,owner,'evaluation-fixture')
            runtime.task=asyncio.create_task(asyncio.Event().wait())
            await asyncio.sleep(0)
            begin=time.perf_counter()
            await asyncio.wait_for(runtime.interrupt(),timeout=1)
            return {'passed':runtime.task.cancelled() and socket.events[-1]['type']=='interrupted','latency_ms':round((time.perf_counter()-begin)*1000,3),'scope':'Synthetic waiting task through the real Runtime.interrupt method; does not certify provider or audio cancellation.'}
        result['cancellation_probe']=asyncio.run(cancellation_probe())
        result['configuration']={'retrieval_limit':3,'kind':kind,'runtime':'python','external_calls':False}
        result['latency_ms']=round((time.perf_counter()-started)*1000,3)
        result['passed']=result['passed'] and result['cancellation_probe']['passed']
        run_id=uuid4().hex
        with self.store.db() as db: db.execute('INSERT INTO evaluation_runs VALUES(?,?,?,?)',(run_id,owner,json.dumps(result),timestamp()))
        return dict(result,id=run_id)

    def delete(self, owner, identity):
        with self.store.db() as db:
            db.execute('DELETE FROM evaluation_cases WHERE id=? AND owner=?',(identity,owner))
            for row in db.execute('SELECT id,value FROM evaluation_runs WHERE owner=?',(owner,)).fetchall():
                if json.loads(row['value'])['case_id']==identity: db.execute('DELETE FROM evaluation_runs WHERE id=?',(row['id'],))
