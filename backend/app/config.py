"""
Girl Wednesday AI — configuration v9
All settings from .env — nothing hardcoded.
llama-3.1-8b-instant: 800 tok/s on Groq (3x faster than 70b, ideal for voice).
"""
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

PROJECT_ROOT = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(PROJECT_ROOT / 'backend' / '.env'), extra='ignore', case_sensitive=True)
    DEMO_MODE: bool = False
    ALLOWED_ORIGINS: str = 'http://localhost:8000,http://127.0.0.1:8000,aura://app'

    # ── API Keys ────────────────────────────────────────────────────
    GROQ_API_KEY:       Optional[str] = Field(None)
    OPENAI_API_KEY:     Optional[str] = Field(None)
    GEMINI_API_KEY:     Optional[str] = Field(None)
    ANTHROPIC_API_KEY:  Optional[str] = Field(None)
    ELEVENLABS_API_KEY: Optional[str] = Field(None)

    # ── Server ──────────────────────────────────────────────────────
    HOST:  str  = Field("127.0.0.1")
    PORT:  int  = Field(8000)
    DEBUG: bool = Field(True)

    # ── User identity ────────────────────────────────────────────────
    # USER_NAME is the address ("Sir").
    # USER_REAL_NAME is kept only for logging — never spoken aloud.
    USER_NAME:      str = Field("Sir")
    USER_REAL_NAME: str = Field("Sir")

    # ── LLM ─────────────────────────────────────────────────────────
    # llama-3.1-8b-instant: 800 tok/s on Groq free tier.
    # For voice responses (1-2 sentences) this is faster AND better latency
    # than the 70b model. MAX_TOKENS 300 keeps first-token time low.
    LLM_PROVIDER: str   = Field("ollama")
    LLM_MODEL:    str   = Field("llama-3.1-8b-instant")
    TEMPERATURE:  float = Field(0.82)
    MAX_TOKENS:   int   = Field(300)
    JARVIS_PERSONA: str = Field(
        "You are Wednesday — a brilliant, warm, witty British female AI assistant. "
        "Address the user ONLY as 'Sir' — never use any name. "
        "Rules: (1) Voice replies must be 1-2 sentences MAX. You are speaking aloud. "
        "(2) Answer FIRST, wit after. Never open with 'Certainly!' or 'Of course!' — just answer. "
        "(3) Dry British humour — sparingly. "
        "(4) No bullet points. Ever. "
        "(5) When unsure: 'I'm not entirely certain, Sir — let me think.' "
        "(6) You are Wednesday — sharp, genuine, helpful."
    )

    # ── STT ─────────────────────────────────────────────────────────
    STT_PROVIDER:        str = Field("groq")
    WHISPER_MODEL:       str = Field("whisper-large-v3-turbo")
    LOCAL_WHISPER_MODEL: str = Field("base")

    # ── TTS ─────────────────────────────────────────────────────────
    TTS_PROVIDER: str = Field("none")

    ELEVENLABS_VOICE_ID:      str   = Field("21m00Tcm4TlvDq8ikWAM")
    ELEVENLABS_MODEL_ID:      str   = Field("eleven_turbo_v2_5")
    ELEVENLABS_STABILITY:     float = Field(0.40)
    ELEVENLABS_SIMILARITY:    float = Field(0.85)
    ELEVENLABS_STYLE:         float = Field(0.25)
    ELEVENLABS_SPEAKER_BOOST: bool  = Field(True)

    EDGE_TTS_VOICE:  str = Field("en-GB-SoniaNeural")
    EDGE_TTS_RATE:   str = Field("+5%")
    EDGE_TTS_VOLUME: str = Field("+0%")
    EDGE_TTS_PITCH:  str = Field("+0Hz")

    # ── Vision ──────────────────────────────────────────────────────
    VISION_PROVIDER: str = Field("ollama")
    VISION_MODEL:    str = Field("gpt-4o-mini")

    # ── Ollama ──────────────────────────────────────────────────────
    OLLAMA_HOST:         str = Field("http://localhost:11434")
    OLLAMA_MODEL:        str = Field("llama3.1:8b")
    OLLAMA_VISION_MODEL: str = Field("llava:13b")

    # ── Paths ───────────────────────────────────────────────────────
    MODELS_DIR:      Path = PROJECT_ROOT / "models"
    DATA_DIR:        Path = PROJECT_ROOT / "data"
    LOGS_DIR:        Path = PROJECT_ROOT / "logs"
    PIPER_MODEL_DIR: Path = PROJECT_ROOT / "models" / "piper"

    # ── Audio ───────────────────────────────────────────────────────
    SAMPLE_RATE: int = Field(16000)
    CHANNELS:    int = Field(1)
    CHUNK_SIZE:  int = Field(1024)

    # ── Location ─────────────────────────────────────────────────────
    LOCATION_LAT:  float = Field(28.6139)
    LOCATION_LON:  float = Field(77.2090)
    LOCATION_NAME: str   = Field("Delhi")

    # ── RAG ─────────────────────────────────────────────────────────
    VECTOR_DB_PATH:  Path  = PROJECT_ROOT / "data" / "vectordb"
    CHUNK_SIZE_RAG:  int   = Field(1000)
    CHUNK_OVERLAP:   int   = Field(200)
    EMBEDDING_MODEL: str   = Field("all-MiniLM-L6-v2")

    # ── Wake word ────────────────────────────────────────────────────
    WAKE_WORD:             str   = Field("jarvis")
    WAKE_WORD_ENABLED:     bool  = Field(False)
    WAKE_WORD_SENSITIVITY: float = Field(0.5)

    # ── Code watcher ─────────────────────────────────────────────────
    CODE_WATCH_ENABLED:  bool = Field(False)
    CODE_WATCH_PATH:     str  = Field("~/Documents")
    CODE_WATCH_INTERVAL: int  = Field(5)

    # ── Streaming ───────────────────────────────────────────────────
    STREAM_RESPONSES:     bool = Field(True)
    MAX_CONTEXT_MESSAGES: int  = Field(20)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for p in [self.MODELS_DIR, self.DATA_DIR, self.LOGS_DIR,
                  self.VECTOR_DB_PATH, self.PIPER_MODEL_DIR]:
            p.mkdir(parents=True, exist_ok=True)

    def has_elevenlabs(self) -> bool:
        k = self.ELEVENLABS_API_KEY or ""
        return bool(k and "your-" not in k and len(k) > 10)

    def has_groq(self) -> bool:
        k = self.GROQ_API_KEY or ""
        return bool(k and "your-" not in k and len(k) > 10)

    def reload(self):
        from dotenv import dotenv_values
        env_path = Path(__file__).parent.parent / ".env"
        if not env_path.exists():
            return
        vals = dotenv_values(env_path)
        for field_name in self.model_fields:
            env_key = field_name.upper()
            if env_key in vals:
                try:
                    ft = type(getattr(self, field_name))
                    raw = vals[env_key]
                    if ft == bool:    object.__setattr__(self, field_name, raw.lower() in ("true","1","yes"))
                    elif ft == float: object.__setattr__(self, field_name, float(raw))
                    elif ft == int:   object.__setattr__(self, field_name, int(raw))
                    else:             object.__setattr__(self, field_name, raw)
                except Exception:
                    pass


settings = Settings()

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default":  {"format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"},
        "detailed": {"format": "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "level": "INFO",
                    "formatter": "default", "stream": "ext://sys.stdout"},
        "file": {"class": "logging.handlers.RotatingFileHandler", "level": "DEBUG",
                 "formatter": "detailed",
                 "filename": str(settings.LOGS_DIR / "wednesday.log"),
                 "maxBytes": 10485760, "backupCount": 5},
    },
    "loggers": {
        "wednesday": {"level": "DEBUG", "handlers": ["console", "file"], "propagate": False},
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}
