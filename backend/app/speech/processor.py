"""Explicit speech adapters with format detection and reusable local models.

Restart the maintained service after changing its private environment settings.
"""
import asyncio
import io
import logging
import os
import re
import tempfile
import threading

logger = logging.getLogger("jarvis.speech")


# ── Audio format detection ─────────────────────────────────────────

def _detect_audio_format(data: bytes) -> tuple[str, str]:
    if data[:4] == b'RIFF':             return ".wav",  "audio/wav"
    if data[:4] == b'fLaC':             return ".flac", "audio/flac"
    if data[:3] == b'ID3' or data[:2] == b'\xff\xfb':
                                         return ".mp3",  "audio/mpeg"
    if len(data) > 8 and data[4:8] == b'ftyp':
                                         return ".m4a",  "audio/mp4"
    if data[:4] == b'OggS':             return ".ogg",  "audio/ogg"
    return ".webm", "audio/webm"


# ── Sentence splitter ─────────────────────────────────────────────

_SENT_RE = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$')

def split_sentences(text: str) -> list[str]:
    parts = _SENT_RE.split(text.strip())
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) > 120:
            out.extend(s.strip() for s in re.split(r',\s+', p) if s.strip())
        else:
            out.append(p)
    return out or [text]


# ── Text cleaner ──────────────────────────────────────────────────

def clean_text(text: str) -> str:
    t = re.sub(r'[—–]', '-', text)
    t = re.sub(r'[\*\_\#\`]', '', t)
    t = re.sub(r'\[.*?\]\(.*?\)', '', t)   # strip markdown links
    return re.sub(r'\s+', ' ', t).strip() or text


class SpeechProcessor:

    def __init__(self):
        self._groq_client = None
        self._coqui_model = None
        self._whisper_model = None
        self._model_lock = threading.Lock()
        # Provider settings come from the configured service, rather than a
        # silent fallback. Expensive local models are reused within this client.
        from app.config import settings as s
        logger.info(f"SpeechProcessor ready | TTS: {s.TTS_PROVIDER} | "
                    f"EL voice: {s.ELEVENLABS_VOICE_ID if s.has_elevenlabs() else 'not configured'}")

    @property
    def _s(self):
        """Always return the live settings object (never cache)."""
        from app.config import settings
        return settings

    @property
    def groq_client(self):
        if self._groq_client is None:
            from groq import Groq
            self._groq_client = Groq(api_key=self._s.GROQ_API_KEY)
        return self._groq_client

    # ════════════════════════════════════════════════════════════════
    #  STT
    # ════════════════════════════════════════════════════════════════

    async def transcribe(self, audio_data: bytes, language: str = "en") -> dict:
        if not audio_data or len(audio_data) < 500:
            return {"success": False, "text": "", "error": "Audio too short"}

        ext, mime = _detect_audio_format(audio_data)
        logger.info(f"STT: {mime} {len(audio_data)/1024:.1f}KB")

        if self._s.STT_PROVIDER == 'groq' and self._s.has_groq():
            try:
                return await self._transcribe_groq(audio_data, ext, mime, language)
            except Exception as e:
                logger.warning(f"Groq STT failed ({e}) — local Whisper fallback")

        return await self._transcribe_local(audio_data, ext,language)

    async def _transcribe_groq(self, audio_data: bytes, ext: str, mime: str, language: str) -> dict:
        loop = asyncio.get_event_loop()
        transcription = await loop.run_in_executor(
            None,
            lambda: self.groq_client.audio.transcriptions.create(
                file=(f"audio{ext}", audio_data, mime),
                model=self._s.WHISPER_MODEL,
                language=language,
                response_format="text",
            )
        )
        text = (transcription if isinstance(transcription, str)
                else getattr(transcription, "text", str(transcription))).strip()
        logger.info(f"Groq STT → '{text[:80]}'")
        return {"success": True, "text": text, "provider": "groq_whisper"}

    async def _transcribe_local(self, audio_data: bytes, ext: str = ".webm",language: str = 'en') -> dict:
        tmp_path = None
        try:
            import whisper
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(audio_data); tmp_path = tmp.name
            loop = asyncio.get_event_loop()
            def transcribe():
                with self._model_lock:
                    if self._whisper_model is None:
                        self._whisper_model = whisper.load_model(self._s.LOCAL_WHISPER_MODEL)
                    return self._whisper_model.transcribe(tmp_path,language=None if language=='auto' else language)
            result = await loop.run_in_executor(None,transcribe)
            text = result["text"].strip()
            logger.info(f"Local Whisper → '{text[:80]}'")
            return {"success": True, "text": text, "provider": "local_whisper"}
        except Exception as e:
            logger.error(f"Local Whisper failed: {e}")
            return {"success": False, "text": "", "error": str(e)}
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ════════════════════════════════════════════════════════════════
    #  TTS — reads voice settings fresh every call
    # ════════════════════════════════════════════════════════════════

    async def synthesize(self, text: str, voice_speed: float = 1.0, emotion: str = "neutral") -> dict:
        """
        TTS priority: elevenlabs → edge → gtts
        Reads ELEVENLABS_VOICE_ID and all settings fresh every call —
        so changing voice in .env + /api/config/reload works immediately.
        """
        clean = clean_text(text)
        if not clean:
            return {"success": False, "error": "Empty text"}

        s = self._s  # live settings
        if s.TTS_PROVIDER == 'none':
            return {'success': False, 'error': 'Server speech is disabled. Configure an installed speech engine to enable it.'}

        try:
            if s.TTS_PROVIDER == 'elevenlabs':
                if not s.has_elevenlabs():
                    raise RuntimeError('The selected speech provider requires an API key.')
                return await self._elevenlabs(clean,s)
            if s.TTS_PROVIDER == 'edge':
                return await self._edge(clean,s)
            if s.TTS_PROVIDER == 'coqui':
                return await self._coqui(clean)
            if s.TTS_PROVIDER == 'gtts':
                return await self._gtts(clean)
            raise RuntimeError('Unknown speech provider')
        except Exception as e:
            return {'success':False,'error':'The selected speech engine is unavailable. Check its installation and configuration.','detail':type(e).__name__}

    # ── ElevenLabs ────────────────────────────────────────────────

    async def _elevenlabs(self, text: str, s) -> dict:
        """
        ElevenLabs TTS — best quality, free 10k chars/month.
        Voice ID is read from s (live settings) every call.
        """
        import httpx

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{s.ELEVENLABS_VOICE_ID}"
        payload = {
            "text": text,
            "model_id": s.ELEVENLABS_MODEL_ID,
            "voice_settings": {
                "stability":         s.ELEVENLABS_STABILITY,
                "similarity_boost":  s.ELEVENLABS_SIMILARITY,
                "style":             s.ELEVENLABS_STYLE,
                "use_speaker_boost": s.ELEVENLABS_SPEAKER_BOOST,
            },
            "output_format": "mp3_44100_128",
        }
        headers = {
            "xi-api-key":   s.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept":       "audio/mpeg",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            raise RuntimeError(f"ElevenLabs {resp.status_code}: {resp.text[:200]}")

        logger.info(f"ElevenLabs ({s.ELEVENLABS_VOICE_ID}) → {len(resp.content)/1024:.1f}KB")
        return {"success": True, "audio_data": resp.content, "provider": "elevenlabs", "format": "mp3"}

    # ── Edge TTS ──────────────────────────────────────────────────

    async def _edge(self, text: str, s) -> dict:
        import edge_tts
        communicate = edge_tts.Communicate(
            text, s.EDGE_TTS_VOICE,
            rate=s.EDGE_TTS_RATE, volume=s.EDGE_TTS_VOLUME, pitch=s.EDGE_TTS_PITCH,
        )
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        buf.seek(0)
        audio = buf.read()
        if not audio:
            raise RuntimeError("edge-tts empty response")
        logger.info(f"edge-tts ({s.EDGE_TTS_VOICE}) → {len(audio)/1024:.1f}KB")
        return {"success": True, "audio_data": audio, "provider": "edge_tts", "format": "mp3"}

    # ── Coqui ─────────────────────────────────────────────────────

    async def _coqui(self, text: str) -> dict:
        from TTS.api import TTS
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out = tmp.name
        def render():
            with self._model_lock:
                if self._coqui_model is None:
                    self._coqui_model = TTS(model_name="tts_models/en/ljspeech/tacotron2-DDC")
                self._coqui_model.tts_to_file(text=text,file_path=out)
            with open(out,'rb') as stream:
                return stream.read()
        try:
            audio = await asyncio.to_thread(render)
        finally:
            if os.path.exists(out):
                os.unlink(out)
        return {"success": True, "audio_data": audio, "provider": "coqui", "format": "wav"}

    # ── gTTS ──────────────────────────────────────────────────────

    async def _gtts(self, text: str) -> dict:
        from gtts import gTTS
        tts = gTTS(text=text, lang=getattr(self,'language','en'), slow=False)
        buf = io.BytesIO()
        await asyncio.to_thread(tts.write_to_fp,buf)
        buf.seek(0)
        return {"success": True, "audio_data": buf.read(), "provider": "gtts", "format": "mp3"}
