# Twenty-capability acceptance matrix

This matrix distinguishes connected implementations and executed local checks from live engine/hardware gates. A provider requirement never appears as a fabricated completion. Authentication, themes, accessibility preferences and settings are additional foundations.

| # | Capability and connected implementation | Recorded acceptance / remaining gate |
|---|---|---|
| 1 | Streaming text and sentence-ordered spoken responses across browser/WPF/editor | Cancellation/order/persistence contract tests pass. Live inference and server speech require a configured engine. |
| 2 | Multilingual transcription, finalized WAV/browser recordings, MP3/WAV playback | Unicode and ordered format handling verified; real microphone/Whisper/cloud consent remains device/provider validation. |
| 3 | Browser RMS microphone meter and silence-based VAD; native RMS waveform | Connected to real captured samples. Physical input and denied-microphone hardware journeys remain manual. |
| 4 | Optional local ONNX wake-word listener with verified startup/error behavior | Requires explicitly installed model, openwakeword and PyAudio. No energy-trigger substitution or automatic model download. Live device gate open. |
| 5 | Active-turn interruption cancels async generation/vision and queued speech | Session and image cancellation tests pass; clients suppress interrupted turn audio. |
| 6 | Connection-specific history/context, authenticated owned storage | Unit/API and separate fresh-browser owner isolation pass. |
| 7 | Persistent searchable conversation sessions and restored history | SQLite restart/readback and live browser reload pass. Native/editor use their own session identities. |
| 8 | Private PDF/text/source ingestion and cited local excerpt retrieval | Real upload/readback and source IDs pass; retrieval is lexical, with no vector-engine claim. |
| 9 | Editable/deletable memories and JSON workspace export | Live memory save/reload, privacy isolation and actual downloaded export pass. |
| 10 | Explicit selected-image analysis and editor screenshot-file chooser | Signature validation and async cancellation pass. Ollama vision/OpenAI inference requires provider configuration. |
| 11 | Deliberate bounded tools, confirmations, demo-mode boundaries and receipts | Ownership/permission API tests and live time receipts pass. Host launch requires individual confirmation. |
| 12 | Durable IANA/UTC reminders, cancellation and delivery acknowledgment | UTC/DST and non-moving due-date tests pass; live browser schedule/cancel passes. Controls are independent of stopped turns. |
| 13 | Focus modes and owned configurable response style/persona | Stored preferences flow into canonical prompts; browser focus/settings and native settings operate. |
| 14 | Local/cloud selection, model list and capability diagnostics | Real missing-Ollama status and provider-failure UI pass. Keys show configured status, not a live-availability guarantee. |
| 15 | Code review uses only explicitly selected files | Context boundary/clear repaired and tested; live AI review remains engine-dependent. |
| 16 | Maintained AuraScript explorer, tabs, create/open and atomic saves | Real isolated Electron file saving passes. Exclusive creation rejects collisions; path and linked escapes are tested. |
| 17 | Actual Python AST/JSON diagnostics plus bundled Monaco language workers | API diagnostics and live invalid-Python editor markers pass; no fabricated linter results. |
| 18 | Asynchronous terminal streams and cancellation within selected project | Real process output/exit and long-process cancellation pass. Hosted browser has no terminal IPC. |
| 19 | Genuine Git checkpoint and full diff/history inspection | Real temporary-repo commit and diff inspection pass; repository-root guard prevents parent-repo changes. |
| 20 | Command palette/shortcuts and persistent explicit reusable workflows | Real Electron command palette and browser workflow/receipt execution pass. Host actions cannot run implicitly in workflows. |

Acceptance evidence: `backend/tests`, `aurascript/tests`, real browser/Electron captures under `docs/screenshots`, demo recording under `docs/demo`, and release notes. WPF compiles with zero warnings/errors and has an invisible runtime/XAML/render/clean-exit smoke check. NSIS packaging is executed on Windows. Optional models, live cloud credentials, microphone devices, macOS/Linux packages and production deployment are not marked passed.

The complete flagship code uses the maintained API/runtime. Experimental legacy neural/RAG/code-watch modules remain outside this release and are not counted as additional verified capabilities.
