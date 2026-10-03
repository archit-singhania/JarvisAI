# Wednesday, Windows assistant and AuraScript: manual testing

Run the first section without API keys. Persistence, documents, memories, reminders, explicit tools, workflows, editor saving, diagnostics, terminal processes and Git work independently of inference. AI responses, speech, vision and wake word require the explicitly selected engine. An unavailable engine must produce a readable error; it must never produce a fabricated response or completion.

## 1. Start the local service

Use separate PowerShell terminals. From this checkout, the installed shared Python can run the core immediately:

```powershell
Set-Location D:\remaining-4-git-projs\JarvisAI
& ..\.tooling\python\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

For a fresh machine, use Python 3.11 (recommended for optional ML packages) or Python 3.12 for the core:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements-core.txt
if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/ui/. Expected: the new moon mark and orb, “Workspace connected”, readable assistant surface, navigation, and persistent Preferences. `/health` returns `status: ready`, `version: 1`; `/docs` shows HTTP contracts. If port 8000 is occupied by the existing preview, use it rather than launching a second process. For an alternate port set `ALLOWED_ORIGINS` to its exact browser URL plus `aura://app`, start Uvicorn on that port, and set `WEDNESDAY_URL` for native clients.

There is no shared demo login. A fresh browser creates a private owned session; WPF and AuraScript create their own private identities. Stay on the same hostname (`127.0.0.1` or `localhost`) when testing persistence. Incognito has a separate identity. Browser cookie, WPF `%LOCALAPPDATA%\Wednesday\session.json` and Electron's local session file are credentials: keep them private. JSON exports omit the credential and do not silently merge accounts.

For disposable manual data, set `WEDNESDAY_DATA_DIR` to a new directory **before** starting the server; do not point automated tests at useful user data. Existing data is preserved under `data/workspace.db`.

## 2. Free local browser journey: about 10 minutes

| Action | Expected result |
|---|---|
| Preferences → choose Pearl, then Graphite, then System; save and reload | Theme persists. System follows browser appearance. Controls and text remain legible. |
| Enable Reduce motion and Reduce transparency | Preference persists; decorative movement and blur are reduced. Keyboard focus remains visible. |
| Memory → Add memory; title `Launch target`, content `The release target is December.` | A saved memory card appears. Reload and reopen Memory: it is still there. |
| Edit that memory to `The release target is January.`; save | The same memory changes, without a duplicate. Remove it when done: it disappears. |
| Create a text file `launch-notes.md` with `Launch budget is 1200. Target market is students.`; Knowledge → Import | Filename appears only after actual upload/extraction. Reload retains the document. Unsupported or corrupt PDF files produce an error. |
| Reminders → Schedule reminder for 1–2 minutes ahead in your IANA zone, such as `Asia/Kolkata` | The saved card contains the resolved date/status/timezone. Keep the workspace connected; notification arrives on a 10-second polling interval and is acknowledged as delivered. |
| Schedule a second future reminder and cancel it | Status changes to cancelled. Reload retains cancellation and it never fires. |
| Tools & workflows → Run a tool → Current time | Service returns actual time and records a `time` receipt. Reopen the section to inspect it. |
| Save workflow `Morning check` with one line `time`; run it | Actual result appears and a new receipt is persisted. Weather/search additionally need internet. |
| Export workspace | An actual JSON download includes owned records, conversations, reminders, preferences and receipts. Open it and check your entered values. |
| Open a fresh incognito browser at the same URL | It has an empty independent workspace and cannot see your memory/document/history. |
| Enter a question without configuring an AI provider | A real provider-unavailable message appears. No fabricated answer or synthetic success is saved. |
| Stop the service with Ctrl+C and restart using the same data directory; reload the same browser | Owned records and preferences survive restart. Pending reminders retain their original due instant. |

Use the sidebar history drawer/search after a successful AI conversation, and reload or reopen that session to check saved messages. “New” starts a separate conversation. It does not erase previous history.

## 3. Configure and test actual intelligence

The free local path uses an installed Ollama service and a downloaded compatible model. Choose a model your machine can run; the application never downloads one automatically. Put `OLLAMA_HOST` and `OLLAMA_MODEL` in the private `backend/.env`, restart the backend, then choose Ollama and the same model name in Preferences. Cloud paths require the matching Groq/OpenAI/Gemini key and supported model name; provider selection never silently switches to another engine. See [SETUP.md](SETUP.md).

| Check | Expected result |
|---|---|
| Ask `Explain the tradeoffs of SQLite WAL for a local app.` | Text streams incrementally, reaches a clear completion, and survives reload. Engine errors appear as errors. |
| Request a long explanation, press Stop while it is streaming | Generation stops promptly; no additional queued speech plays. The saved partial conversation remains readable. |
| Immediately ask a second question | A new turn responds; interrupted content does not contaminate it. |
| Ask `What is the launch budget in my source?` after importing the notes | Matching private excerpts are supplied with source IDs. Inspect cited source evidence. Retrieval is lexical, so the query should share meaningful terms. |
| Set response style `Use three concise bullets.` and focus Coding; save, ask again, reload Preferences | Configuration persists and is included in new prompts. Response quality still depends on the selected model. |
| Use a second separate client concurrently | Each client retains its own conversation and interruption state. Stopping one does not stop the other. |
| Disconnect/reconnect or reopen saved history | Persisted history reloads; aborted inference is not claimed to have resumed silently. |

## 4. Voice, selected images and wake word

Install only the engines you select. Speech setup is explicit in [SETUP.md](SETUP.md); default server speech is `none`. Optional Edge/gTTS need internet, Groq transcription needs its key, local Whisper needs its package/model and FFmpeg, and local Coqui needs a compatible Python 3.11 environment/model. Selecting an unconfigured engine produces an honest unavailable result.

| Check | Expected result |
|---|---|
| Browser Voice → deny microphone permission | Readable permission error; no “listening” success and no uploaded audio. |
| Allow microphone, speak a sentence, then pause or stop recording | Orb/input feedback reflects actual RMS energy. The recording is finalized; silence-based VAD or manual stop sends it. Configured transcription produces visible text before response. |
| Change speech language and speak in that language | Unicode transcript is retained. Engine/language support is shown by the actual result. |
| Enable Speak with a configured server TTS adapter | Sentence chunks play in order with their actual MP3/WAV format. Press Stop during speech: queued audio stops. |
| Select an image through Image; use installed Ollama vision model or configured OpenAI vision | Only selected PNG/JPEG/WebP bytes are analyzed. No background screenshot capture occurs. Invalid/oversized files fail. |
| Start optional local wake listener in Preferences | Requires the installed `models/wakeword/hey_jarvis.onnx`, dependencies and microphone. Only verified startup reports active; missing model/device gives an error. |
| Say the wake phrase, then stop listener | Owned wake notification appears; microphone listener stops. Another workspace cannot stop your listener. |

Microphone capture, audible quality, live inference and model accuracy require hardware/provider acceptance; the automated tone/fixture tests do not stand in for these checks.

## 5. Native Windows assistant

Start the backend first, then either run the source or use the extracted Windows release:

```powershell
Set-Location D:\remaining-4-git-projs\JarvisAI
$env:WEDNESDAY_URL = 'http://127.0.0.1:8000'
& ..\.tooling\dotnet\dotnet.exe run --project desktop\JarvisAI.csproj -c Release
```

Fresh machine source builds require .NET 10 SDK. The self-contained release executable needs no .NET SDK. Extract the latest `release/Wednesday-win-x64-*.zip` to a writable private folder. If no backend is running, execute `Start-Wednesday.ps1` from that folder with Python 3.11/3.12 installed. It installs a local core environment, starts its own backend, launches Wednesday, and stops only that backend when the client closes. A busy port fails clearly; `-Port 8019` selects another free port. If the backend is already running, launch `desktop/JarvisAI.exe` directly with `WEDNESDAY_URL` set.

Repeat Memory save/edit/remove, Knowledge import, Reminders save/cancel, Time tool, explicit workflow, Preferences and JSON export. Expected: durable results in this client's separate workspace, no raw technical error payloads, clear listening/connection state, correct timezone shown in Preferences/Reminders. Set response style, language and IANA timezone and relaunch: settings persist. Try high-contrast Windows settings, keyboard tab navigation, large display scaling, both themes and reduced motion.

The reminder editor suggests one hour ahead in the selected timezone, including daylight-saving changes. Blank/invalid/absolute timezone strings are rejected with a readable validation message without overwriting your last valid preference. If first-run dependency installation is interrupted, rerun the release launcher: it retries unfinished setup and repairs missing/changed core dependencies before starting the service.

For voice, click Voice once to record and again to finalize/send. Input waveform reflects real samples. MP3/WAV are decoded according to the server event format. Physical device checks remain manual. The invisible render/clean-exit and synthetic WAV/MP3 decoding checks have already passed.

## 6. AuraScript editor: use a disposable Git repository

Start the service, then launch AuraScript source with Node 22.12 or newer:

```powershell
Set-Location D:\remaining-4-git-projs\JarvisAI\aurascript
npm.cmd ci
npm.cmd run prepare:editor
npm.cmd start
```

Or install `aurascript/dist/AuraScript Setup 2.0.0.exe`, then launch it while the backend runs. This is an unsigned local portfolio package; publisher signing remains a distribution step. The packaged executable has its own application acceptance check; running the interactive installer and uninstall flow on a spare Windows profile is a separate manual release gate.

Create a scratch folder outside these product repos, run `git init`, and set a local Git user name/email. Open that exact root in AuraScript. Do not run checkpoint tests against useful unstaged work: a deliberate checkpoint commits changes in the selected repository.

| Action | Expected result |
|---|---|
| Open workspace; create `hello.py`; enter `print("saved")`; Ctrl+S | Explorer/tab/model appear, “Saved” status appears, disk file contains that exact text. Close/reopen retains it. |
| Create `hello.py` again | File-exists error; original content survives. Parent folder must exist. |
| Edit then close an unsaved tab/window | Explicit unsaved-edit confirmation. Keep editing preserves the buffer; discard is deliberate. |
| Enter `def broken(:` | Real Python syntax diagnostic appears. Correct it: marker clears. JSON/JS/TS/HTML/CSS use supported parser/Monaco workers. |
| Ctrl+K; search `Preferences`; choose Pearl/Graphite/System and accessibility settings | Palette executes the real command; application and code themes agree and preferences persist. |
| Terminal: `git --version` | Real streamed output and process exit code appear. |
| Terminal: `node -e "console.log('running');setInterval(()=>{},1000)"`, then Stop process | Stream contains `running`; the process tree exits. A subsequent command runs normally. |
| Save all tabs → Save checkpoint → enter a message → Git history → select commit | A genuine Git commit exists, with full diff shown. Non-repository roots/parent repo misuse fail explicitly. |
| Select a file → Review file with configured AI | Only that file's explicit context is supplied. Closing its last tab or switching workspace clears it. |
| Memory / History / Export | Actual owned service state is edited/read/exported. This client's session is separate from browser/WPF. |
| Disconnect the backend; try a service action | Clear unavailable state. Local file saving remains independent. Reopen History after backend restart to reconnect. |

The browser version has no editor filesystem/terminal IPC. Local terminal commands run only after explicit submission; reusable service workflows cannot launch host apps implicitly.

## 7. Twenty-capability checklist

Use this for your own acceptance record. Write date, platform, selected engine, pass/fail and a screenshot or exported output for each row. Keep configured-only or device-required rows pending until their real check runs.

| # | Capability | Manual evidence |
|---|---|---|
| 1 | Streaming text and speech | Live streamed answer, ordered playback, saved history |
| 2 | Multilingual speech and decoding | Actual transcript plus audible MP3/WAV playback |
| 3 | VAD and input feedback | Real microphone meter, silence stop and denied-permission check |
| 4 | Local wake word | Installed model/device start, wake and stop |
| 5 | Interruption | Active stream and queued audio stop, next turn succeeds |
| 6 | Concurrent client isolation | Two private clients, independent messages/cancellation |
| 7 | Durable searchable sessions | Restart/reload and history search |
| 8 | Documents and citations | Real upload, matching source query and inspectable citation |
| 9 | Editable memory/export | Save/edit/remove plus actual JSON download |
| 10 | Selected image analysis | Explicit chooser, live vision result, invalid upload check |
| 11 | Permissioned tools/receipts | Time receipt, host confirmation and demo-mode denial |
| 12 | Timezone reminders | Actual delivery, cancellation, restart and DST validation |
| 13 | Focus/personas | Persisted settings used in new live prompt |
| 14 | Providers/diagnostics | Healthy engine plus explicit unavailable-engine error |
| 15 | Contextual code review | Selected-file review, last-tab/workspace context clearing |
| 16 | Project files/tabs/saving | Disk readback, reopen, collision preservation, unsaved prompt |
| 17 | Language diagnostics | Invalid/corrected Python/JSON/Monaco markers |
| 18 | Terminal processes | Streamed output, exit code and process-tree cancellation |
| 19 | Git checkpoints/diffs | Actual commit inspected outside UI as well as in editor |
| 20 | Palette/shortcuts/workflows | Real keyboard action and persisted time-workflow receipt |

## 8. Repeat automated checks

```powershell
Set-Location D:\remaining-4-git-projs\JarvisAI
& ..\.tooling\python\Scripts\python.exe -m pytest -q
Set-Location aurascript
npm.cmd test
npm.cmd audit
```

Application tests use a separate engine-free backend on port 8006 and private `WEDNESDAY_DATA_DIR`; its allowed origin must include `http://127.0.0.1:8006,aura://app`. With Playwright/Chrome installed, run `node tests/browser-smoke.cjs` and `node tests/electron-smoke.cjs`. `RECORD_DEMO=1` records the paced browser test. To test the packaged editor set `AURA_EXECUTABLE` to the absolute `dist/win-unpacked/AuraScript.exe` path. Do not set test data to your normal workspace.

Recorded acceptance and remaining platform/provider gates are in [CAPABILITIES.md](CAPABILITIES.md) and [RELEASE.md](RELEASE.md). The final plan does not mark unrun live speech/inference, macOS/Linux packaging, reference-device frame rate, signed installation, public deployment, backups or experimental models as passed.
