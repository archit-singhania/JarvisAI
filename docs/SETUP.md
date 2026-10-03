# Engine and environment setup

## Core

Python 3.11 is the recommended environment for ML extras. The FastAPI core was verified with Python 3.12.14. Use `backend/requirements-core.txt` for document/storage/tool workflows without model downloads. `.NET 10` runs WPF; Node 22.12 or newer builds the Electron editor. Keep the ignored `.env` and local session files private.

`WEDNESDAY_DATA_DIR` overrides the service data directory. `WEDNESDAY_URL` selects the service URL for WPF/AuraScript. `WEDNESDAY_CLIENT_DATA` overrides WPF client state for isolated tests; `AURA_TEST_DATA` and `AURA_HEADLESS=1` isolate invisible Electron acceptance runs. These test overrides are not required for ordinary use.

## Intelligence

Run Ollama, install the model you select, and configure `OLLAMA_HOST`, `OLLAMA_MODEL`. The default model name is `llama3.1:8b`; the service does not automatically download it. Cloud adapters use direct asynchronous HTTP and require the matching Groq/OpenAI/Gemini key. Choose the provider and correct model in Preferences. No provider is silently substituted.

Image analysis uses the explicitly configured `VISION_PROVIDER=ollama` with `OLLAMA_VISION_MODEL`, or `VISION_PROVIDER=openai` with `VISION_MODEL` and its key. Images are never captured automatically. Only selected PNG/JPEG/WebP bytes are sent.

## Speech and wake word

Server speech is disabled by default. Install `requirements-speech.txt` for optional internet providers, then select `TTS_PROVIDER=edge`, `gtts`, or `elevenlabs` explicitly. ElevenLabs also needs its key/voice settings. Edge/gTTS require internet; they are not described as offline engines.

Local transcription requires an installed `openai-whisper` package, an explicitly downloaded Whisper model, and FFmpeg in PATH. Select `STT_PROVIDER=local`. Groq transcription needs its key and `STT_PROVIDER=groq`. Browser recording finalizes its MediaRecorder payload; WPF closes the WAV writer before sending audio. Local Coqui speech requires its compatible Python 3.11 installation/model and `TTS_PROVIDER=coqui`. Those optional ML environments are not part of the minimal core lock or the executed hardware acceptance here.

For wake word, install openwakeword/PyAudio/ONNX prerequisites and explicitly place the genuine `hey_jarvis.onnx` model in `models/wakeword`. Start it from Preferences. Startup waits for the model and microphone; failures return an unavailable result. It never substitutes generic noise detection for wake-word recognition. Demo mode blocks this host microphone listener.

## Durable data and recovery

Back up the SQLite workspace with Python's `sqlite3.Connection.backup` while the service is running, or stop the service and preserve the database/WAL together. Keep backups private. The client session credential is needed to restore its identity; it is deliberately excluded from portfolio bundles. Old legacy memory/vector files remain preserved and are not automatically assigned to new unrelated sessions. Import useful legacy content explicitly through the authenticated document/memory APIs.

## Build dependencies

Use `npm ci` and `npm run prepare:editor` under `aurascript`. If npm's install-script approval configuration blocks Electron's official download, run `node node_modules/electron/install.js` in that directory after reviewing it. The maintained build compiles offline Monaco and language workers from locked ESM sources, including the patched DOMPurify override. It does not fetch scripts from a CDN at runtime.

Electron's downloader is locked to the official `@electron/get` 5.1.0, which uses native fetch and avoids the older vulnerable cache-library chain. This needs Node 22.12+ for CommonJS/ESM interoperability with the maintained builder. Current dependency audit and rebuilt-package results are in RELEASE.md.
