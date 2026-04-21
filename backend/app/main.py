"""
Daisy AI — FastAPI main v7
New in this version:
  - Greeting on connect: "Hi Sir, Archit! How are you feeling today?"
  - Mood detection: adjusts tone based on user's mood response
  - Project analysis: when code_context arrives for first time in session,
    Daisy proactively analyses it and suggests what to work on
  - TTS_PROVIDER=edge fixes ElevenLabs 402 error (library voices require paid plan)
  - Better persona injection with USER_NAME
  - Session state: tracks mood, greeted, project_introduced flags
  - No more double responses
"""
import asyncio
import base64
import logging
import logging.config
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import settings, LOGGING_CONFIG
from app.orchestrator.orchestrator import orchestrator
from app.speech.interrupt import interrupt_handler

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("jarvis")

# ── RAG skip keywords ──────────────────────────────────────────────
_NO_RAG = {
    "time", "weather", "joke", "rap", "sing", "open", "launch",
    "search", "remind", "alarm", "calculate", "what time",
    "temperature", "forecast", "date", "timer", "screenshot", "volume", "mute",
    "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
    "how are you", "feeling", "mood",
}

def _needs_rag(text: str) -> bool:
    lower = text.lower()
    return not any(kw in lower for kw in _NO_RAG)

def _is_creative(text: str) -> bool:
    return any(text.startswith(t) for t in ("[RAP_MODE", "[SING_MODE", "[JOKE_MODE"))


# ── Session state (per connection) ────────────────────────────────
class Session:
    def __init__(self):
        self.greeted = False
        self.mood_asked = False
        self.mood = "neutral"           # positive / neutral / frustrated / tired
        self.project_introduced = False  # has Daisy spoken about the open project yet?
        self.last_project = None         # last file path seen


# ── Connection manager ─────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []
        self.sessions: dict[WebSocket, Session] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        self.sessions[ws] = Session()

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
        self.sessions.pop(ws, None)

    def session(self, ws: WebSocket) -> Session:
        return self.sessions.get(ws, Session())

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)
            self.sessions.pop(ws, None)

    def broadcast_threadsafe(self, data: dict):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(data), self._loop)


manager = ConnectionManager()


# ── Lifespan ───────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_event_loop()
    manager.set_loop(loop)

    tts_desc = f"{settings.TTS_PROVIDER}({settings.EDGE_TTS_VOICE if settings.TTS_PROVIDER=='edge' else settings.ELEVENLABS_VOICE_ID})"
    logger.info(f"🚀 Daisy AI v7 | TTS:{tts_desc} | LLM:{settings.LLM_MODEL} | STT:{settings.WHISPER_MODEL} | User:{settings.USER_NAME}")

    # Reminder scheduler
    from app.tools.scheduler import ReminderScheduler
    db_path = Path(settings.DATA_DIR) / "reminders.db"

    def _on_reminder(text: str):
        manager.broadcast_threadsafe({"type": "reminder", "content": text})

    orchestrator.scheduler = ReminderScheduler(db_path, _on_reminder)
    await orchestrator.scheduler.start()

    # Code watcher
    from app.tools.code_watcher import CodeWatcher
    orchestrator.code_watcher = CodeWatcher(
        on_interrupt=lambda msg: manager.broadcast_threadsafe({"type": "code_interrupt", "content": msg}),
        llm_client=orchestrator.llm_client,
        speech_processor=orchestrator.speech_processor,
        manager=manager,
    )
    orchestrator.code_watcher.start()

    # Wake word
    if settings.WAKE_WORD_ENABLED:
        try:
            from app.speech.wake_word import WakeWordListener

            def _on_wake():
                interrupt_handler.interrupt()
                manager.broadcast_threadsafe({"type": "wake_detected", "content": "Listening…"})

            orchestrator.wake_listener = WakeWordListener(on_detected=_on_wake)
            orchestrator.wake_listener.start()
            logger.info("Wake word active")
        except Exception as e:
            logger.warning(f"Wake word skipped: {e}")

    yield

    logger.info("👋 Shutting down")
    for attr in ("wake_listener", "scheduler", "code_watcher"):
        if hasattr(orchestrator, attr):
            try: getattr(orchestrator, attr).stop()
            except Exception: pass


app = FastAPI(title="Daisy AI", version="7.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

_ui_path = Path(__file__).parent.parent.parent / "ui"
_ui_path.mkdir(exist_ok=True)
app.mount("/ui", StaticFiles(directory=str(_ui_path), html=True), name="ui")


# ── Health / info ───────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "online", "version": "7.0.0", "ui": "http://localhost:8000/ui",
            "user": settings.USER_NAME}

@app.get("/health")
async def health():
    return {
        "llm": settings.LLM_MODEL, "tts": settings.TTS_PROVIDER,
        "stt": settings.WHISPER_MODEL,
        "edge_voice": settings.EDGE_TTS_VOICE,
        "user": settings.USER_NAME,
        "groq_ok": settings.has_groq(),
    }


# ── Config endpoints ────────────────────────────────────────────────
@app.get("/api/config")
async def get_config():
    return {
        "tts_provider": settings.TTS_PROVIDER,
        "elevenlabs_voice_id": settings.ELEVENLABS_VOICE_ID,
        "elevenlabs_model_id": settings.ELEVENLABS_MODEL_ID,
        "elevenlabs_stability": settings.ELEVENLABS_STABILITY,
        "elevenlabs_similarity": settings.ELEVENLABS_SIMILARITY,
        "elevenlabs_style": settings.ELEVENLABS_STYLE,
        "edge_tts_voice": settings.EDGE_TTS_VOICE,
        "llm_model": settings.LLM_MODEL,
        "temperature": settings.TEMPERATURE,
        "location_name": settings.LOCATION_NAME,
        "location_lat": settings.LOCATION_LAT,
        "location_lon": settings.LOCATION_LON,
        "jarvis_persona": settings.JARVIS_PERSONA,
        "user_name": settings.USER_NAME,
        "elevenlabs_configured": settings.has_elevenlabs(),
        "code_watch_enabled": settings.CODE_WATCH_ENABLED,
        "code_watch_path": settings.CODE_WATCH_PATH,
    }

@app.patch("/api/config")
async def patch_config(body: dict):
    allowed = {
        "tts_provider", "elevenlabs_voice_id", "elevenlabs_model_id",
        "elevenlabs_stability", "elevenlabs_similarity", "elevenlabs_style",
        "elevenlabs_speaker_boost", "edge_tts_voice", "edge_tts_rate",
        "edge_tts_volume", "edge_tts_pitch", "llm_model", "temperature",
        "max_tokens", "location_name", "location_lat", "location_lon",
        "jarvis_persona", "user_name", "wake_word_enabled",
        "code_watch_enabled", "code_watch_path",
    }
    applied = {}
    for key, val in body.items():
        if key.lower() not in allowed: continue
        attr = key.upper()
        try:
            cur = getattr(settings, attr, None)
            if isinstance(cur, bool):    val = str(val).lower() in ("true","1","yes")
            elif isinstance(cur, float): val = float(val)
            elif isinstance(cur, int):   val = int(val)
            object.__setattr__(settings, attr, val)
            applied[key] = val
            logger.info(f"Config: {attr} = {val}")
        except Exception as e:
            logger.warning(f"Patch {key}: {e}")
    _write_env(applied)
    return {"applied": applied}

@app.post("/api/config/reload")
async def reload_config():
    settings.reload()
    return {"status": "reloaded", "tts_provider": settings.TTS_PROVIDER}

def _write_env(patch: dict):
    try:
        env_path = Path(__file__).parent.parent / ".env"
        if not env_path.exists(): return
        lines = env_path.read_text().splitlines()
        km = {k.upper(): str(v) for k, v in patch.items()}
        new, done = [], set()
        for line in lines:
            s = line.strip()
            if s.startswith("#") or "=" not in s:
                new.append(line); continue
            ek = s.split("=",1)[0].strip().upper()
            if ek in km:
                new.append(f"{ek}={km[ek]}"); done.add(ek)
            else:
                new.append(line)
        for k, v in km.items():
            if k not in done: new.append(f"{k}={v}")
        env_path.write_text("\n".join(new) + "\n")
    except Exception as e:
        logger.warning(f"Could not write .env: {e}")


# ── ElevenLabs endpoints ────────────────────────────────────────────
@app.get("/api/elevenlabs/voices")
async def elevenlabs_voices():
    if not settings.has_elevenlabs():
        return {"error": "Not configured", "voices": []}
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get("https://api.elevenlabs.io/v1/voices",
                            headers={"xi-api-key": settings.ELEVENLABS_API_KEY})
        voices = [{"voice_id": v["voice_id"], "name": v["name"],
                   "category": v.get("category",""), "preview_url": v.get("preview_url",""),
                   "labels": v.get("labels",{})}
                  for v in r.json().get("voices",[])]
        voices.sort(key=lambda x: (x["category"] != "premade", x["name"]))
        return {"voices": voices, "current": settings.ELEVENLABS_VOICE_ID}
    except Exception as e:
        return {"error": str(e), "voices": []}

@app.get("/api/elevenlabs/usage")
async def elevenlabs_usage():
    if not settings.has_elevenlabs(): return {"error": "Not configured"}
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get("https://api.elevenlabs.io/v1/user",
                            headers={"xi-api-key": settings.ELEVENLABS_API_KEY})
        sub = r.json().get("subscription", {})
        used, lim = sub.get("character_count",0), sub.get("character_limit",10000)
        return {"used": used, "limit": lim, "remaining": lim-used}
    except Exception as e:
        return {"error": str(e)}


# ── Code endpoints ──────────────────────────────────────────────────
@app.post("/api/code/context")
async def receive_code_context(body: dict):
    if hasattr(orchestrator, "code_watcher"):
        await orchestrator.code_watcher.update_context(body)
    return {"status": "received"}

@app.post("/api/code/analyze")
async def analyze_code(body: dict):
    code = body.get("code",""); lang = body.get("language","python")
    question = body.get("question","Review this code. Give concise actionable feedback.")
    if not code: return JSONResponse(status_code=400, content={"error":"code required"})
    name = settings.USER_NAME
    prompt = (
        f"You are reviewing {lang} code for {name}. They ask: '{question}'\n\n"
        f"```{lang}\n{code}\n```\n\n"
        f"Address {name} by name. Be concise — 2-3 sentences max. Speak naturally."
    )
    result = await orchestrator.llm_client.generate_response(
        messages=[{"role":"user","content":prompt}])
    response_text = result.get("content","")
    tts = await orchestrator.speech_processor.synthesize(response_text)
    if tts.get("audio_data"):
        manager.broadcast_threadsafe({
            "type": "code_feedback", "content": response_text,
            "audio_b64": base64.b64encode(tts["audio_data"]).decode(),
            "audio_format": tts.get("format","mp3"),
        })
    return {"response": response_text}


# ── WebSocket ───────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    session = manager.session(ws)
    logger.info(f"WS connected | user:{settings.USER_NAME}")

    # ── Greeting on connect ──────────────────────────────────────────
    await _do_greeting(ws, session)

    try:
        while True:
            data  = await ws.receive_json()
            mtype = data.get("type")

            if mtype == "interrupt":
                interrupt_handler.interrupt()
                await ws.send_json({"type": "interrupted"})
                continue

            interrupt_handler.reset()

            if mtype == "text":
                txt = data.get("content","").strip()
                if txt:
                    await _handle_text(ws, session, txt, speak=data.get("tts", True))

            elif mtype == "audio":
                raw = data.get("audio_b64","")
                if raw:
                    await _handle_audio(ws, session, base64.b64decode(raw))

            elif mtype == "code_context":
                if hasattr(orchestrator, "code_watcher"):
                    await orchestrator.code_watcher.update_context(data)
                # Proactive project intro (once per session)
                await _maybe_intro_project(ws, session, data)

            elif mtype == "clear":
                orchestrator.clear_history()
                # Reset session so Daisy greets again
                session.greeted = False
                session.mood_asked = False
                session.project_introduced = False
                await ws.send_json({"type": "cleared"})
                await _do_greeting(ws, session)

    except WebSocketDisconnect:
        manager.disconnect(ws)
        logger.info("WS disconnected")
    except Exception as e:
        logger.error(f"WS error: {e}", exc_info=True)
        manager.disconnect(ws)


# ── Greeting flow ───────────────────────────────────────────────────
async def _do_greeting(ws: WebSocket, session: Session):
    """
    On every new connection (or after clear), Daisy greets Archit by name,
    asks how he's feeling, and sets the mood for the session.
    """
    if session.greeted:
        return
    session.greeted = True

    name = settings.USER_NAME
    hour = datetime.now().hour
    if 5 <= hour < 12:   time_of_day = "Good morning"
    elif 12 <= hour < 17: time_of_day = "Good afternoon"
    elif 17 <= hour < 21: time_of_day = "Good evening"
    else:                 time_of_day = "Hey"

    greeting = (
        f"{time_of_day}, {name}! Great to see you. "
        f"How are you feeling today? Ready to build something amazing?"
    )

    session.mood_asked = True

    # Send as a Daisy message + speak it
    await ws.send_json({"type": "response", "content": greeting, "is_greeting": True})
    await _send_tts(ws, greeting)
    _add_history(None, greeting)


async def _maybe_intro_project(ws: WebSocket, session: Session, data: dict):
    """
    When a file is opened for the first time in this session,
    Daisy proactively analyses it and suggests what to focus on.
    """
    if session.project_introduced:
        return

    file_path = data.get("file","")
    content   = data.get("content","")
    lang      = data.get("language","code")

    if not content or not file_path:
        return

    # Only trigger for actual code files with meaningful content
    if len(content) < 50:
        return

    session.project_introduced = True
    session.last_project = file_path
    name = settings.USER_NAME
    filename = file_path.split("/")[-1]

    # Ask LLM to briefly analyse the file
    mood_context = ""
    if session.mood == "frustrated":
        mood_context = f"Note: {name} seems frustrated today, so keep it encouraging and focus on the positives first."
    elif session.mood == "tired":
        mood_context = f"Note: {name} mentioned feeling tired — keep it brief and easy."

    prompt = (
        f"{mood_context}\n\n"
        f"You just opened {name}'s file '{filename}' ({lang}). "
        f"Here's what's in it:\n\n```{lang}\n{content[:1500]}\n```\n\n"
        f"Give a 2-3 sentence briefing: what this file does, and ONE thing to focus on or improve today. "
        f"Address {name} directly. Be warm and encouraging."
    )

    try:
        result = await orchestrator.llm_client.generate_response(
            messages=[{"role":"user","content":prompt}],
            system_prompt=settings.JARVIS_PERSONA
        )
        intro = result.get("content","")
        if intro:
            await ws.send_json({"type": "response", "content": intro, "is_project_intro": True})
            await _send_tts(ws, intro)
            _add_history(None, intro)
    except Exception as e:
        logger.error(f"Project intro error: {e}")


# ── Mood detection ──────────────────────────────────────────────────
def _detect_mood(text: str) -> str:
    """Rough mood detection from user's response to 'how are you'."""
    lower = text.lower()
    if any(w in lower for w in ["great","amazing","fantastic","excited","good","happy","awesome","well"]):
        return "positive"
    if any(w in lower for w in ["tired","exhausted","sleepy","slow","not great"]):
        return "tired"
    if any(w in lower for w in ["frustrated","annoyed","stuck","bad","angry","stressed","not good","terrible"]):
        return "frustrated"
    if any(w in lower for w in ["okay","fine","alright","ok","so-so","meh"]):
        return "neutral"
    return "neutral"


def _mood_adjusted_persona(mood: str, base_persona: str, name: str) -> str:
    """Inject mood context into the system prompt."""
    mood_ctx = {
        "positive":    f"Great, {name} is in a good mood today — match his energy, be enthusiastic.",
        "tired":       f"{name} is feeling tired today — be gentle, keep responses short, be encouraging.",
        "frustrated":  f"{name} seems frustrated — be extra patient, calm, and positive. Celebrate small wins.",
        "neutral":     f"",
    }.get(mood, "")

    return f"{base_persona}\n\n{mood_ctx}" if mood_ctx else base_persona


# ── Text handler ────────────────────────────────────────────────────
async def _handle_text(ws: WebSocket, session: Session, user_text: str, speak: bool = True):
    """Handle typed text messages."""

    # Detect mood from response to greeting
    if session.mood_asked and session.mood == "neutral":
        detected = _detect_mood(user_text)
        if detected != "neutral" or any(w in user_text.lower() for w in
                                         ["great","tired","okay","fine","bad","good","frustrated"]):
            session.mood = detected
            logger.info(f"Mood detected: {detected}")
            # Acknowledge the mood
            mood_responses = {
                "positive":   f"Love the energy, {settings.USER_NAME}! Let's make it count.",
                "tired":      f"Got it, {settings.USER_NAME} — we'll keep it easy today. I've got you.",
                "frustrated": f"I hear you, {settings.USER_NAME}. Let's take it one step at a time.",
                "neutral":    None,
            }
            ack = mood_responses.get(detected)
            if ack:
                await ws.send_json({"type": "response", "content": ack})
                if speak: await _send_tts(ws, ack)
                _add_history(None, ack)
                return

    # Tool check
    tool_result = await orchestrator.tool_manager.detect_and_execute(user_text)
    if tool_result and tool_result.get("success"):
        text = tool_result["result"]
        if not _is_creative(text):
            await ws.send_json({"type":"response","content":text,"tool_used":tool_result["tool"]})
            if speak: await _send_tts(ws, text)
            _add_history(user_text, text)
            return
        user_text = text

    # LLM with mood-aware persona
    persona = _mood_adjusted_persona(session.mood, settings.JARVIS_PERSONA, settings.USER_NAME)
    orchestrator.conversation_history.append(
        {"role":"user","content":user_text,"timestamp":datetime.now().isoformat()})
    orchestrator._trim_history()
    rag = await orchestrator.rag_engine.query(user_text) if _needs_rag(user_text) else None

    await ws.send_json({"type":"stream_start"})
    full = await _stream_and_speak(ws, rag, speak, system_prompt=persona)
    await ws.send_json({"type":"stream_end","content":""})
    _add_history(None, full)


# ── Audio (voice) handler ────────────────────────────────────────────
async def _handle_audio(ws: WebSocket, session: Session, audio_data: bytes):
    """Handle voice messages — STT → mood/tool/LLM → TTS."""

    await ws.send_json({"type":"stt_start"})
    tr = await orchestrator.speech_processor.transcribe(audio_data)

    if not tr.get("success") or not tr.get("text","").strip():
        await ws.send_json({"type":"stt_error","content":"Could not understand"})
        return

    user_text = tr["text"].strip()
    await ws.send_json({"type":"transcript","content":user_text})
    logger.info(f"Voice → '{user_text}'")

    # Stop command
    if any(w in user_text.lower() for w in {"stop","cancel","shut up","be quiet","silence","quiet"}):
        interrupt_handler.interrupt()
        resp = f"Okay, {settings.USER_NAME}."
        await ws.send_json({"type":"response","content":resp,"tool_used":"interrupt"})
        await _send_tts(ws, resp)
        return

    # Detect mood from voice response to greeting
    if session.mood_asked and session.mood == "neutral":
        detected = _detect_mood(user_text)
        if detected != "neutral" or any(w in user_text.lower() for w in
                                         ["great","tired","okay","fine","bad","good","frustrated","yeah","yep"]):
            session.mood = detected
            logger.info(f"Voice mood: {detected}")
            mood_responses = {
                "positive":   f"Love the energy, {settings.USER_NAME}! Let's get to work.",
                "tired":      f"Alright {settings.USER_NAME}, we'll keep it light today. I'm here.",
                "frustrated": f"No worries {settings.USER_NAME}, let's tackle it together step by step.",
                "neutral":    f"Alright {settings.USER_NAME}, let's get started then.",
            }
            ack = mood_responses.get(detected, f"Got it, {settings.USER_NAME}. What are we working on today?")
            await ws.send_json({"type":"response","content":ack})
            await _send_tts(ws, ack)
            _add_history(None, ack)
            return

    # Inject code context if relevant
    code_kws = {"code","function","file","my code","bug","error","refactor",
                "explain","how does","review","debug","fix","approach","better way",
                "what does this","what is this","what am i","improve"}
    if any(kw in user_text.lower() for kw in code_kws) and hasattr(orchestrator,"code_watcher"):
        ctx = orchestrator.code_watcher.get_context_snippet()
        if ctx:
            user_text = f"{user_text}\n\n[Current code context]\n{ctx}"

    # Tool check
    tool_result = await orchestrator.tool_manager.detect_and_execute(user_text)
    if tool_result and tool_result.get("success"):
        text = tool_result["result"]
        if not _is_creative(text):
            await ws.send_json({"type":"response","content":text,"tool_used":tool_result["tool"]})
            await _send_tts(ws, text)
            _add_history(user_text, text)
            return
        user_text = text

    # LLM with mood-aware persona
    persona = _mood_adjusted_persona(session.mood, settings.JARVIS_PERSONA, settings.USER_NAME)
    orchestrator.conversation_history.append(
        {"role":"user","content":user_text,"timestamp":datetime.now().isoformat()})
    orchestrator._trim_history()
    rag = await orchestrator.rag_engine.query(user_text) if _needs_rag(user_text) else None

    await ws.send_json({"type":"stream_start"})
    full = await _stream_and_speak(ws, rag, speak=True, system_prompt=persona)
    await ws.send_json({"type":"stream_end","content":""})
    _add_history(None, full)


# ── Stream + speak ──────────────────────────────────────────────────
async def _stream_and_speak(
    ws: WebSocket, rag, speak: bool,
    system_prompt: Optional[str] = None
) -> str:
    full = ""
    buf  = ""

    try:
        async for token in orchestrator.llm_client.stream_response(
                messages=orchestrator.conversation_history,
                rag_context=rag,
                system_prompt=system_prompt):

            if interrupt_handler.is_interrupted:
                await ws.send_json({"type":"stream_interrupted"})
                return full

            full += token
            buf  += token
            await ws.send_json({"type":"stream_chunk","content":token})

            if speak and _ends_sentence(buf):
                sentence = buf.strip()
                buf = ""
                if sentence:
                    asyncio.create_task(_send_tts(ws, sentence))

    except Exception as e:
        logger.error(f"LLM stream error: {e}")
        name = settings.USER_NAME
        err = f"Sorry {name}, I had a connection issue — please try again."
        await ws.send_json({"type":"stream_chunk","content":err})
        if speak:
            asyncio.create_task(_send_tts(ws, err))
        return err

    if speak and buf.strip():
        asyncio.create_task(_send_tts(ws, buf.strip()))

    return full


async def _send_tts(ws: WebSocket, text: str):
    try:
        result = await orchestrator.speech_processor.synthesize(text)
        if result.get("success") and result.get("audio_data"):
            await ws.send_json({
                "type":         "audio_chunk",
                "audio_b64":    base64.b64encode(result["audio_data"]).decode(),
                "audio_format": result.get("format","mp3"),
                "text":         text,
            })
    except Exception as e:
        logger.warning(f"TTS: {e}")


def _ends_sentence(text: str) -> bool:
    s = text.strip()
    return bool(s) and (s[-1] in '.!?…' or (s[-1] == ',' and len(s) > 80))

def _add_history(user: Optional[str], assistant: str):
    ts = datetime.now().isoformat()
    if user:
        orchestrator.conversation_history.append({"role":"user","content":user,"timestamp":ts})
    orchestrator.conversation_history.append({"role":"assistant","content":assistant,"timestamp":ts})


# ── REST ────────────────────────────────────────────────────────────
@app.post("/api/speech/synthesize")
async def synthesize(request: dict):
    text = request.get("text","")
    if not text: return JSONResponse(status_code=400, content={"error":"text required"})
    result = await orchestrator.speech_processor.synthesize(text)
    if result.get("success"):
        mime = "audio/wav" if result.get("format")=="wav" else "audio/mpeg"
        return Response(content=result["audio_data"], media_type=mime)
    return JSONResponse(status_code=500, content={"error":"TTS failed"})

@app.post("/api/rag/add")
async def rag_add(request: dict):
    meta = request.get("metadata") or {"source":"user"}
    ok = await orchestrator.rag_engine.add_document(
        request.get("text",""),
        request.get("doc_id", f"doc_{__import__('time').time()}"), meta)
    return {"success": ok}

@app.get("/api/history")
async def get_history():
    return {"history": orchestrator.get_history()}

@app.delete("/api/history")
async def clear_history():
    orchestrator.clear_history()
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
