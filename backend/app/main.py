"""Wednesday workspace API and versioned realtime protocol."""
import ast
import asyncio
import base64
import importlib.util
import io
import json
import logging
import os
import platform
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from app.config import settings
from app.workspace import Workspace
from app.runtime import Runtime
from app.llm.client import LLMClient

logger = logging.getLogger('wednesday')
store = Workspace(Path(os.environ.get('WEDNESDAY_DATA_DIR', str(settings.DATA_DIR))) / 'workspace.db')
runtimes = set()
origins = {x.strip() for x in settings.ALLOWED_ORIGINS.split(',') if x.strip()}
wake_listener = None


def token_from(request):
    authorization = request.headers.get('authorization','')
    if authorization.startswith('Bearer '):
        return authorization[7:]
    protocols = request.headers.get('sec-websocket-protocol','').split(',')
    protocol_token = next((p.strip()[6:] for p in protocols if p.strip().startswith('token.')),None)
    return request.cookies.get('wednesday_token') or protocol_token


def owner(request: Request):
    identity = store.authenticate(token_from(request))
    if not identity:
        raise HTTPException(401,'Create or restore a workspace session first')
    return identity


async def reminder_loop():
    while True:
        for reminder in store.due_reminders():
            for runtime in tuple(runtimes):
                if runtime.owner == reminder['owner']:
                    try:
                        await runtime.send('reminder',content=reminder['text'],reminder_id=reminder['id'],due_at=reminder['due_at'])
                    except Exception:
                        logger.debug('Reminder delivery deferred until reconnect')
        await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(reminder_loop())
    yield
    task.cancel()
    await asyncio.gather(task,return_exceptions=True)
    for runtime in tuple(runtimes):
        await runtime.interrupt(False)
    if wake_listener:
        wake_listener.stop()


app = FastAPI(title='Wednesday / AuraScript',version='1.0.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=list(origins),allow_credentials=True,allow_methods=['GET','POST','PATCH','DELETE'],allow_headers=['Authorization','Content-Type','X-Requested-With'])


@app.middleware('http')
async def protect_browser(request, call_next):
    origin = request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and origin not in origins:
        return JSONResponse(status_code=403,content={'detail':'Origin is not allowed'})
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(KeyError)
async def not_found(request, error):
    return JSONResponse(status_code=404,content={'detail':'Owned resource not found'})


@app.get('/')
def root():
    return RedirectResponse('/ui/')


@app.get('/health')
def health():
    with store.db() as db:
        db.execute('SELECT 1')
    return {'status':'ready','version':1,'demo_mode':settings.DEMO_MODE}


@app.post('/api/session')
def bootstrap(request: Request,response: Response):
    token = token_from(request)
    identity = store.authenticate(token)
    if not identity:
        identity,token = store.create_owner()
    response.set_cookie('wednesday_token',token,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=60*60*24*365)
    return {'owner_id':identity,'token':token,'preferences':store.prefs(identity)}


@app.get('/api/conversations')
def conversations(q: str='', identity=Depends(owner)):
    return {'conversations':store.conversations(identity,q[:200])}


class ConversationInput(BaseModel):
    title: str = Field(default='New conversation',max_length=100)
    mode: Literal['assistant','coding','research','focus'] = 'assistant'


@app.post('/api/conversations')
def create_conversation(body: ConversationInput,identity=Depends(owner)):
    return store.conversation(identity,title=body.title,mode=body.mode)


@app.get('/api/conversations/{conversation_id}')
def history(conversation_id: str,identity=Depends(owner)):
    return {**store.conversation(identity,conversation_id),'messages':store.history(identity,conversation_id)}


@app.delete('/api/conversations/{conversation_id}')
def delete_conversation(conversation_id: str,identity=Depends(owner)):
    store.delete_conversation(identity,conversation_id)
    return {'deleted':True}


class Preferences(BaseModel):
    theme: Literal['system','light','dark'] | None = None
    reduce_motion: bool | None = None
    reduce_transparency: bool | None = None
    focus: Literal['assistant','coding','research','focus'] | None = None
    language: str | None = Field(default=None,max_length=20)
    tts: bool | None = None
    llm_provider: Literal['ollama','groq','openai','gemini'] | None = None
    llm_model: str | None = Field(default=None,max_length=100)
    ollama_model: str | None = Field(default=None,max_length=100)


@app.get('/api/preferences')
def get_preferences(identity=Depends(owner)):
    return store.prefs(identity)


@app.patch('/api/preferences')
def preferences(body: Preferences,identity=Depends(owner)):
    return store.prefs(identity,body.model_dump(exclude_none=True))


class RecordInput(BaseModel):
    title: str = Field(min_length=1,max_length=200)
    content: str = Field(min_length=1,max_length=200000)


@app.get('/api/memories')
def memories(identity=Depends(owner)):
    return {'memories':store.records(identity,'memory')}


@app.post('/api/memories')
def add_memory(body: RecordInput,identity=Depends(owner)):
    return {'id':store.save_record(identity,'memory',body.title,body.content)}


@app.patch('/api/memories/{record_id}')
def edit_memory(record_id: str,body: RecordInput,identity=Depends(owner)):
    if not any(r['id']==record_id and r['kind']=='memory' for r in store.records(identity)):
        raise KeyError(record_id)
    return {'id':store.save_record(identity,'memory',body.title,body.content,identity=record_id)}


@app.delete('/api/records/{record_id}')
def delete_record(record_id: str,identity=Depends(owner)):
    if not store.delete_record(identity,record_id):
        raise KeyError(record_id)
    return {'deleted':True}


@app.get('/api/documents')
def documents(identity=Depends(owner)):
    return {'documents':[{k:v for k,v in r.items() if k!='content'} for r in store.records(identity,'document')]}


@app.post('/api/documents')
async def upload_document(file: UploadFile,identity=Depends(owner)):
    raw = await file.read(10*1024*1024+1)
    if len(raw)>10*1024*1024:
        raise HTTPException(413,'Document exceeds 10 MB')
    filename = Path(file.filename or 'document').name
    try:
        if filename.lower().endswith('.pdf'):
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            text = '\n\n'.join(p.extract_text() or '' for p in reader.pages)
        elif Path(filename).suffix.lower() in ('.txt','.md','.csv','.json','.py','.js','.ts','.cs','.dart'):
            text = raw.decode('utf-8-sig')
        else:
            raise HTTPException(415,'Upload PDF, UTF-8 text, Markdown, CSV, JSON, or a supported source file')
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422,'Document could not be read; scanned PDFs require OCR before import')
    if not text.strip():
        raise HTTPException(422,'Document contains no extractable text')
    identity_record = store.save_record(identity,'document',filename,text[:2000000],{'retrieval':'lexical','bytes':len(raw)})
    return {'id':identity_record,'title':filename,'characters':len(text),'retrieval':'lexical'}


@app.get('/api/search')
def search(q: str,identity=Depends(owner)):
    return {'conversations':store.conversations(identity,q[:200]),'sources':store.retrieve(identity,q[:200],10)}


class ReminderInput(BaseModel):
    text: str = Field(min_length=1,max_length=500)
    due_at: str
    timezone: str = 'Asia/Kolkata'


@app.get('/api/reminders')
def reminders(identity=Depends(owner)):
    return {'reminders':store.reminders(identity)}


@app.post('/api/reminders')
def add_reminder(body: ReminderInput,identity=Depends(owner)):
    try:
        ZoneInfo(body.timezone)
        result = store.add_reminder(identity,body.text,body.due_at,body.timezone)
    except (ValueError,ZoneInfoNotFoundError):
        raise HTTPException(422,'Supply an ISO date/time and valid IANA timezone. Local times during a daylight-saving gap are invalid.')
    return {'id':result}


@app.delete('/api/reminders/{reminder_id}')
def cancel_reminder(reminder_id: str,identity=Depends(owner)):
    if not store.cancel_reminder(identity,reminder_id):
        raise KeyError(reminder_id)
    return {'cancelled':True}


@app.get('/api/export')
def export(identity=Depends(owner)):
    return JSONResponse(store.export(identity),headers={'Content-Disposition':'attachment; filename="wednesday-workspace.json"'})


@app.get('/api/receipts')
def receipts(identity=Depends(owner)):
    return {'receipts':store.receipts(identity)}


@app.get('/api/capabilities')
async def capabilities(identity=Depends(owner)):
    models, local_error = [], None
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(settings.OLLAMA_HOST.rstrip('/')+'/api/tags')
            response.raise_for_status()
            models = [m['name'] for m in response.json().get('models',[])]
    except Exception:
        local_error = 'Ollama is not reachable. Install/start Ollama and download a model.'
    return {'llm':{'ollama':{'available':bool(models),'models':models,'detail':local_error},'groq':{'available':settings.has_groq()},'openai':{'available':bool(settings.OPENAI_API_KEY)},'gemini':{'available':bool(settings.GEMINI_API_KEY)}},'speech':{'server_tts':settings.TTS_PROVIDER!='none','provider':settings.TTS_PROVIDER,'local_stt':importlib.util.find_spec('whisper') is not None,'groq_stt':settings.has_groq()},'vision':{'local_models':[m for m in models if any(k in m for k in ('llava','vision','gemma3'))],'openai':bool(settings.OPENAI_API_KEY)},'wake_word':{'available':not settings.DEMO_MODE and importlib.util.find_spec('openwakeword') is not None and importlib.util.find_spec('pyaudio') is not None},'host_tools':not settings.DEMO_MODE,'retrieval':'local lexical source retrieval'}


class CodeInput(BaseModel):
    code: str = Field(min_length=1,max_length=100000)
    language: str = Field(default='python',max_length=30)
    question: str = Field(default='Review this code and explain actionable improvements.',max_length=1000)


@app.post('/api/code/diagnostics')
def diagnostics(body: CodeInput,identity=Depends(owner)):
    findings = []
    if body.language == 'python':
        try:
            ast.parse(body.code)
        except SyntaxError as error:
            findings.append({'line':error.lineno,'column':error.offset,'severity':'error','message':error.msg})
    elif body.language == 'json':
        try:
            json.loads(body.code)
        except json.JSONDecodeError as error:
            findings.append({'line':error.lineno,'column':error.colno,'severity':'error','message':error.msg})
    else:
        return {'diagnostics':[],'supported':False,'detail':'Use Monaco language services for this language'}
    return {'diagnostics':findings,'supported':True}


@app.post('/api/code/analyze')
async def analyze(body: CodeInput,identity=Depends(owner)):
    prefs = store.prefs(identity)
    configuration = settings.model_copy(update={k.upper():prefs[k] for k in ('llm_provider','llm_model','ollama_model')})
    try:
        result = await LLMClient(configuration).generate_response([{'role':'user','content':f'{body.question}\nLanguage: {body.language}\n```\n{body.code}\n```'}])
    except Exception:
        raise HTTPException(503,'Code review engine unavailable; configure a provider')
    return {'response':result['content']}


class ToolInput(BaseModel):
    tool: Literal['time','weather','search','open_app']
    argument: str = Field(default='',max_length=300)
    confirmed: bool = False


@app.post('/api/tools/execute')
async def tools(body: ToolInput,identity=Depends(owner)):
    if body.tool == 'open_app':
        if settings.DEMO_MODE:
            raise HTTPException(403,'Host tools are disabled in hosted demo mode')
        if not body.confirmed:
            raise HTTPException(409,'Confirm this host action before execution')
        allowed = {'Windows':{'calculator':['calc.exe'],'notepad':['notepad.exe']},'Darwin':{'calculator':['open','-a','Calculator'],'notes':['open','-a','Notes']},'Linux':{'calculator':['gnome-calculator']}}.get(platform.system(),{})
        command = allowed.get(body.argument.lower())
        if not command:
            raise HTTPException(422,'Select a supported app from the allowlist')
        try:
            await asyncio.create_subprocess_exec(*command)
            result = {'success':True,'content':f'Launched {body.argument}'}
        except OSError:
            raise HTTPException(503,'The selected app is unavailable on this device')
    elif body.tool == 'time':
        result = {'success':True,'content':datetime.now().astimezone().isoformat()}
    else:
        from app.tools.manager import get_weather, web_search
        content = await (get_weather(body.argument) if body.tool=='weather' else web_search(body.argument))
        result = {'success':not content.lower().startswith(('search failed','couldn\'t','weather unavailable')),'content':content}
    result['receipt_id'] = store.receipt(identity,body.tool,result)
    return result


class WorkflowInput(BaseModel):
    title: str = Field(min_length=1,max_length=100)
    steps: list[ToolInput] = Field(min_length=1,max_length=10)


@app.get('/api/workflows')
def workflows(identity=Depends(owner)):
    return {'workflows':store.records(identity,'workflow')}


@app.post('/api/workflows')
def save_workflow(body: WorkflowInput,identity=Depends(owner)):
    return {'id':store.save_record(identity,'workflow',body.title,json.dumps([s.model_dump() for s in body.steps]))}


@app.post('/api/workflows/{workflow_id}/run')
async def run_workflow(workflow_id: str,identity=Depends(owner)):
    record = next((r for r in store.records(identity,'workflow') if r['id']==workflow_id),None)
    if not record:
        raise KeyError(workflow_id)
    results = []
    for step in json.loads(record['content']):
        command = ToolInput.model_validate(step)
        if command.tool == 'open_app':
            raise HTTPException(409,'Host actions require individual confirmation and cannot run from a workflow')
        results.append(await tools(command,identity))
    return {'results':results}


@app.post('/api/wake-word/{action}')
async def wake_word(action: Literal['start','stop'],identity=Depends(owner)):
    global wake_listener
    if settings.DEMO_MODE:
        raise HTTPException(403,'Local microphone access disabled in demo mode')
    if action == 'stop':
        if wake_listener:
            wake_listener.stop()
        wake_listener = None
        return {'active':False}
    if importlib.util.find_spec('openwakeword') is None or importlib.util.find_spec('pyaudio') is None:
        raise HTTPException(503,'Install the optional wake-word dependencies and model first')
    if wake_listener:
        raise HTTPException(409,'Wake-word listener already active')
    from app.speech.wake_word import WakeWordListener
    loop = asyncio.get_running_loop()
    async def notify():
        for runtime in tuple(runtimes):
            if runtime.owner==identity:
                await runtime.interrupt()
                await runtime.send('wake_detected')
    wake_listener = WakeWordListener(lambda:loop.call_soon_threadsafe(lambda:loop.create_task(notify())))
    try:
        await asyncio.to_thread(wake_listener.start)
    except Exception as error:
        wake_listener = None
        raise HTTPException(503,'Wake-word model or microphone could not start. Install its ONNX model and allow microphone access.') from error
    return {'active':True,'detail':'Local wake-word model and microphone are active'}


@app.websocket('/ws')
async def socket(ws: WebSocket):
    origin = ws.headers.get('origin')
    if origin and origin not in origins:
        await ws.close(1008)
        return
    identity = store.authenticate(token_from(ws))
    if not identity:
        await ws.close(1008)
        return
    try:
        conversation = store.conversation(identity,ws.query_params.get('conversation_id'))
    except KeyError:
        await ws.close(1008)
        return
    await ws.accept(subprotocol='wednesday.v1' if 'wednesday.v1' in ws.headers.get('sec-websocket-protocol','') else None)
    runtime = Runtime(ws,store,identity,conversation['id'])
    runtimes.add(runtime)
    await runtime.send('session',preferences=store.prefs(identity),history=store.history(identity,conversation['id']))
    try:
        while True:
            data = await ws.receive_json()
            if not isinstance(data,dict):
                await runtime.send('error',code='invalid_message',content='Message must be a JSON object')
                continue
            kind = data.get('type')
            if kind == 'interrupt':
                await runtime.interrupt()
            elif kind == 'text':
                text = str(data.get('content','')).strip()
                if not text or len(text)>12000:
                    await runtime.send('error',code='invalid_text',content='Text must contain 1–12000 characters')
                else:
                    await runtime.start(text=text,speak=bool(data.get('tts',False)))
            elif kind == 'audio':
                try:
                    encoded = data.get('audio_b64','')
                    if len(encoded)>14*1024*1024:
                        raise ValueError()
                    raw = base64.b64decode(encoded,validate=True)
                    if not raw or len(raw)>10*1024*1024:
                        raise ValueError()
                    await runtime.start(audio=raw,speak=bool(data.get('tts',True)),language=str(data.get('language','en'))[:20])
                except (ValueError,TypeError):
                    await runtime.send('error',code='invalid_audio',content='Upload valid audio under 10 MB')
            elif kind == 'clear':
                await runtime.interrupt(False)
                runtime.conversation = store.conversation(identity)['id']
                await runtime.send('cleared')
            elif kind == 'code_context':
                runtime.context = f"File: {str(data.get('file',''))[:200]}\n{str(data.get('content',''))[:12000]}"
                await runtime.send('context_updated')
            elif kind == 'reminder_ack':
                store.acknowledge_reminder(identity,str(data.get('reminder_id','')))
            elif kind in ('screen','image'):
                try:
                    encoded = data.get('image_b64','')
                    if not isinstance(encoded,str) or len(encoded)>12*1024*1024:
                        raise ValueError()
                    raw = base64.b64decode(encoded,validate=True)
                    if not raw or len(raw)>8*1024*1024:
                        raise ValueError()
                    await runtime.start_image(raw,str(data.get('prompt','Describe this selected image.'))[:500])
                except (ValueError,TypeError):
                    await runtime.send('error',code='invalid_image',content='Select a PNG, JPEG, or WebP image under 8 MB.')
            else:
                await runtime.send('error',code='unknown_message',content='Unsupported message type')
    except (WebSocketDisconnect,RuntimeError):
        pass
    finally:
        await runtime.interrupt(False)
        runtimes.discard(runtime)


app.mount('/ui',StaticFiles(directory=str(Path(__file__).resolve().parents[2]/'ui'),html=True),name='ui')
