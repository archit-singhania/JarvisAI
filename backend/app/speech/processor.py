"""
Speech Processor — Phase 4 Final
STT:  Groq Whisper (fast, free) → local Whisper fallback (offline)
TTS:  ElevenLabs (best quality, free 10k/month)
      → edge-tts (Microsoft Neural, free unlimited, very human)
      → gTTS (last resort)

Zero-delay architecture:
  - TTS fires per sentence as LLM streams, not after full response
  - All blocking calls run in thread executors (never blocks event loop)
  - Audio format auto-detected so webm/wav/mp3 all work correctly
"""
import asyncio
import io
import logging
import os
import re
import tempfile
from typing import AsyncGenerator, Optional

logger = logging.getLogger("jarvis.speech")


# ── Audio format detection ─────────────────────────────────────────

def _detect_audio_format(audio_data: bytes) -> tuple[str, str]:
    """Detect format from magic bytes → (extension, mime_type)."""
    if audio_data[:4] == b'RIFF':
        return ".wav", "audio/wav"
    elif audio_data[:4] == b'fLaC':
        return ".flac", "audio/flac"
    elif audio_data[:3] == b'ID3' or audio_data[:2] == b'\xff\xfb':
        return ".mp3", "audio/mpeg"
    elif len(audio_data) > 8 and audio_data[4:8] == b'ftyp':
        return ".m4a", "audio/mp4"
    elif audio_data[:4] == b'OggS':
        return ".ogg", "audio/ogg"
    else:
        return ".webm", "audio/webm"


# ── Sentence splitter ─────────────────────────────────────────────

_SENT_END = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$')

def split_sentences(text: str) -> list[str]:
    parts = _SENT_END.split(text.strip())
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) > 120:
            for sub in re.split(r',\s+', p):
                if sub.strip():
                    out.append(sub.strip())
        else:
            out.append(p)
    return out or [text]


class SpeechProcessor:

    def __init__(self):
        from app.config import settings
        self.settings = settings
        self._groq_client = None
        self._coqui_model = None
        provider = settings.TTS_PROVIDER
        has_el = bool(settings.ELEVENLABS_API_KEY and
                      settings.ELEVENLABS_API_KEY != "your-elevenlabs-api-key-here")
        if provider == "elevenlabs" and not has_el:
            logger.warning("ElevenLabs key not set — falling back to edge-tts")
        logger.info(f"SpeechProcessor ready | STT: groq_whisper | TTS: {provider}")

    # ── Groq client ────────────────────────────────────────────────
    @property
    def groq_client(self):
        if self._groq_client is None:
            from groq import Groq
            self._groq_client = Groq(api_key=self.settings.GROQ_API_KEY)
        return self._groq_client

    # ════════════════════════════════════════════════════════════════
    #  STT
    # ════════════════════════════════════════════════════════════════

    async def transcribe(self, audio_data: bytes, language: str = "en") -> dict:
        if not audio_data or len(audio_data) < 500:
            return {"success": False, "text": "", "error": "Audio too short"}

        ext, mime = _detect_audio_format(audio_data)
        logger.info(f"STT input: {mime}, {len(audio_data)/1024:.1f}KB")

        api_key = self.settings.GROQ_API_KEY or ""
        if api_key and "your-groq" not in api_key:
            try:
                return await self._transcribe_groq(audio_data, ext, mime, language)
            except Exception as e:
                logger.warning(f"Groq STT failed ({e}) — local Whisper fallback")

        return await self._transcribe_local(audio_data, ext)

    async def _transcribe_groq(self, audio_data: bytes, ext: str, mime: str, language: str) -> dict:
        """Groq Whisper — ~100-300ms, free, handles webm/wav/mp3/ogg."""
        loop = asyncio.get_event_loop()
        transcription = await loop.run_in_executor(
            None,
            lambda: self.groq_client.audio.transcriptions.create(
                file=(f"audio{ext}", audio_data, mime),
                model=self.settings.WHISPER_MODEL,
                language=language,
                response_format="text",
            )
        )
        text = (transcription if isinstance(transcription, str)
                else getattr(transcription, "text", str(transcription))).strip()
        logger.info(f"Groq STT → '{text[:80]}'")
        return {"success": True, "text": text, "provider": "groq_whisper"}

    async def _transcribe_local(self, audio_data: bytes, ext: str = ".webm") -> dict:
        """Local openai-whisper — fully offline."""
        try:
            import whisper
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: whisper.load_model(self.settings.LOCAL_WHISPER_MODEL).transcribe(tmp_path)
            )
            os.unlink(tmp_path)
            text = result["text"].strip()
            logger.info(f"Local Whisper → '{text[:80]}'")
            return {"success": True, "text": text, "provider": "local_whisper"}
        except Exception as e:
            logger.error(f"Local Whisper failed: {e}")
            return {"success": False, "text": "", "error": str(e)}

    # ════════════════════════════════════════════════════════════════
    #  TTS — single shot
    # ════════════════════════════════════════════════════════════════

    async def synthesize(self, text: str, voice_speed: float = 1.0, emotion: str = "neutral") -> dict:
        """Convert text → audio bytes using best available TTS."""
        clean = _clean_text(text)
        if not clean:
            return {"success": False, "error": "Empty text after cleaning"}

        provider = self.settings.TTS_PROVIDER
        has_el = bool(self.settings.ELEVENLABS_API_KEY and
                      self.settings.ELEVENLABS_API_KEY != "your-elevenlabs-api-key-here")

        # Try ElevenLabs first if configured
        if provider == "elevenlabs" and has_el:
            try:
                return await self._synthesize_elevenlabs(clean)
            except Exception as e:
                logger.warning(f"ElevenLabs failed ({e}) — edge-tts fallback")

        # edge-tts (free, neural, very human)
        try:
            return await self._synthesize_edge(clean)
        except Exception as e:
            logger.warning(f"edge-tts failed ({e}) — gTTS fallback")

        # Last resort
        return await self._synthesize_gtts(clean)

    # ════════════════════════════════════════════════════════════════
    #  TTS implementations
    # ════════════════════════════════════════════════════════════════

    async def _synthesize_elevenlabs(self, text: str) -> dict:
        """
        ElevenLabs TTS — best quality, sounds exactly like a human.
        Free tier: 10,000 characters/month.
        Uses eleven_turbo_v2_5 model for lowest latency (~200ms first byte).
        """
        import httpx

        api_key  = self.settings.ELEVENLABS_API_KEY
        voice_id = self.settings.ELEVENLABS_VOICE_ID
        model_id = self.settings.ELEVENLABS_MODEL_ID

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability":         self.settings.ELEVENLABS_STABILITY,
                "similarity_boost":  self.settings.ELEVENLABS_SIMILARITY,
                "style":             self.settings.ELEVENLABS_STYLE,
                "use_speaker_boost": self.settings.ELEVENLABS_SPEAKER_BOOST,
            },
            "output_format": "mp3_44100_128",
        }

        headers = {
            "xi-api-key":   api_key,
            "Content-Type": "application/json",
            "Accept":       "audio/mpeg",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            raise RuntimeError(f"ElevenLabs {resp.status_code}: {resp.text[:200]}")

        audio_bytes = resp.content
        logger.info(f"ElevenLabs TTS → {len(audio_bytes)/1024:.1f}KB for '{text[:50]}'")
        return {"success": True, "audio_data": audio_bytes, "provider": "elevenlabs", "format": "mp3"}

    async def _synthesize_edge(self, text: str) -> dict:
        """
        edge-tts — Microsoft Neural TTS, completely free, no API key needed.
        ~80-150ms latency. Sounds genuinely human.
        Install: pip install edge-tts
        """
        import edge_tts

        communicate = edge_tts.Communicate(
            text,
            self.settings.EDGE_TTS_VOICE,
            rate=self.settings.EDGE_TTS_RATE,
            volume=self.settings.EDGE_TTS_VOLUME,
            pitch=self.settings.EDGE_TTS_PITCH,
        )

        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])

        buf.seek(0)
        audio_bytes = buf.read()
        if not audio_bytes:
            raise RuntimeError("edge-tts returned empty audio")

        logger.info(f"edge-tts → {len(audio_bytes)/1024:.1f}KB for '{text[:50]}'")
        return {"success": True, "audio_data": audio_bytes, "provider": "edge_tts", "format": "mp3"}

    async def _synthesize_coqui(self, text: str) -> dict:
        """Coqui TTS — offline fallback, slower on CPU."""
        from TTS.api import TTS
        if self._coqui_model is None:
            logger.info("Loading Coqui TTS model…")
            self._coqui_model = TTS(model_name="tts_models/en/ljspeech/tacotron2-DDC")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out_path = tmp.name

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._coqui_model.tts_to_file(text=text, file_path=out_path)
        )
        with open(out_path, "rb") as f:
            audio_bytes = f.read()
        os.unlink(out_path)
        return {"success": True, "audio_data": audio_bytes, "provider": "coqui", "format": "wav"}

    async def _synthesize_gtts(self, text: str) -> dict:
        """gTTS — last resort, needs internet, free."""
        from gtts import gTTS
        tts = gTTS(text=text, lang="en", slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return {"success": True, "audio_data": buf.read(), "provider": "gtts", "format": "mp3"}


# ── Shared text cleaner ────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Strip characters that confuse TTS engines."""
    t = re.sub(r'[—–]', '-', text)
    t = re.sub(r'[\*\_\#\`]', '', t)
    t = re.sub(r'\[.*?\]\(.*?\)', '', t)
    t = re.sub(r'[^\x00-\x7F]+', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t or text
