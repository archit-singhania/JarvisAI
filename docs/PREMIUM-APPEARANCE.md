# Wednesday family appearance refinement

The maintained browser assistant, native Windows client and Wednesday-connected editor share an ink, amethyst and platinum palette, with cool mineral accents. Light mode uses warm paper surfaces and deep slate text. Glass navigation, action islands, composers and dialogs have subtle edge highlights; transcript, code and terminal content remain readable, solid surfaces.

The browser and Electron interface now bundle the Manrope variable font locally, with system fallbacks. The SIL Open Font License is included beside each font in `ui/assets/fonts` and `aurascript/src/assets/fonts`; no external font request is needed. Native Windows uses Segoe UI Variable Text and Display with Segoe UI fallback. Typography, selected states, input focus, spacing and panel hierarchy have been refined throughout the maintained clients.

Use Preferences to select light, dark or system appearance. Reduce transparency replaces glass with opaque chrome; high contrast also changes the actual Monaco code theme. Reduce motion disables interface transitions and editor smooth scrolling. The underlying stored work and controls are unchanged by appearance settings.

To inspect the result manually:

1. Start Wednesday through the setup guide, open `/ui/`, and inspect the rail, orb, header actions, composer, memory cards and preferences in both themes.
2. Resize the browser to 390 pixels. Navigation should become a floating dock; settings and the composer should remain within the viewport.
3. Save high contrast and reduced transparency preferences, reload, and confirm opaque surfaces and clear control boundaries. Toggle reduced motion to verify immediate transitions.
4. Launch the native client and inspect Assistant, Memory and Preferences in both themes; the Send button should retain readable text against its violet background.
5. Start the maintained editor in `aurascript`, open a project, inspect syntax colors and code/terminal separation, then switch its high contrast setting. Code and chrome should both change. Save, diagnostics, terminal and Git operations retain their existing behavior.

Fresh acceptance evidence is recorded under `test-results/premium-appearance-2026-10-06.json`; actual captures are copied into `docs/screenshots/premium-appearance-2026-10-06`. The browser journey covers real owned persistence, documents, reminders, workflows, export and responsive layouts; Electron journeys exercise actual IPC, file saving, diagnostics, terminal and Git checkpoints plus typography and accessibility states. Native smoke uses the production WAV/MP3 decoder and actual XAML rendering. Model providers, physical microphones/speakers, interactive installation and other operating systems remain separate setup/platform checks documented in [RELEASE](RELEASE.md).
