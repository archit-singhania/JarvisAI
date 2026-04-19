"""
Speech Processor — reads settings live on every call, no caching of voice IDs.
This means changing ELEVENLABS_VOICE_ID in .env + calling /api/config/reload
takes effect immediately without a server restart.
"""
import asyncio
import io
import logging
import os
import re
import tempfile

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
    t = re.sub(r'[^\x00-\x7F]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip() or text


class SpeechProcessor:

    def __init__(self):
        self._groq_client = None
        self._coqui_model = None
        # NOTE: we do NOT cache settings fields here — always read from settings at call time
        # so that /api/config/reload takes effect without restart
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

        if self._s.has_groq():
            try:
                return await self._transcribe_groq(audio_data, ext, mime, language)
            except Exception as e:
                logger.warning(f"Groq STT failed ({e}) — local Whisper fallback")

        return await self._transcribe_local(audio_data, ext)

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

    async def _transcribe_local(self, audio_data: bytes, ext: str = ".webm") -> dict:
        try:
            import whisper
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(audio_data); tmp_path = tmp.name
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: whisper.load_model(self._s.LOCAL_WHISPER_MODEL).transcribe(tmp_path)
            )
            os.unlink(tmp_path)
            text = result["text"].strip()
            logger.info(f"Local Whisper → '{text[:80]}'")
            return {"success": True, "text": text, "provider": "local_whisper"}
        except Exception as e:
            logger.error(f"Local Whisper failed: {e}")
            return {"success": False, "text": "", "error": str(e)}

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

        if s.TTS_PROVIDER == "elevenlabs" and s.has_elevenlabs():
            try:
                return await self._elevenlabs(clean, s)
            except Exception as e:
                logger.warning(f"ElevenLabs failed ({e}) — edge-tts fallback")

        try:
            return await self._edge(clean, s)
        except Exception as e:
            logger.warning(f"edge-tts failed ({e}) — gTTS fallback")

        return await self._gtts(clean)

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
        if self._coqui_model is None:
            self._coqui_model = TTS(model_name="tts_models/en/ljspeech/tacotron2-DDC")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out = tmp.name
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._coqui_model.tts_to_file(text=text, file_path=out))
        with open(out, "rb") as f:
            audio = f.read()
        os.unlink(out)
        return {"success": True, "audio_data": audio, "provider": "coqui", "format": "wav"}

    # ── gTTS ──────────────────────────────────────────────────────

    async def _gtts(self, text: str) -> dict:
        from gtts import gTTS
        tts = gTTS(text=text, lang="en", slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return {"success": True, "audio_data": buf.read(), "provider": "gtts", "format": "mp3"}
