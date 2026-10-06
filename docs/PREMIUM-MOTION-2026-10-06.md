# Wednesday family motion and signature palettes

Wednesday's orb is an instrument for the current session. A finite pulse marks listening, thinking, completion, interruption and error state changes. A stable orbital rim and an always-visible composer indicator communicate progress. Stream chunks can briefly refresh the indicator; microphone expansion uses actual measured input. Idle and busy states have no continuous animation.

Browser and connected AuraScript 2 transitions use a 220 ms eased arrival for routes, panels, transcripts and dialogs, with a 120 ms modal exit. Replacement transitions cancel earlier clocks, reduced motion cancels work already in flight, and an older network response cannot replace the currently selected browser route. Modal focus, native close, Escape, navigation, records and owned persistence retain their existing behavior. The editor applies the same restrained motion to file selection, folder expansion, commands, saving and terminal start/completion; code and terminal text stay solid.

Native Windows uses finite opacity and position/scale transitions in response to view-model section, transcript, listening, progress and status changes. Each property has at most one clock and one short cleanup timer. Replacement, reduced motion and window disposal release them; event subscriptions are removed on close. The native motion smoke samples live clocks, cancels them mid-transition and checks that completed clocks are released.

Preferences persist three signature palettes per owned workspace: **Amethyst** (violet/platinum), **Lagoon** (mineral/sea glass), and **Ember** (copper/warm pearl). They work with light, dark or system appearance; neutral reading surfaces and semantic success/error colors remain clear. High contrast, reduced transparency, system preferences and local Manrope font assets remain supported. Native typography uses Segoe UI Variable with Segoe UI fallback.

Fresh machine evidence is in `PREMIUM-MOTION-2026-10-06.json` and `test-results/premium-motion`. Captures in `docs/screenshots/premium-motion-2026-10-06` were taken with motion enabled, plus settled theme/accessibility/native renders. The live browser journey uses an isolated real service and real owned preferences, provider failure, and a synthetic browser microphone through MediaRecorder. Editor journeys use real IPC, file saving, diagnostics, terminal and Git operations in a newly created fixture. Native listening state is a synthetic view-model stimulus; WAV/MP3 checks use the production decoder. These do not claim physical microphone/speaker or live inference acceptance.

Manual review:

1. Change sections rapidly while a request is pending. The selected heading and panel should agree and keyboard focus should remain usable.
2. Open and dismiss a memory dialog with the close button and Escape. It should arrive gently, exit promptly, retain modal focus and save a real edit.
3. Send a request, interrupt, reconnect, then record voice. The indicator should follow actual activity, the orb should respond to measured sound, and motion should stop after completion.
4. Enable reduced motion during an arrival or pulse. It must settle immediately. Repeat with the operating system setting and after reload.
5. Switch each palette in both appearances, reload and inspect focus, disabled controls, selected navigation, source chips, high contrast and opaque chrome. Check at 390 pixels.
6. In native Windows, navigate repeatedly, toggle reduced motion, then close and reopen. Confirm no held opacity/position or repeated event response.
7. In connected AuraScript 2, open a folder and file, save, run a terminal command, open Commands and Preferences, and record/interrupt Wednesday. Check the actual Monaco high contrast setting as well as chrome.

Physical audio devices, configured model inference, interactive installation, unsigned distribution and other operating systems remain manual/platform checks described in `RELEASE.md`. No standalone AuraScript 3 source is changed by this refinement.
