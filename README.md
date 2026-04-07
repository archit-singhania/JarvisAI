# Jarvis AI

An advanced, Siri-like voice assistant with a sleek WPF desktop UI, powered by a Python FastAPI backend.
Built to be impressive on a resume and as a portfolio project for roles at top-tier companies.

---

## Architecture

```
desktop/   → C# WPF (.NET 8) — Iron Man-style dark UI
backend/   → Python FastAPI — AI brain (LLM, STT, TTS, Vision, RAG, Tools)
```

Communication: WebSocket (`ws://localhost:8000/ws`) for real-time voice + text.

---

## Unique features

- 🎤 Voice input via Groq Whisper (fast, free)
- 🔊 Natural TTS via Coqui (free, local)
- 🧠 LLM: Groq llama-3.1-70b (online) / Ollama (offline)
- 🛠 Tool system: time, weather, open apps, web search, rap, sing, jokes, reminders
- 📖 RAG memory: ChromaDB + sentence-transformers (feed it documents, it remembers)
- 🖥 Screen analysis: "Hey Jarvis, what's on my screen?" via LLaVA vision
- 🎵 Rap & sing on command — unique feature no other open-source assistant has

---

## Quickstart

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # add your GROQ_API_KEY
uvicorn app.main:app --reload
```

### Desktop (Windows)
```bash
cd desktop
dotnet restore
dotnet run
```

---

## Phase status

| Phase | Feature                        | Status        |
|-------|-------------------------------|---------------|
| 1     | FastAPI server + WebSocket    | ✅ Done        |
| 1     | LLM client (Groq/Gemini/Ollama)| ✅ Done        |
| 1     | Orchestrator                  | ✅ Done        |
| 1     | STT (Groq Whisper + local)    | ✅ Done        |
| 1     | TTS (Coqui + gTTS fallback)   | ✅ Done        |
| 2     | Tool system (7 tools)         | ✅ Done        |
| 2     | RAG engine (ChromaDB)         | ✅ Done        |
| 2     | Vision processor (LLaVA)      | ✅ Done        |
| 2     | WPF UI skeleton + ViewModel   | ✅ Done        |
| 2     | WebSocket C# client           | ✅ Done        |
| 2     | Audio recording (NAudio)      | ✅ Done        |
| 3     | Wake word ("Hey Jarvis")      | 🔲 TODO        |
| 3     | Streaming token output        | 🔲 TODO        |
| 3     | Interrupt handling            | 🔲 TODO        |
| 3     | Reminder scheduler            | 🔲 TODO        |
| 3     | Voice cloning (Coqui)         | 🔲 TODO        |
| 3     | Memory dialog in UI           | 🔲 TODO        |
| 4     | Installer / packaging         | 🔲 TODO        |
| 4     | GitHub Actions CI             | 🔲 TODO        |

---

## Get a Groq API key (free)
https://console.groq.com/keys
