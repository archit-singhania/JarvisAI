# Release validation and CV evidence

Local verification on Windows x64, Python 3.12.14, .NET SDK 10.0.401, installed Chrome, Electron 44.5.1 and the locked offline Monaco bundle. Python 3.11 is configured in container/CI for compatible optional ML environments.

Executed checks cover backend ownership/persistence/cancellation and message contracts; browser memories/documents/reminders/workflows/export, two-owner isolation, theme preferences, missing-provider failure, and 390px layout; real Electron IPC, file saving, Python diagnostics, streamed terminal processes, a temporary-repo Git commit/full diff, command palette and themes; WPF release build and invisible XAML/render/clean-exit smoke. Check the latest generated acceptance records under `test-results` and recorded captures in `docs/screenshots`.

Commands:

```powershell
python -m pytest -q
cd aurascript
npm test
node tests/browser-smoke.cjs # isolated Wednesday service on port 8006
node tests/electron-smoke.cjs # Windows with downloaded Electron runtime
npm audit
npm run build:win
```

The full browser acceptance deliberately uses an engine-free service so it can verify honest provider failures. Streaming model/audio ordering unit tests use labeled fixture adapters. The screenshot and demo show actual applications and persisted operations; they are not concept mockups. Demo inputs are acceptance fixtures.

Windows artifacts: NSIS installer under `aurascript/dist`; WPF self-contained package under `release`. The source bundle excludes real `.env`, session credentials, user data, downloaded models and generated Python environments. Packages are unsigned unless a signing identity is configured. Installer construction and extracted executable relaunch are separate checks; installer UI installation/device audio should be checked before distribution to other users.

Open release gates: live local/cloud LLM responses and code review; actual microphone capture and playback on reference devices; optional Whisper/Coqui/ONNX model installation; macOS/Linux package execution; Docker/host deployment, HTTPS, production backup/recovery; provider/account credentials and chosen public hosting destinations. The configured CI workflow has not been run remotely because this work has not been pushed.

## Portfolio demonstration

1. Show the original Wednesday interface in both themes.
2. Save a memory and import a source document; reload to prove persistence.
3. Inspect provider availability and genuine engine errors before configuration.
4. Schedule/cancel a timezone-aware reminder; run a deliberate workflow and inspect receipts.
5. Show AuraScript opening a project, saving a file, producing genuine diagnostics, streaming a terminal process and recording a real Git checkpoint.
6. Show the native Windows counterpart and release package.

Use only measured claims on a CV, for example: “Built a FastAPI/.NET/Electron assistant workspace with owned durable sessions, cancellable streaming, ordered speech events and a bundled code editor; verified persistence, isolation, process cancellation and real Git workflows through automated application journeys.” Cite actual test totals and package results from the final verification record. Do not claim a measured 60fps/device audio/live-model result until those reference-device tests are performed.
