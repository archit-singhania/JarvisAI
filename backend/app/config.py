"""
Configuration management for Jarvis AI with FREE services
"""
import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field

# Get project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    """Application settings"""
    
    # API Keys
    GROQ_API_KEY: Optional[str] = Field(None, env="GROQ_API_KEY")  # FREE - For LLM and Whisper
    OPENAI_API_KEY: Optional[str] = Field(None, env="OPENAI_API_KEY")  # For Vision and TTS
    
    # Optional Fallback Keys
    GEMINI_API_KEY: Optional[str] = Field(None, env="GEMINI_API_KEY")
    ANTHROPIC_API_KEY: Optional[str] = Field(None, env="ANTHROPIC_API_KEY")
    
    # Server Configuration
    HOST: str = Field("0.0.0.0", env="HOST")
    PORT: int = Field(8000, env="PORT")
    DEBUG: bool = Field(True, env="DEBUG")
    
    # Model Configuration - FREE Services
    LLM_PROVIDER: str = Field("groq", env="LLM_PROVIDER")  # groq, gemini, ollama
    LLM_MODEL: str = Field("llama-3.1-70b-versatile", env="LLM_MODEL")
    
    # Vision Configuration
    VISION_PROVIDER: str = Field("openai", env="VISION_PROVIDER")  # openai, ollama
    VISION_MODEL: str = Field("gpt-4o-mini", env="VISION_MODEL")
    
    # Speech-to-Text Configuration
    STT_PROVIDER: str = Field("groq", env="STT_PROVIDER")  # groq, local
    WHISPER_MODEL: str = Field("whisper-large-v3", env="WHISPER_MODEL")
    LOCAL_WHISPER_MODEL: str = Field("base", env="LOCAL_WHISPER_MODEL")  # tiny, base, small, medium
    
    # Text-to-Speech Configuration
    TTS_PROVIDER: str = Field("openai", env="TTS_PROVIDER")  # openai, piper, gtts
    TTS_MODEL: str = Field("tts-1", env="TTS_MODEL")  # tts-1 or tts-1-hd
    TTS_VOICE: str = Field("alloy", env="TTS_VOICE")  # alloy, echo, fable, onyx, nova, shimmer
    
    # Ollama Configuration (for local models)
    OLLAMA_HOST: str = Field("http://localhost:11434", env="OLLAMA_HOST")
    OLLAMA_MODEL: str = Field("llama3.1:8b", env="OLLAMA_MODEL")
    OLLAMA_VISION_MODEL: str = Field("llava:13b", env="OLLAMA_VISION_MODEL")
    
    # Paths
    MODELS_DIR: Path = PROJECT_ROOT / "models"
    DATA_DIR: Path = PROJECT_ROOT / "data"
    LOGS_DIR: Path = PROJECT_ROOT / "logs"
    PIPER_MODEL_DIR: Path = MODELS_DIR / "piper"
    
    # Speech Configuration
    SAMPLE_RATE: int = Field(16000, env="SAMPLE_RATE")
    CHANNELS: int = Field(1, env="CHANNELS")
    CHUNK_SIZE: int = Field(1024, env="CHUNK_SIZE")
    
    # RAG Configuration
    VECTOR_DB_PATH: Path = PROJECT_ROOT / "data" / "vectordb"
    CHUNK_SIZE_RAG: int = Field(1000, env="CHUNK_SIZE_RAG")
    CHUNK_OVERLAP: int = Field(200, env="CHUNK_OVERLAP")
    EMBEDDING_MODEL: str = Field("text-embedding-3-small", env="EMBEDDING_MODEL")
    
    # Wake Word
    WAKE_WORD: str = Field("jarvis", env="WAKE_WORD")
    
    # Context Window
    MAX_CONTEXT_MESSAGES: int = Field(10, env="MAX_CONTEXT_MESSAGES")
    MAX_TOKENS: int = Field(8000, env="MAX_TOKENS")
    TEMPERATURE: float = Field(0.7, env="TEMPERATURE")
    
    class Config:
        env_file = ".env"
        case_sensitive = True
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Create directories if they don't exist
        self.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.VECTOR_DB_PATH.mkdir(parents=True, exist_ok=True)
        self.PIPER_MODEL_DIR.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()


# Logging configuration
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        },
        "detailed": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "detailed",
            "filename": str(settings.LOGS_DIR / "jarvis.log"),
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
        },
    },
    "loggers": {
        "jarvis": {
            "level": "DEBUG",
            "handlers": ["console", "file"],
            "propagate": False,
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
}