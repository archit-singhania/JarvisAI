"""
Girl Wednesday AI — FastAPI main v10
Fixes vs v9:
  - No real name ever spoken/displayed — address is always "Sir"
  - stream_end sends content:"" only — UI must NOT re-render from it (v10 UI handles this)
  - VAD fires after 1.8s silence (handled in frontend); backend stays clean
  - Greeting: pure "Sir" only, no name field used
  - Mood persona no longer embeds name in LLM context
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
logger = logging.getLogger("wednesday")

# ── RAG skip keywords ──────────────────────────────────────────────
_NO_RAG = {
    "time", "weather", "joke", "rap", "sing", "open", "launch",
    "search", "remind", "alarm", "calculate", "what time",
    "temperature", "forecast", "date", "timer", "screenshot", "volume", "mute",
    "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
    "how are you", "feeling", "mood",
}

def _needs_rag(text: str) -> bool:
    return not any(kw in text.lower() for kw in _NO_RAG)

def _is_creative(text: str) -> bool:
    return bool(text) and any(text.startswith(t) for t in ("[RAP_MODE", "[SING_MODE", "[JOKE_MODE"))


# ── Session state ─────────────────────────────────────────────────
class Session:
    def __init__(self):
        self.greeted = False
        self.mood_asked = False
        self.mood = "neutral"
        self.project_introduced = False
        self.last_project = None
        self.speaking = False


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
        self.active = [w for w in self.active if w is not ws]
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
            self.disconnect(ws)

    def broadcast_threadsafe(self, data: dict):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(data), self._loop)


manager = ConnectionManager()


# ── Lifespan ───────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_event_loop()
    manager.set_loop(loop)

    logger.info(f"🌙 Wednesday v10 | TTS:{settings.TTS_PROVIDER} | LLM:{settings.LLM_MODEL}")

    from app.tools.scheduler import ReminderScheduler
    db_path = Path(settings.DATA_DIR) / "reminders.db"

    def _on_reminder(text: str):
        manager.broadcast_threadsafe({"type": "reminder", "content": text})

    orchestrator.scheduler = ReminderScheduler(db_path, _on_reminder)
    await orchestrator.scheduler.start()

    from app.tools.code_watcher import CodeWatcher
    orchestrator.code_watcher = CodeWatcher(
        on_interrupt=lambda msg: manager.broadcast_threadsafe({"type": "code_interrupt", "content": msg}),
        llm_client=orchestrator.llm_client,
        speech_processor=orchestrator.speech_processor,
        manager=manager,
    )
    orchestrator.code_watcher.start()

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

    logger.info("🌙 Wednesday signing off")
    for attr in ("wake_listener", "scheduler", "code_watcher"):
        obj = getattr(orchestrator, attr, None)
        if obj:
            try: obj.stop()
            except Exception: pass


app = FastAPI(title="Girl Wednesday AI", version="10.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

_ui_path = Path(__file__).parent.parent.parent / "ui"
_ui_path.mkdir(exist_ok=True)
app.mount("/ui", StaticFiles(directory=str(_ui_path), html=True), name="ui")


# ── Health ─────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "online", "version": "10.0.0", "name": "Girl Wednesday",
            "ui": "http://localhost:8000/ui",
            "address": settings.USER_NAME}

@app.get("/health")
async def health():
    return {
        "llm": settings.LLM_MODEL, "tts": settings.TTS_PROVIDER,
        "stt": settings.WHISPER_MODEL,
        "edge_voice": settings.EDGE_TTS_VOICE,
        "elevenlabs_voice": settings.ELEVENLABS_VOICE_ID,
        "user_addr": settings.USER_NAME,
        "groq_ok": settings.has_groq(),
        "elevenlabs_ok": settings.has_elevenlabs(),
    }


# ── Config endpoints ────────────────────────────────────────────────
@app.get("/api/config")
async def get_config():
    return {
        "tts_provider":          settings.TTS_PROVIDER,
        "elevenlabs_voice_id":   settings.ELEVENLABS_VOICE_ID,
        "edge_tts_voice":        settings.EDGE_TTS_VOICE,
        "llm_model":             settings.LLM_MODEL,
        "temperature":           settings.TEMPERATURE,
        "location_name":         settings.LOCATION_NAME,
        "jarvis_persona":        settings.JARVIS_PERSONA,
        "user_name":             settings.USER_NAME,
        "elevenlabs_configured": settings.has_elevenlabs(),
        "code_watch_enabled":    settings.CODE_WATCH_ENABLED,
    }

@app.patch("/api/config")
async def patch_config(body: dict):
    allowed = {
        "tts_provider","elevenlabs_voice_id","elevenlabs_model_id",
        "elevenlabs_stability","elevenlabs_similarity","elevenlabs_style",
        "elevenlabs_speaker_boost","edge_tts_voice","edge_tts_rate",
        "edge_tts_volume","edge_tts_pitch","llm_model","temperature",
        "max_tokens","location_name","location_lat","location_lon",
        "jarvis_persona","user_name",
        "wake_word_enabled","code_watch_enabled","code_watch_path",
    }
    applied = {}
    for key, val in body.items():
        if key.lower() not in allowed:
            continue
        attr = key.upper()
        try:
            cur = getattr(settings, attr, None)
            if isinstance(cur, bool):    val = str(val).lower() in ("true","1","yes")
            elif isinstance(cur, float): val = float(val)
            elif isinstance(cur, int):   val = int(val)
            object.__setattr__(settings, attr, val)
            applied[key] = val
        except Exception as e:
            logger.warning(f"Patch {key}: {e}")
    _write_env(applied)
    return {"applied": applied}

@app.post("/api/config/reload")
async def reload_config():
    settings.reload()
    return {"status": "reloaded"}

def _write_env(patch: dict):
    try:
        env_path = Path(__file__).parent.parent / ".env"
        if not env_path.exists():
            return
        lines = env_path.read_text().splitlines()
        km = {k.upper(): str(v) for k, v in patch.items()}
        new, done = [], set()
        for line in lines:
            s = line.strip()
            if s.startswith("#") or "=" not in s:
                new.append(line); continue
            ek = s.split("=", 1)[0].strip().upper()
            if ek in km:
                new.append(f"{ek}={km[ek]}"); done.add(ek)
            else:
                new.append(line)
        for k, v in km.items():
            if k not in done:
                new.append(f"{k}={v}")
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
        voices = [
            {"voice_id": v["voice_id"], "name": v["name"],
             "category": v.get("category",""), "preview_url": v.get("preview_url",""),
             "labels": v.get("labels",{})}
            for v in r.json().get("voices", [])
        ]
        voices.sort(key=lambda x: (x["category"] != "premade", x["name"]))
        return {"voices": voices, "current": settings.ELEVENLABS_VOICE_ID}
    except Exception as e:
        return {"error": str(e), "voices": []}

@app.get("/api/elevenlabs/usage")
async def elevenlabs_usage():
    if not settings.has_elevenlabs():
        return {"error": "Not configured"}
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get("https://api.elevenlabs.io/v1/user",
                            headers={"xi-api-key": settings.ELEVENLABS_API_KEY})
        sub = r.json().get("subscription", {})
        used, lim = sub.get("character_count", 0), sub.get("character_limit", 10000)
        return {"used": used, "limit": lim, "remaining": lim - used}
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
    code     = body.get("code", "")
    lang     = body.get("language", "python")
    question = body.get("question", "Review this code. Give concise actionable feedback.")
    if not code:
        return JSONResponse(status_code=400, content={"error": "code required"})

    prompt = (
        f"You are reviewing {lang} code. They ask: '{question}'\n\n"
        f"```{lang}\n{code}\n```\n\n"
        f"Address the user as 'Sir'. Be concise — 2 sentences max. "
        f"Speak naturally. Be direct, witty, and helpful."
    )
    result = await orchestrator.llm_client.generate_response(
        messages=[{"role": "user", "content": prompt}])
    response_text = result.get("content", "")
    tts = await orchestrator.speech_processor.synthesize(response_text)
    if tts.get("audio_data"):
        manager.broadcast_threadsafe({
            "type": "code_feedback", "content": response_text,
            "audio_b64": base64.b64encode(tts["audio_data"]).decode(),
            "audio_format": tts.get("format", "mp3"),
        })
    return {"response": response_text}


# ── WebSocket ───────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    session = manager.session(ws)
    logger.info("WS connected")

    await _do_greeting(ws, session)

    try:
        while True:
            data  = await ws.receive_json()
            mtype = data.get("type")

            if mtype == "interrupt":
                interrupt_handler.interrupt()
                session.speaking = False
                await ws.send_json({"type": "interrupted"})
                continue

            interrupt_handler.reset()

            if mtype == "text":
                txt = data.get("content", "").strip()
                if txt:
                    await _handle_text(ws, session, txt, speak=data.get("tts", True))

            elif mtype == "audio":
                raw = data.get("audio_b64", "")
                if raw:
                    await _handle_audio(ws, session, base64.b64decode(raw))

            elif mtype == "code_context":
                if hasattr(orchestrator, "code_watcher"):
                    await orchestrator.code_watcher.update_context(data)
                await _maybe_intro_project(ws, session, data)

            elif mtype == "clear":
                orchestrator.clear_history()
                session.greeted = False
                session.mood_asked = False
                session.project_introduced = False
                session.mood = "neutral"
                await ws.send_json({"type": "cleared"})
                await _do_greeting(ws, session)

    except WebSocketDisconnect:
        manager.disconnect(ws)
        logger.info("WS disconnected")
    except Exception as e:
        logger.error(f"WS error: {e}", exc_info=True)
        manager.disconnect(ws)


# ── Greeting — says "Sir" only, never a name ───────────────────────
async def _do_greeting(ws: WebSocket, session: Session):
    if session.greeted:
        return
    session.greeted = True

    hour = datetime.now().hour
    if 5 <= hour < 12:
        time_str = "morning"
    elif 12 <= hour < 17:
        time_str = "afternoon"
    elif 17 <= hour < 21:
        time_str = "evening"
    else:
        time_str = "night"

    greeting = (
        f"Good {time_str}, Sir. I'm Wednesday — ready when you are. "
        f"How are you feeling, and what are we working on?"
    )

    session.mood_asked = True
    await ws.send_json({"type": "response", "content": greeting, "is_greeting": True})
    await _send_tts(ws, greeting)
    _add_history(None, greeting)


async def _maybe_intro_project(ws: WebSocket, session: Session, data: dict):
    if session.project_introduced:
        return
    file_path = data.get("file", "")
    content   = data.get("content", "")
    lang      = data.get("language", "code")
    if not content or not file_path or len(content) < 50:
        return

    session.project_introduced = True
    filename = file_path.split("/")[-1]

    mood_ctx = {
        "frustrated": "The user is frustrated — lead with something encouraging.",
        "tired":      "The user is tired — one sentence only.",
    }.get(session.mood, "")

    prompt = (
        f"{mood_ctx}\n"
        f"You've just looked at the file '{filename}' ({lang}):\n\n"
        f"```{lang}\n{content[:1500]}\n```\n\n"
        f"Give a 2-sentence take: what this does, and one thing worth focusing on. "
        f"Address the user as 'Sir'. Be direct, witty, and natural."
    )

    try:
        result = await orchestrator.llm_client.generate_response(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=settings.JARVIS_PERSONA
        )
        intro = result.get("content", "")
        if intro:
            await ws.send_json({"type": "response", "content": intro, "is_project_intro": True})
            await _send_tts(ws, intro)
            _add_history(None, intro)
    except Exception as e:
        logger.error(f"Project intro error: {e}")


# ── Mood detection ──────────────────────────────────────────────────
def _detect_mood(text: str) -> str:
    lower = text.lower()
    if any(w in lower for w in ["great","amazing","fantastic","excited","good","happy","awesome","well","brilliant","splendid"]):
        return "positive"
    if any(w in lower for w in ["tired","exhausted","sleepy","slow","not great","knackered","low"]):
        return "tired"
    if any(w in lower for w in ["frustrated","annoyed","stuck","bad","angry","stressed","not good","terrible","awful","rubbish"]):
        return "frustrated"
    return "neutral"

def _mood_adjusted_persona(mood: str, base_persona: str) -> str:
    ctx = {
        "positive":   "The user is in high spirits — match their energy, be playful.",
        "tired":      "The user is exhausted — be gentle, very brief, one sentence answers only.",
        "frustrated": "The user is frustrated — be calm, patient, and focused on solutions. No jokes.",
    }.get(mood, "")
    return f"{base_persona}\n\n{ctx}" if ctx else base_persona


# ── Text handler ────────────────────────────────────────────────────
async def _handle_text(ws: WebSocket, session: Session, user_text: str, speak: bool = True):
    # Mood ack on first mood reply
    if session.mood_asked and session.mood == "neutral":
        mood_words = ["great","tired","okay","fine","bad","good","frustrated","yeah",
                      "brilliant","terrible","alright","knackered","low","not great","splendid"]
        if any(w in user_text.lower() for w in mood_words):
            detected = _detect_mood(user_text)
            session.mood = detected if detected != "neutral" else "neutral"
            mood_acks = {
                "positive":   "Excellent — let's make the most of it, Sir. What are we working on?",
                "tired":      "Understood, Sir. We'll keep things quick and painless.",
                "frustrated": "Fair enough, Sir. Let's sort whatever's vexing you.",
                "neutral":    "Right then, Sir. What shall we tackle today?",
            }
            ack = mood_acks.get(session.mood, "Right, Sir. What are we building?")
            await ws.send_json({"type": "response", "content": ack})
            if speak:
                await _send_tts(ws, ack)
            _add_history(None, ack)
            return

    tool_result = await orchestrator.tool_manager.detect_and_execute(user_text)
    if tool_result and tool_result.get("success"):
        text = tool_result["result"]
        if not _is_creative(text):
            await ws.send_json({"type": "response", "content": text, "tool_used": tool_result["tool"]})
            if speak:
                await _send_tts(ws, text)
            _add_history(user_text, text)
            return
        user_text = text

    persona = _mood_adjusted_persona(session.mood, settings.JARVIS_PERSONA)
    orchestrator.conversation_history.append(
        {"role": "user", "content": user_text, "timestamp": datetime.now().isoformat()})
    orchestrator._trim_history()
    rag = await orchestrator.rag_engine.query(user_text) if _needs_rag(user_text) else None

    await ws.send_json({"type": "stream_start"})
    session.speaking = True
    full = await _stream_and_speak(ws, session, rag, speak, system_prompt=persona)
    session.speaking = False
    # stream_end carries no content — UI must not re-render from it
    await ws.send_json({"type": "stream_end", "content": ""})
    _add_history(None, full)


# ── Audio handler ────────────────────────────────────────────────────
async def _handle_audio(ws: WebSocket, session: Session, audio_data: bytes):
    await ws.send_json({"type": "stt_start"})
    tr = await orchestrator.speech_processor.transcribe(audio_data)

    if not tr.get("success") or not tr.get("text", "").strip():
        await ws.send_json({"type": "stt_error", "content": "Didn't quite catch that."})
        return

    user_text = tr["text"].strip()
    await ws.send_json({"type": "transcript", "content": user_text})
    logger.info(f"Heard: '{user_text}'")

    # Stop command
    if any(w in user_text.lower() for w in {"stop","cancel","shut up","be quiet","silence","quiet","enough","hush"}):
        interrupt_handler.interrupt()
        session.speaking = False
        resp = "Of course, Sir."
        await ws.send_json({"type": "response", "content": resp, "tool_used": "interrupt"})
        await _send_tts(ws, resp)
        return

    # Mood detection from greeting response
    if session.mood_asked and session.mood == "neutral":
        mood_words = ["great","tired","okay","fine","bad","good","frustrated","yeah",
                      "brilliant","terrible","alright","knackered","low","not great","splendid"]
        if any(w in user_text.lower() for w in mood_words):
            detected = _detect_mood(user_text)
            session.mood = detected if detected != "neutral" else "neutral"
            mood_acks = {
                "positive":   "Brilliant. Let's get cracking, Sir.",
                "tired":      "Right then, Sir. Quick and efficient it is.",
                "frustrated": "Say no more. Let's fix whatever's broken, Sir.",
                "neutral":    "Right, Sir. What are we working on today?",
            }
            ack = mood_acks.get(session.mood, "Right. What are we building, Sir?")
            await ws.send_json({"type": "response", "content": ack})
            await _send_tts(ws, ack)
            _add_history(None, ack)
            return

    # Code context injection
    code_kws = {"code","function","file","my code","bug","error","refactor","explain",
                "how does","review","debug","fix","approach","better way","what does","improve"}
    if any(kw in user_text.lower() for kw in code_kws) and hasattr(orchestrator, "code_watcher"):
        ctx = orchestrator.code_watcher.get_context_snippet()
        if ctx:
            user_text = f"{user_text}\n\n[Current code context]\n{ctx}"

    tool_result = await orchestrator.tool_manager.detect_and_execute(user_text)
    if tool_result and tool_result.get("success"):
        text = tool_result["result"]
        if not _is_creative(text):
            await ws.send_json({"type": "response", "content": text, "tool_used": tool_result["tool"]})
            await _send_tts(ws, text)
            _add_history(user_text, text)
            return
        user_text = text

    persona = _mood_adjusted_persona(session.mood, settings.JARVIS_PERSONA)
    orchestrator.conversation_history.append(
        {"role": "user", "content": user_text, "timestamp": datetime.now().isoformat()})
    orchestrator._trim_history()
    rag = await orchestrator.rag_engine.query(user_text) if _needs_rag(user_text) else None

    await ws.send_json({"type": "stream_start"})
    session.speaking = True
    full = await _stream_and_speak(ws, session, rag, speak=True, system_prompt=persona)
    session.speaking = False
    await ws.send_json({"type": "stream_end", "content": ""})
    _add_history(None, full)


# ── Stream + speak ──────────────────────────────────────────────────
async def _stream_and_speak(
    ws: WebSocket, session: Session, rag,
    speak: bool, system_prompt: Optional[str] = None
) -> str:
    full = ""
    buf  = ""

    try:
        async for token in orchestrator.llm_client.stream_response(
                messages=orchestrator.conversation_history,
                rag_context=rag,
                system_prompt=system_prompt):

            if interrupt_handler.is_interrupted:
                await ws.send_json({"type": "stream_interrupted"})
                session.speaking = False
                return full

            full += token
            buf  += token
            await ws.send_json({"type": "stream_chunk", "content": token})

            if speak and _ends_sentence(buf):
                sentence = buf.strip()
                buf = ""
                if sentence:
                    asyncio.create_task(_send_tts(ws, sentence))

    except Exception as e:
        logger.error(f"LLM stream error: {e}")
        err = "Terribly sorry, Sir — something went sideways on my end. Shall we try again?"
        await ws.send_json({"type": "stream_chunk", "content": err})
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
                "audio_format": result.get("format", "mp3"),
                "text":         text,
            })
    except Exception as e:
        logger.warning(f"TTS send error: {e}")


def _ends_sentence(text: str) -> bool:
    s = text.strip()
    return bool(s) and (s[-1] in '.!?…' or (s[-1] == ',' and len(s) > 80))

def _add_history(user: Optional[str], assistant: str):
    ts = datetime.now().isoformat()
    if user:
        orchestrator.conversation_history.append({"role": "user", "content": user, "timestamp": ts})
    orchestrator.conversation_history.append({"role": "assistant", "content": assistant, "timestamp": ts})


# ── REST endpoints ──────────────────────────────────────────────────
@app.post("/api/speech/synthesize")
async def synthesize(request: dict):
    text = request.get("text", "")
    if not text:
        return JSONResponse(status_code=400, content={"error": "text required"})
    result = await orchestrator.speech_processor.synthesize(text)
    if result.get("success"):
        mime = "audio/wav" if result.get("format") == "wav" else "audio/mpeg"
        return Response(content=result["audio_data"], media_type=mime)
    return JSONResponse(status_code=500, content={"error": "TTS failed"})

@app.post("/api/rag/add")
async def rag_add(request: dict):
    meta = request.get("metadata") or {"source": "user"}
    ok = await orchestrator.rag_engine.add_document(
        request.get("text", ""),
        request.get("doc_id", f"doc_{__import__('time').time()}"),
        meta)
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
