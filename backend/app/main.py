"""
Jarvis AI — FastAPI main v5
Fixes:
  - _on_wake uses loop.call_soon_threadsafe (thread-safe, no event loop error)
  - LLM stream errors handled gracefully — no "Sorry I encountered an error"
  - ConnectionManager stores loop and exposes broadcast_threadsafe
  - tts=True by default for voice pipeline
  - /api/code/context — receives code snapshots from editor extension
  - /api/code/interrupt — AI proactively interrupts with coding advice
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

_NO_RAG = {
    "time", "weather", "joke", "rap", "sing", "open", "launch",
    "search", "remind", "alarm", "calculate", "what time",
    "temperature", "forecast", "date", "timer", "screenshot", "volume", "mute",
    "explain this", "what does this do", "review my code", "debug",
}

def _needs_rag(text: str) -> bool:
    return not any(kw in text.lower() for kw in _NO_RAG)

def _is_creative(text: str) -> bool:
    return any(text.startswith(t) for t in ("[RAP_MODE", "[SING_MODE", "[JOKE_MODE"))


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)

    def broadcast_threadsafe(self, data: dict):
        """Schedule broadcast from any background thread."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(data), self._loop)


manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_event_loop()
    manager.set_loop(loop)

    v = settings.ELEVENLABS_VOICE_ID if settings.has_elevenlabs() else settings.EDGE_TTS_VOICE
    logger.info(f"🚀 Jarvis AI v5 | TTS:{settings.TTS_PROVIDER} ({v}) | LLM:{settings.LLM_MODEL}")

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
        on_interrupt=lambda msg: manager.broadcast_threadsafe({
            "type": "code_interrupt", "content": msg
        }),
        llm_client=orchestrator.llm_client,
        speech_processor=orchestrator.speech_processor,
        manager=manager,
    )
    orchestrator.code_watcher.start()

    # Wake word — thread-safe
    if settings.WAKE_WORD_ENABLED:
        try:
            from app.speech.wake_word import WakeWordListener

            def _on_wake():
                interrupt_handler.interrupt()
                manager.broadcast_threadsafe({
                    "type": "wake_detected", "content": "Listening…"
                })

            orchestrator.wake_listener = WakeWordListener(on_detected=_on_wake)
            orchestrator.wake_listener.start()
            logger.info("Wake word active")
        except Exception as e:
            logger.warning(f"Wake word skipped: {e}")

    yield

    logger.info("👋 Shutting down")
    for attr in ("wake_listener", "scheduler", "code_watcher"):
        if hasattr(orchestrator, attr):
            try:
                getattr(orchestrator, attr).stop()
            except Exception:
                pass


app = FastAPI(title="Jarvis AI", version="5.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

_ui_path = Path(__file__).parent.parent.parent / "ui"
_ui_path.mkdir(exist_ok=True)
app.mount("/ui", StaticFiles(directory=str(_ui_path), html=True), name="ui")


# ── Health ─────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "online", "version": "5.0.0", "ui": "http://localhost:8000/ui"}

@app.get("/health")
async def health():
    return {
        "llm": settings.LLM_MODEL, "tts": settings.TTS_PROVIDER,
        "voice_id": settings.ELEVENLABS_VOICE_ID, "edge_voice": settings.EDGE_TTS_VOICE,
        "elevenlabs_ok": settings.has_elevenlabs(), "groq_ok": settings.has_groq(),
        "location": settings.LOCATION_NAME,
    }


# ── Config ─────────────────────────────────────────────────────────
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
        "jarvis_persona", "wake_word_enabled", "code_watch_enabled", "code_watch_path",
    }
    applied = {}
    for key, val in body.items():
        if key.lower() not in allowed:
            continue
        attr = key.upper()
        try:
            cur = getattr(settings, attr, None)
            if isinstance(cur, bool):   val = str(val).lower() in ("true","1","yes")
            elif isinstance(cur, float): val = float(val)
            elif isinstance(cur, int):   val = int(val)
            object.__setattr__(settings, attr, val)
            applied[key] = val
        except Exception as e:
            logger.warning(f"Patch failed {key}: {e}")
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


# ── ElevenLabs ─────────────────────────────────────────────────────
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
    if not settings.has_elevenlabs():
        return {"error": "Not configured"}
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get("https://api.elevenlabs.io/v1/user",
                            headers={"xi-api-key": settings.ELEVENLABS_API_KEY})
        sub = r.json().get("subscription", {})
        used, lim = sub.get("character_count",0), sub.get("character_limit",10000)
        return {"used": used, "limit": lim, "remaining": lim-used, "tier": sub.get("tier","free")}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/edge/voices")
async def edge_voices():
    try:
        import edge_tts
        all_v = await edge_tts.list_voices()
        en = [{"name": v["ShortName"], "gender": v["Gender"],
               "locale": v["Locale"], "friendly": v["FriendlyName"]}
              for v in all_v if v["Locale"].startswith("en")]
        return {"voices": sorted(en, key=lambda x: x["locale"]), "current": settings.EDGE_TTS_VOICE}
    except Exception as e:
        return {"error": str(e)}


# ── Code watcher API ───────────────────────────────────────────────
@app.post("/api/code/context")
async def receive_code_context(body: dict):
    """
    Receives code snapshots from editor extensions or the file watcher.
    Body: { file: str, language: str, content: str, cursor_line: int }
    """
    if hasattr(orchestrator, "code_watcher"):
        await orchestrator.code_watcher.update_context(body)
    return {"status": "received"}

@app.post("/api/code/analyze")
async def analyze_code(body: dict):
    """Manually trigger a code analysis and get spoken + text feedback."""
    code    = body.get("code", "")
    lang    = body.get("language", "python")
    question = body.get("question", "Review this code and point out any issues or improvements.")
    if not code:
        return JSONResponse(status_code=400, content={"error": "code required"})

    prompt = (
        f"You are reviewing {lang} code. The developer is asking: '{question}'\n\n"
        f"```{lang}\n{code}\n```\n\n"
        "Give concise, actionable feedback. Speak naturally as if talking to the developer."
    )
    result = await orchestrator.llm_client.generate_response(
        messages=[{"role": "user", "content": prompt}]
    )
    response_text = result.get("content", "")

    # Synthesize and broadcast audio
    tts = await orchestrator.speech_processor.synthesize(response_text)
    if tts.get("audio_data"):
        manager.broadcast_threadsafe({
            "type": "code_feedback",
            "content": response_text,
            "audio_b64": base64.b64encode(tts["audio_data"]).decode(),
            "audio_format": tts.get("format", "mp3"),
        })

    return {"response": response_text}


# ── WebSocket ──────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    logger.info("WS connected")
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
                    await _handle_text(ws, txt, speak=data.get("tts", True))

            elif mtype == "audio":
                raw = data.get("audio_b64","")
                if raw:
                    await _handle_audio(ws, base64.b64decode(raw))

            elif mtype == "code_context":
                # UI sends active file context for passive watching
                if hasattr(orchestrator, "code_watcher"):
                    await orchestrator.code_watcher.update_context(data)

            elif mtype == "screen":
                result = await orchestrator.analyze_screen(data.get("prompt"))
                await ws.send_json({"type":"screen","content":result.get("analysis",""),
                                    "success":result.get("success")})

            elif mtype == "clear":
                orchestrator.clear_history()
                await ws.send_json({"type": "cleared"})

    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as e:
        logger.error(f"WS error: {e}", exc_info=True)
        manager.disconnect(ws)


# ── Text handler ───────────────────────────────────────────────────
async def _handle_text(ws: WebSocket, user_text: str, speak: bool = True):
    tool_result = await orchestrator.tool_manager.detect_and_execute(user_text)
    if tool_result and tool_result.get("success"):
        text = tool_result["result"]
        if not _is_creative(text):
            await ws.send_json({"type":"stream_end","content":text,"tool_used":tool_result["tool"]})
            if speak: await _speak_chunk(ws, text)
            _add_history(user_text, text)
            return
        user_text = text

    orchestrator.conversation_history.append(
        {"role":"user","content":user_text,"timestamp":datetime.now().isoformat()})
    orchestrator._trim_history()
    rag = await orchestrator.rag_engine.query(user_text) if _needs_rag(user_text) else None
    await ws.send_json({"type":"stream_start"})
    full = await _stream_and_speak(ws, rag, speak)
    await ws.send_json({"type":"stream_end","content":full})
    _add_history(None, full)


# ── Audio handler ──────────────────────────────────────────────────
async def _handle_audio(ws: WebSocket, audio_data: bytes):
    await ws.send_json({"type":"stt_start"})
    tr = await orchestrator.speech_processor.transcribe(audio_data)

    if not tr.get("success") or not tr.get("text","").strip():
        await ws.send_json({"type":"stt_error","content":"Could not understand"})
        return

    user_text = tr["text"].strip()
    await ws.send_json({"type":"transcript","content":user_text})
    logger.info(f"Voice → '{user_text}'")

    if any(w in user_text.lower() for w in {"stop","cancel","shut up","be quiet","silence"}):
        interrupt_handler.interrupt()
        await _speak_reply(ws, "Okay.", user_text, "interrupt")
        return

    # Code question detection
    code_keywords = {"code", "this function", "this file", "my code", "bug", "error",
                     "refactor", "explain this", "what does this", "how does this work",
                     "review", "debug", "fix this", "approach", "better way"}
    is_code_question = any(kw in user_text.lower() for kw in code_keywords)
    if is_code_question and hasattr(orchestrator, "code_watcher"):
        ctx = orchestrator.code_watcher.get_context_snippet()
        if ctx:
            user_text = f"{user_text}\n\n[Current code context]\n{ctx}"

    tool_result = await orchestrator.tool_manager.detect_and_execute(user_text)
    if tool_result and tool_result.get("success"):
        text = tool_result["result"]
        if not _is_creative(text):
            await _speak_reply(ws, text, user_text, tool_result["tool"])
            _add_history(user_text, text)
            return
        user_text = text

    orchestrator.conversation_history.append(
        {"role":"user","content":user_text,"timestamp":datetime.now().isoformat()})
    orchestrator._trim_history()
    rag = await orchestrator.rag_engine.query(user_text) if _needs_rag(user_text) else None
    await ws.send_json({"type":"stream_start"})
    full = await _stream_and_speak(ws, rag, speak=True)
    await ws.send_json({"type":"stream_end","content":full})
    await ws.send_json({"type":"audio_end","transcript":user_text,"content":full})
    _add_history(None, full)


# ── Shared stream + TTS ────────────────────────────────────────────
async def _stream_and_speak(ws: WebSocket, rag, speak: bool) -> str:
    full, buf = "", ""
    first_spoken = False
    tts_tasks: list[asyncio.Task] = []

    try:
        async for token in orchestrator.llm_client.stream_response(
                messages=orchestrator.conversation_history, rag_context=rag):
            if interrupt_handler.is_interrupted:
                await ws.send_json({"type":"stream_interrupted"})
                break
            full += token; buf += token
            await ws.send_json({"type":"stream_chunk","content":token})

            if speak and _ends_sentence(buf):
                s = buf.strip(); buf = ""
                if s:
                    if not first_spoken:
                        await _speak_chunk(ws, s); first_spoken = True
                    else:
                        tts_tasks.append(asyncio.create_task(_speak_chunk(ws, s)))
    except Exception as e:
        logger.error(f"LLM stream error: {e}")
        err = "I had trouble connecting. Please check your API key or try again."
        await ws.send_json({"type":"stream_chunk","content": err})
        full = err; buf = ""

    if speak and buf.strip():
        if not first_spoken: await _speak_chunk(ws, buf.strip())
        else: tts_tasks.append(asyncio.create_task(_speak_chunk(ws, buf.strip())))

    if tts_tasks:
        await asyncio.gather(*tts_tasks, return_exceptions=True)
    return full


async def _speak_chunk(ws: WebSocket, text: str):
    try:
        result = await orchestrator.speech_processor.synthesize(text)
        if result.get("success") and result.get("audio_data"):
            await ws.send_json({
                "type": "audio_chunk",
                "audio_b64": base64.b64encode(result["audio_data"]).decode(),
                "audio_format": result.get("format","mp3"),
                "text": text,
            })
    except Exception as e:
        logger.warning(f"TTS chunk: {e}")


async def _speak_reply(ws, text, transcript, tool_used):
    try:
        result = await orchestrator.speech_processor.synthesize(text)
        payload = {"type":"audio_end","transcript":transcript,"content":text,"tool_used":tool_used}
        if result.get("audio_data"):
            payload["audio_b64"]    = base64.b64encode(result["audio_data"]).decode()
            payload["audio_format"] = result.get("format","mp3")
        await ws.send_json(payload)
    except Exception as e:
        logger.warning(f"speak_reply: {e}")
        await ws.send_json({"type":"audio_end","transcript":transcript,"content":text,"tool_used":tool_used})


def _ends_sentence(text: str) -> bool:
    s = text.strip()
    return bool(s) and (s[-1] in '.!?…' or (s[-1] == ',' and len(s) > 80))

def _add_history(user: Optional[str], assistant: str):
    ts = datetime.now().isoformat()
    if user:
        orchestrator.conversation_history.append({"role":"user","content":user,"timestamp":ts})
    orchestrator.conversation_history.append({"role":"assistant","content":assistant,"timestamp":ts})


# ── REST ───────────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(request: dict):
    msg = request.get("message","")
    if not msg: return JSONResponse(status_code=400, content={"error":"message required"})
    result = await orchestrator.process_text_input(msg)
    return {"response": result.get("response"), "tool_used": result.get("tool_used")}

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

@app.post("/api/rag/query")
async def rag_query(request: dict):
    return await orchestrator.rag_engine.query(request.get("query",""))

@app.get("/api/history")
async def get_history():
    return {"history": orchestrator.get_history()}

@app.delete("/api/history")
async def clear_history():
    orchestrator.clear_history(); return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
