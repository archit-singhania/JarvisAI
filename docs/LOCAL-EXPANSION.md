# Wednesday local expansion

Implementation and acceptance record: November 17, 2026. These four additions now have backend, browser and WPF source implementations. This is not a claim that every release gate is complete.

## Offline operations

Open **Local workspace** in the browser or **Continuity studio → Local edits** in WPF. Save a note, conversation draft, existing memory correction or local reminder. Browser queue entries and unfinished form values are stored per workspace in local storage; desktop entries are written atomically to a per-workspace JSON queue. Desktop users load their authenticated workspace identity before going offline.

Disconnect after opening the application, save an operation, reconnect and synchronize. Expect one resulting revision even if the response was lost and the operation is retried. Browser reconnect attempts safe synchronization automatically. WPF synchronization is explicit. Pending, syncing, failed, completed and conflicted browser states are visible. A conflict shows your submitted text and the saved version; explicitly choose the revision to overwrite. In WPF inspect both versions in the result, then create a new operation with the current revision. Completed entries can be removed locally.

Notes enter local knowledge retrieval. Drafts are saved drafts, not sent messages. Memory corrections preserve original provenance and revision history; use the existing memory inspector to obtain the ID/version. Reminders require an explicit UTC offset. Commands, host actions and external writes are rejected by the queue contract. Workspace identity is checked again before synchronization. After one connected load, a service worker caches only public application files (never API responses). Offline reload restores the last workspace and pending edits. WPF similarly restores its last loaded identity locally; synchronization still requires a matching authenticated owner. Clearing browser/application storage removes these local drafts and queue entries.

## Calendar planning

Import an `.ics` file, inspect events, enter a working-window start/end with UTC offsets and a duration, and request a proposal. Inspect the exact proposed interval before approving a local event or a Google write. Existing events block time; calendar changes invalidate unapplied proposals. Retries use stable event IDs. Export and reopen the `.ics` file to inspect real saved events.

Calendar-file import supports UTC and IANA TZID timed events, folded lines and escaped summaries. Ambiguous/nonexistent daylight-saving times are rejected; convert them to UTC explicitly. All-day date values use the workspace timezone and round-trip as dates. Recurring imports preserve rules, extra dates, exclusions, moves and cancellations. Open-ended rules expand on demand up to 9,000 occurrences per series. The planner rejects requests outside verified coverage. Export folds UTF-8 lines. Working windows are at most seven days and blocks are 5–480 minutes. Multi-task priority scheduling and recurring working-hour presets remain follow-up work.

### Optional Google adapter

For interactive sign-in, configure a Google OAuth web application with the Calendar API enabled, then set these process environment variables on the Wednesday host:

- `WEDNESDAY_GOOGLE_CLIENT_ID` and `WEDNESDAY_GOOGLE_CLIENT_SECRET` from the OAuth application.
- `WEDNESDAY_GOOGLE_REDIRECT_URI` to the exact registered callback, for example `http://localhost:8000/api/expansion/calendar/google/oauth/callback`.
- `WEDNESDAY_GOOGLE_CREDENTIAL_KEY` to a persistent Fernet key. Generate it with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and keep it outside Git and database backups.

Choose **Sign in with Google** in either client, finish consent in the browser, then select a calendar and synchronize. Keep the credential key available across restarts. Sign-in stores an encrypted workspace-bound refresh token. Live-account behavior remains unverified.

For host-provisioned access, set `WEDNESDAY_GOOGLE_OWNER` to the authorized workspace ID and provide either `WEDNESDAY_GOOGLE_ACCESS_TOKEN` or `WEDNESDAY_GOOGLE_REFRESH_TOKEN` with the OAuth client ID and secret. Sync persists checkpoints, handles pagination and HTTP 410 recovery, and processes remote deletions. It is bounded to 50 pages of 1,000 events.

Approved writes re-synchronize first, compare the reviewed calendar snapshot, use a stable Google event ID and recover uncertain responses. No attendees are added and `sendUpdates=none` is sent. Calendar changes after the last read remain an external-service race; the adapter is not a distributed scheduling lock. Disconnect clears the browser sign-in grant, pending sign-in attempts and imported Google events from the workspace. Host-provisioned credentials and Google-side grants are managed separately.

Implementation references: [Google synchronization](https://developers.google.com/workspace/calendar/api/guides/sync) and [event creation](https://developers.google.com/workspace/calendar/api/guides/create-events).

## Watched document folders

On the host, set `WEDNESDAY_WATCH_OWNER` to the authorized workspace ID and `WEDNESDAY_WATCH_ROOTS` to exact approved absolute directories separated by the operating system path separator (`;` on Windows). These are process environment variables. In WPF choose a directory, enter optional exclusion globs and explicitly approve indexing. The directory must exactly match a configured root. Hosted demonstration mode denies registration.

The browser exposes status and stop controls; it has no folder picker. TXT, Markdown and PDF files are scanned every 30 seconds. Hashes prevent re-extracting unchanged files. Changed files replace retrieval content, deleted/excluded files leave retrieval, and loss of root authorization withholds indexed content. Failed extraction is visible per file. Stop removes indexed copies without modifying originals.

Budgets: 2000 visited files, 4 MiB per file, 32 MiB read per scan, 100 PDF pages, 200,000 extracted characters per file and 10 million new extracted characters per scan. Symlinks and escaping paths are rejected. Source files are never edited. Operator-controlled roots must not be writable by hostile users: path replacement during a filesystem read is not protected by an OS-level directory handle. Extraction runs in a background thread; hard subprocess memory/time isolation and per-file job cancellation remain gaps.

## Evaluation dashboard

Save a deliberately redacted local query with expected owned source IDs, or a Python syntax example with its expected error state. Run the case and inspect/download its report. Deleting a source should turn a formerly passing retrieval case into a failed case. Python is parsed without executing it. Cases and results survive restart and are scoped to their workspace.

Reports include case hashes, formula/configuration versions, source hashes, elapsed time, failures and a synthetic waiting-task probe through the real `Runtime.interrupt` method. That probe does **not** establish cloud-provider or audio-queue cancellation performance. No model requests, host commands or external writes are replayed. Subjective/model-graded evaluation, richer tool adapters, latency distributions and configuration comparison charts remain open.

November 23: Browser and WPF cases can specify the expected line of a Python syntax error. A matching error on the wrong line fails the evaluation. Older cases still check only whether a syntax error occurred. WPF now also exposes the existing calendar timestamp evaluation. The expansion suite passed 42 tests with one platform-specific skip, and WPF built with zero warnings or errors.

## Evidence and release gaps

The final backend regression run passed 52 tests. WPF Debug build passed with zero warnings/errors. An Edge journey verified offline save/reconnect/reload, local calendar approval, evaluation execution and a 390px layout without horizontal overflow or JavaScript errors. Google tests use mocked responses, not a live account. Existing test tooling emits a Starlette/httpx deprecation warning.

Still required: interactive WPF journeys, updated packaged installation, full keyboard/screen-reader and light/dark visual review, physical-device checks, long-running performance/recovery profiling and live Google consent/token tests. No deployment, paid subscription, signing or automatic update execution was performed.

## November 18 acceptance update

Offline Edge reload/reconnect acceptance passed against the latest code. All 52 backend regressions passed again. WPF Debug build passed with zero warnings/errors. Actual native controls passed queue persistence, duplicate prevention, calendar approval, evaluation and folder-status checks. The same checks passed in the self-contained Windows executable. These programmatic native checks do not certify visual/screen-reader behavior. All 46 bundled Python, JavaScript, CSS and HTML source files matched repository hashes.

Package: `release/Wednesday-win-x64-20261118-044338.zip`. No live Google account was used. Remaining release checks include visual/native accessibility, physical devices, load/performance profiling and live-provider consent/token behavior. Remaining implementation gaps include coverage beyond the recurrence cap, multi-task planning, OS-level filesystem isolation for the PDF parser, and additional evaluation adapters.

## Current workspace verification

The browser and Windows clients support Google sign-in. Mocked checks cover callback replay, cancellation, partial grants, encrypted storage and revocation. A live Google account and registered OAuth client are still required for provider acceptance.

PDF uploads and watched folders use a shared subprocess with two parser slots per backend process, a 384 MiB memory limit and a 10-second execution timeout. On x64 and ARM64 Linux with Landlock enabled, the worker denies new filesystem reads, writes and execution before parsing document bytes. Kernel ABI 3 or later also denies standalone truncation. The worker retains Python audit restrictions on every platform.

Set `WEDNESDAY_REQUIRE_PDF_ISOLATION=1` in the backend process environment to require OS filesystem isolation. On Linux this requires Landlock. On macOS it enables a deny-all policy through the deprecated Seatbelt API, with native verification configured in CI. Windows workers refuse PDF extraction under this setting because native Windows filesystem isolation is pending. Uploads return HTTP 503 and watched folders show a per-file error when enforcement is unavailable.

Set `WEDNESDAY_REQUIRE_PDF_LANDLOCK=1` to require Linux Landlock specifically. When both flags are set, the Landlock requirement takes precedence. Standard Windows and macOS mode uses subprocess resource limits and Python audit restrictions.

The PDF upload API reports unavailable isolation as HTTP 503, and watched folders show the same cause in their file status. The Windows strict-mode worker returned the expected refusal in a subprocess check. An integration test verifies neither path indexes a rejected PDF. The expansion suite passed 43 tests with one Linux-only check skipped on Windows.

On hosts that support directory-relative opens and `O_NOFOLLOW`, watched files now open through a chain of directory handles, rejecting symlinked parent components at open time. A Linux probe confirmed that a regular file opens and a symlinked parent is denied. Windows still uses the existing identity and containment checks.

The updated Edge acceptance ran a three-case suite through the browser. The downloaded report recorded two passes and one deliberate failure: Python reported line 2 while the saved expectation was line 3. It also verified the calendar UTC case, keyboard activation, report focus restoration and a 390px layout. The fixture server used an explicitly allowed loopback origin.

A fresh Windows WPF build passed the same evaluation cases through the native controls, including the calendar UTC result, Python line mismatch and completion live-region text. Windows CI now runs the isolated expansion check and uploads its receipt. Actual screen-reader speech remains unverified.

The full backend suite passed 87 tests on Windows, with the Linux-only Landlock probe skipped. The Google fixture verified that an ambiguous write is recovered by its deterministic event ID, an unreviewed title change is refused, and retry does not create a second event. Live consent and writes still require an authorized Google test account.

Edge verified phone-width keyboard navigation, evaluation focus and connection status semantics. Windows acceptance verified evaluation completion text and its live-region setting. Actual screen-reader speech remains unverified. Local HTTP measurements for 20 distinct queries across four concurrent workspaces reached a 706 ms median, with an 859 ms maximum. The Windows ZIP above is historical and predates these changes.

## November 26 Windows package acceptance

The Windows ZIP `Wednesday-win-x64-20261126-072859.zip` passed SHA-256 verification and all 47 checked bundled source files matched the workspace. The packaged WPF app passed offline queue, duplicate prevention, calendar approval, multi-task planning, evaluations and watched-folder status against the API bundled in the release and an isolated local data directory. The initial sandboxed smoke stalled inside Python’s Windows asyncio loopback initialization before the API started. The same release passed when run with loopback access. The receipt records programmatic acceptance; visual inspection and screen-reader speech were outside that run.

The subsequent Windows package `Wednesday-win-x64-20261126-075012.zip` passed SHA-256 verification. Its native expansion run also saved an exact ranked retrieval case through the desktop controls and checked the returned source order against the bundled API. The evaluation suite reported three passes and one deliberate Python diagnostic mismatch. This run did not include visual inspection or screen-reader speech.

Edge also passed the ranked retrieval journey against an isolated API. The browser saved the case through the evaluation dialog, ran the four-case suite with keyboard activation, and verified the selected source order in the downloaded report. The run also verified focus restoration and a 390 px viewport without horizontal overflow or page errors. The same journey is now configured in the Linux flagship workflow with Chromium; hosted execution is pending.
