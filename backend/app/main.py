"""
Jarvis AI — FastAPI main  |  Phase 4 Final
Pipeline: STT → tools → smart-RAG → stream-LLM → per-sentence TTS → audio chunks
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

# ── RAG skip list — tool queries don't need vector search ──────────
_NO_RAG = {
    "time", "weather", "joke", "rap", "sing", "open", "launch",
    "search", "remind", "alarm", "calculate", "what time", "temperature",
    "forecast", "date", "timer",
}

def _needs_rag(text: str) -> bool:
    lower = text.lower()
    return not any(kw in lower for kw in _NO_RAG)


# ── Connection manager ─────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

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


manager = ConnectionManager()


# ── Lifespan ───────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    tts = settings.TTS_PROVIDER
    voice = (settings.ELEVENLABS_VOICE_ID if tts == "elevenlabs"
             else settings.EDGE_TTS_VOICE)
    logger.info(f"🚀 Jarvis AI v4 | TTS: {tts} ({voice}) | LLM: {settings.LLM_MODEL}")

    db_path = Path(settings.DATA_DIR) / "reminders.db"
    from app.tools.scheduler import ReminderScheduler

    def _on_reminder(text: str):
        asyncio.create_task(manager.broadcast({"type": "reminder", "content": text}))

    orchestrator.scheduler = ReminderScheduler(db_path, _on_reminder)
    await orchestrator.scheduler.start()

    if settings.WAKE_WORD_ENABLED:
        try:
            from app.speech.wake_word import WakeWordListener

            def _on_wake():
                interrupt_handler.interrupt()
                asyncio.create_task(manager.broadcast({
                    "type": "wake_detected",
                    "content": "Wake word detected — listening…"
                }))

            orchestrator.wake_listener = WakeWordListener(on_detected=_on_wake)
            orchestrator.wake_listener.start()
            logger.info("Wake word active")
        except Exception as e:
            logger.warning(f"Wake word skipped: {e}")

    yield

    logger.info("👋 Shutting down")
    if hasattr(orchestrator, "wake_listener"):
        orchestrator.wake_listener.stop()
    if hasattr(orchestrator, "scheduler"):
        orchestrator.scheduler.stop()


# ── App ─────────────────────────────────────────────────────────────
app = FastAPI(title="Jarvis AI", version="4.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

_ui_path = Path(__file__).parent.parent.parent / "ui"
_ui_path.mkdir(exist_ok=True)
app.mount("/ui", StaticFiles(directory=str(_ui_path), html=True), name="ui")


# ── Health ──────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "online", "version": "4.0.0",
            "tts": settings.TTS_PROVIDER, "ui": "http://localhost:8000/ui"}

@app.get("/health")
async def health():
    return {"llm": settings.LLM_MODEL, "tts": settings.TTS_PROVIDER,
            "voice": settings.ELEVENLABS_VOICE_ID if settings.TTS_PROVIDER == "elevenlabs"
                     else settings.EDGE_TTS_VOICE}


# ── WebSocket ────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    logger.info("WS connected")
    try:
        while True:
            data = await ws.receive_json()
            mtype = data.get("type")

            if mtype == "interrupt":
                interrupt_handler.interrupt()
                await ws.send_json({"type": "interrupted"})
                continue

            interrupt_handler.reset()

            if mtype == "text":
                txt = data.get("content", "").strip()
                if txt:
                    speak = data.get("tts", False)
                    await _handle_text(ws, txt, speak=speak)

            elif mtype == "audio":
                raw = data.get("audio_b64", "")
                if raw:
                    await _handle_audio(ws, base64.b64decode(raw))

            elif mtype == "screen":
                result = await orchestrator.analyze_screen(data.get("prompt"))
                await ws.send_json({"type": "screen",
                                    "content": result.get("analysis", ""),
                                    "success": result.get("success")})

            elif mtype == "clear":
                orchestrator.clear_history()
                await ws.send_json({"type": "cleared"})

            else:
                await ws.send_json({"type": "error", "content": f"Unknown: {mtype}"})

    except WebSocketDisconnect:
        manager.disconnect(ws)
        logger.info("WS disconnected")
    except Exception as e:
        logger.error(f"WS error: {e}", exc_info=True)
        manager.disconnect(ws)


# ── Text handler ───────────────────────────────────────────────────

async def _handle_text(ws: WebSocket, user_text: str, speak: bool = False):
    """Stream LLM response with optional per-sentence TTS."""

    # Tools first — instant, no LLM
    tool_result = await orchestrator.tool_manager.detect_and_execute(user_text)
    if tool_result and tool_result.get("success"):
        text = tool_result["result"]
        is_creative = text.startswith("[RAP_MODE") or text.startswith("[SING_MODE")
        if not is_creative:
            await ws.send_json({"type": "stream_end", "content": text,
                                "tool_used": tool_result["tool"]})
            _add_history(user_text, text)
            return
        user_text = text

    # History
    orchestrator.conversation_history.append(
        {"role": "user", "content": user_text, "timestamp": datetime.now().isoformat()}
    )
    orchestrator._trim_history()

    # RAG (smart skip)
    rag = await orchestrator.rag_engine.query(user_text) if _needs_rag(user_text) else None

    await ws.send_json({"type": "stream_start"})

    full, buf = "", ""
    tts_queue: list[asyncio.Task] = []

    async for token in orchestrator.llm_client.stream_response(
            messages=orchestrator.conversation_history, rag_context=rag):

        if interrupt_handler.is_interrupted:
            await ws.send_json({"type": "stream_interrupted"})
            break

        full += token
        buf  += token
        await ws.send_json({"type": "stream_chunk", "content": token})

        if speak and _ends_sentence(buf):
            s = buf.strip(); buf = ""
            if s:
                tts_queue.append(asyncio.create_task(_speak(ws, s)))

    # Flush
    if speak and buf.strip():
        tts_queue.append(asyncio.create_task(_speak(ws, buf.strip())))

    await ws.send_json({"type": "stream_end", "content": full})
    if tts_queue:
        await asyncio.gather(*tts_queue, return_exceptions=True)

    _add_history(None, full)


# ── Audio (voice) handler ──────────────────────────────────────────

async def _handle_audio(ws: WebSocket, audio_data: bytes):
    """Full voice pipeline: STT → tools → LLM stream → sentence TTS."""

    await ws.send_json({"type": "stt_start"})
    tr = await orchestrator.speech_processor.transcribe(audio_data)

    if not tr.get("success") or not tr.get("text", "").strip():
        await ws.send_json({"type": "stt_error", "content": "Could not understand"})
        return

    user_text = tr["text"].strip()
    await ws.send_json({"type": "transcript", "content": user_text})
    logger.info(f"Voice → '{user_text}'")

    # Interrupt words
    if any(w in user_text.lower() for w in {"stop", "cancel", "shut up", "be quiet"}):
        interrupt_handler.interrupt()
        await _speak_and_signal(ws, "Okay, stopping.", user_text, "interrupt")
        return

    # Tools
    tool_result = await orchestrator.tool_manager.detect_and_execute(user_text)
    if tool_result and tool_result.get("success"):
        text = tool_result["result"]
        is_creative = text.startswith("[RAP_MODE") or text.startswith("[SING_MODE")
        if not is_creative:
            await _speak_and_signal(ws, text, user_text, tool_result["tool"])
            _add_history(user_text, text)
            return
        user_text = text

    # History + RAG
    orchestrator.conversation_history.append(
        {"role": "user", "content": user_text, "timestamp": datetime.now().isoformat()}
    )
    orchestrator._trim_history()
    rag = await orchestrator.rag_engine.query(user_text) if _needs_rag(user_text) else None

    await ws.send_json({"type": "stream_start"})

    full, buf = "", ""
    first_spoken = False
    tts_queue: list[asyncio.Task] = []

    async for token in orchestrator.llm_client.stream_response(
            messages=orchestrator.conversation_history, rag_context=rag):

        if interrupt_handler.is_interrupted:
            await ws.send_json({"type": "stream_interrupted"})
            break

        full += token
        buf  += token
        await ws.send_json({"type": "stream_chunk", "content": token})

        if _ends_sentence(buf):
            s = buf.strip(); buf = ""
            if s:
                if not first_spoken:
                    # Await first sentence directly → minimum perceived latency
                    await _speak(ws, s)
                    first_spoken = True
                else:
                    tts_queue.append(asyncio.create_task(_speak(ws, s)))

    # Flush remaining
    if buf.strip():
        if not first_spoken:
            await _speak(ws, buf.strip())
        else:
            tts_queue.append(asyncio.create_task(_speak(ws, buf.strip())))

    await ws.send_json({"type": "stream_end", "content": full})
    if tts_queue:
        await asyncio.gather(*tts_queue, return_exceptions=True)

    await ws.send_json({"type": "audio_end",
                        "transcript": user_text, "content": full})
    _add_history(None, full)


# ── TTS helpers ────────────────────────────────────────────────────

async def _speak(ws: WebSocket, text: str):
    """Synthesize one sentence and push audio_chunk to client."""
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
        logger.warning(f"TTS chunk error: {e}")


async def _speak_and_signal(ws: WebSocket, text: str,
                             transcript: str, tool_used: Optional[str]):
    """Synthesize full response and send as audio_end."""
    try:
        result = await orchestrator.speech_processor.synthesize(text)
        payload = {"type": "audio_end", "transcript": transcript,
                   "content": text, "tool_used": tool_used}
        if result.get("audio_data"):
            payload["audio_b64"]    = base64.b64encode(result["audio_data"]).decode()
            payload["audio_format"] = result.get("format", "mp3")
        await ws.send_json(payload)
    except Exception as e:
        logger.warning(f"speak_and_signal error: {e}")
        await ws.send_json({"type": "audio_end", "transcript": transcript,
                            "content": text, "tool_used": tool_used})


def _ends_sentence(text: str) -> bool:
    s = text.strip()
    return bool(s) and (
        s[-1] in '.!?…'
        or (s[-1] == ',' and len(s) > 80)
    )


def _add_history(user: Optional[str], assistant: str):
    ts = datetime.now().isoformat()
    if user:
        orchestrator.conversation_history.append(
            {"role": "user", "content": user, "timestamp": ts})
    orchestrator.conversation_history.append(
        {"role": "assistant", "content": assistant, "timestamp": ts})


# ── REST ────────────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(request: dict):
    msg = request.get("message", "")
    if not msg:
        return JSONResponse(status_code=400, content={"error": "message required"})
    result = await orchestrator.process_text_input(msg)
    return {"response": result.get("response"), "tool_used": result.get("tool_used")}


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


@app.get("/api/voices")
async def list_voices():
    try:
        import edge_tts
        voices = await edge_tts.list_voices()
        return {"voices": [v for v in voices if v["Locale"].startswith("en")]}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/rag/add")
async def rag_add(request: dict):
    meta = request.get("metadata") or {"source": "user"}
    ok = await orchestrator.rag_engine.add_document(
        request.get("text", ""),
        request.get("doc_id", f"doc_{__import__('time').time()}"),
        meta,
    )
    return {"success": ok}


@app.post("/api/rag/query")
async def rag_query(request: dict):
    return await orchestrator.rag_engine.query(request.get("query", ""))


@app.get("/api/history")
async def get_history():
    return {"history": orchestrator.get_history()}


@app.delete("/api/history")
async def clear_history():
    orchestrator.clear_history()
    return {"success": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST,
                port=settings.PORT, reload=settings.DEBUG)
