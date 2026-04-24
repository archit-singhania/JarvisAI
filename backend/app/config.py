"""
Girl Wednesday AI — configuration v8
All settings from .env — nothing hardcoded.
"""
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field

PROJECT_ROOT = Path(__file__).parent.parent.parent


class Settings(BaseSettings):

    # ── API Keys ────────────────────────────────────────────────────
    GROQ_API_KEY:       Optional[str] = Field(None, env="GROQ_API_KEY")
    OPENAI_API_KEY:     Optional[str] = Field(None, env="OPENAI_API_KEY")
    GEMINI_API_KEY:     Optional[str] = Field(None, env="GEMINI_API_KEY")
    ANTHROPIC_API_KEY:  Optional[str] = Field(None, env="ANTHROPIC_API_KEY")
    ELEVENLABS_API_KEY: Optional[str] = Field(None, env="ELEVENLABS_API_KEY")

    # ── Server ──────────────────────────────────────────────────────
    HOST:  str  = Field("0.0.0.0", env="HOST")
    PORT:  int  = Field(8000,      env="PORT")
    DEBUG: bool = Field(True,      env="DEBUG")

    # ── User identity ────────────────────────────────────────────────
    USER_NAME:      str = Field("Sir",    env="USER_NAME")
    USER_REAL_NAME: str = Field("Archit", env="USER_REAL_NAME")

    # ── LLM ─────────────────────────────────────────────────────────
    LLM_PROVIDER:   str   = Field("groq",                    env="LLM_PROVIDER")
    LLM_MODEL:      str   = Field("llama-3.3-70b-versatile", env="LLM_MODEL")
    TEMPERATURE:    float = Field(0.85, env="TEMPERATURE")
    MAX_TOKENS:     int   = Field(800,  env="MAX_TOKENS")
    JARVIS_PERSONA: str   = Field(
        "You are Wednesday — a brilliant, warm, witty British female AI assistant. "
        "You address the user as 'Sir' naturally. Keep voice responses to 1-2 sentences max. "
        "Be genuine, curious, and genuinely helpful.",
        env="JARVIS_PERSONA"
    )

    # ── STT ─────────────────────────────────────────────────────────
    STT_PROVIDER:        str = Field("groq",                   env="STT_PROVIDER")
    WHISPER_MODEL:       str = Field("whisper-large-v3-turbo", env="WHISPER_MODEL")
    LOCAL_WHISPER_MODEL: str = Field("base",                   env="LOCAL_WHISPER_MODEL")

    # ── TTS ─────────────────────────────────────────────────────────
    TTS_PROVIDER: str = Field("elevenlabs", env="TTS_PROVIDER")

    # ElevenLabs — Rachel (21m00Tcm4TlvDq8ikWAM) works on free tier
    ELEVENLABS_VOICE_ID:      str   = Field("21m00Tcm4TlvDq8ikWAM", env="ELEVENLABS_VOICE_ID")
    ELEVENLABS_MODEL_ID:      str   = Field("eleven_turbo_v2_5",    env="ELEVENLABS_MODEL_ID")
    ELEVENLABS_STABILITY:     float = Field(0.40, env="ELEVENLABS_STABILITY")
    ELEVENLABS_SIMILARITY:    float = Field(0.85, env="ELEVENLABS_SIMILARITY")
    ELEVENLABS_STYLE:         float = Field(0.25, env="ELEVENLABS_STYLE")
    ELEVENLABS_SPEAKER_BOOST: bool  = Field(True, env="ELEVENLABS_SPEAKER_BOOST")

    # Edge TTS — British female fallback
    EDGE_TTS_VOICE:  str = Field("en-GB-SoniaNeural", env="EDGE_TTS_VOICE")
    EDGE_TTS_RATE:   str = Field("+5%",  env="EDGE_TTS_RATE")
    EDGE_TTS_VOLUME: str = Field("+0%",  env="EDGE_TTS_VOLUME")
    EDGE_TTS_PITCH:  str = Field("+0Hz", env="EDGE_TTS_PITCH")

    # ── Vision ──────────────────────────────────────────────────────
    VISION_PROVIDER: str = Field("ollama",      env="VISION_PROVIDER")
    VISION_MODEL:    str = Field("gpt-4o-mini", env="VISION_MODEL")

    # ── Ollama ──────────────────────────────────────────────────────
    OLLAMA_HOST:         str = Field("http://localhost:11434", env="OLLAMA_HOST")
    OLLAMA_MODEL:        str = Field("llama3.1:8b",            env="OLLAMA_MODEL")
    OLLAMA_VISION_MODEL: str = Field("llava:13b",              env="OLLAMA_VISION_MODEL")

    # ── Paths ───────────────────────────────────────────────────────
    MODELS_DIR:      Path = PROJECT_ROOT / "models"
    DATA_DIR:        Path = PROJECT_ROOT / "data"
    LOGS_DIR:        Path = PROJECT_ROOT / "logs"
    PIPER_MODEL_DIR: Path = PROJECT_ROOT / "models" / "piper"

    # ── Audio ───────────────────────────────────────────────────────
    SAMPLE_RATE: int = Field(16000, env="SAMPLE_RATE")
    CHANNELS:    int = Field(1,     env="CHANNELS")
    CHUNK_SIZE:  int = Field(1024,  env="CHUNK_SIZE")

    # ── Location ─────────────────────────────────────────────────────
    LOCATION_LAT:  float = Field(28.6139, env="LOCATION_LAT")
    LOCATION_LON:  float = Field(77.2090, env="LOCATION_LON")
    LOCATION_NAME: str   = Field("Delhi", env="LOCATION_NAME")

    # ── RAG ─────────────────────────────────────────────────────────
    VECTOR_DB_PATH:  Path  = PROJECT_ROOT / "data" / "vectordb"
    CHUNK_SIZE_RAG:  int   = Field(1000,               env="CHUNK_SIZE_RAG")
    CHUNK_OVERLAP:   int   = Field(200,                env="CHUNK_OVERLAP")
    EMBEDDING_MODEL: str   = Field("all-MiniLM-L6-v2", env="EMBEDDING_MODEL")

    # ── Wake word ────────────────────────────────────────────────────
    WAKE_WORD:             str   = Field("jarvis", env="WAKE_WORD")
    WAKE_WORD_ENABLED:     bool  = Field(True,     env="WAKE_WORD_ENABLED")
    WAKE_WORD_SENSITIVITY: float = Field(0.5,      env="WAKE_WORD_SENSITIVITY")

    # ── Code watcher ─────────────────────────────────────────────────
    CODE_WATCH_ENABLED:  bool = Field(True,          env="CODE_WATCH_ENABLED")
    CODE_WATCH_PATH:     str  = Field("~/Documents", env="CODE_WATCH_PATH")
    CODE_WATCH_INTERVAL: int  = Field(5,             env="CODE_WATCH_INTERVAL")

    # ── Streaming ───────────────────────────────────────────────────
    STREAM_RESPONSES:     bool = Field(True, env="STREAM_RESPONSES")
    MAX_CONTEXT_MESSAGES: int  = Field(20,   env="MAX_CONTEXT_MESSAGES")

    class Config:
        env_file = ".env"
        case_sensitive = True

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
