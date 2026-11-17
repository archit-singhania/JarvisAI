# Wednesday local expansion

Implementation and acceptance record: November 17, 2026. These four additions now have backend, browser and WPF source implementations. This is not a claim that every release gate is complete.

## Offline operations

Open **Local workspace** in the browser or **Continuity studio → Local edits** in WPF. Save a note, conversation draft, existing memory correction or local reminder. Browser queue entries and unfinished form values are stored per workspace in local storage; desktop entries are written atomically to a per-workspace JSON queue. Desktop users load their authenticated workspace identity before going offline.

Disconnect after opening the application, save an operation, reconnect and synchronize. Expect one resulting revision even if the response was lost and the operation is retried. Browser reconnect attempts safe synchronization automatically. WPF synchronization is explicit. Pending, syncing, failed, completed and conflicted browser states are visible. A conflict shows your submitted text and the saved version; explicitly choose the revision to overwrite. In WPF inspect both versions in the result, then create a new operation with the current revision. Completed entries can be removed locally.

Notes enter local knowledge retrieval. Drafts are saved drafts, not sent messages. Memory corrections preserve original provenance and revision history; use the existing memory inspector to obtain the ID/version. Reminders require an explicit UTC offset. Commands, host actions and external writes are rejected by the queue contract. Workspace identity is checked again before synchronization. The browser must already be loaded to work during a service outage; an offline-installable service-worker shell is not included. Desktop reopening while disconnected still requires identity-loading improvements.

## Calendar planning

Import an `.ics` file, inspect events, enter a working-window start/end with UTC offsets and a duration, and request a proposal. Inspect the exact proposed interval before approving a local event or a Google write. Existing events block time; calendar changes invalidate unapplied proposals. Retries use stable event IDs. Export and reopen the `.ics` file to inspect real saved events.

Calendar-file import supports UTC and IANA TZID timed events, folded lines and escaped summaries. Ambiguous/nonexistent daylight-saving times are rejected; convert them to UTC explicitly. Recurring and all-day **file** imports currently require conversion/expansion. Export folds UTF-8 lines. Working windows are at most seven days and blocks are 5–480 minutes. Multi-task priority scheduling and recurring working-hour presets remain follow-up work.

### Optional Google adapter

Set these **process environment variables** on the local backend host, outside Git:

- `WEDNESDAY_GOOGLE_OWNER`: the exact authorized workspace owner ID.
- `WEDNESDAY_GOOGLE_ACCOUNT_LABEL`: a recognizable account label.
- Either `WEDNESDAY_GOOGLE_ACCESS_TOKEN`, or all of `WEDNESDAY_GOOGLE_REFRESH_TOKEN`, `WEDNESDAY_GOOGLE_CLIENT_ID`, `WEDNESDAY_GOOGLE_CLIENT_SECRET`.

Provision OAuth authorization outside this application; the app does not currently provide an OAuth consent/sign-in screen. Tokens never enter exported records or browser state. Select a calendar from the configured account, then synchronize before proposing time blocks. The adapter persists checkpoints, handles pagination and HTTP 410 full-resync recovery, and imports deleted events. Sync is bounded to 50 pages of 1000 events. Live-account behavior remains unverified.

Approved writes re-synchronize first, compare the reviewed calendar snapshot, use a stable Google event ID and recover uncertain responses. No attendees are added and `sendUpdates=none` is sent. Calendar changes after the last read remain an external-service race; the adapter is not a distributed scheduling lock. Disconnect stops subsequent synchronization and removes imported Google events from local planning. It does not delete external events or revoke the separately provisioned OAuth grant.

Implementation references: [Google synchronization](https://developers.google.com/workspace/calendar/api/guides/sync) and [event creation](https://developers.google.com/workspace/calendar/api/guides/create-events).

## Watched document folders

On the host, set `WEDNESDAY_WATCH_OWNER` to the authorized workspace ID and `WEDNESDAY_WATCH_ROOTS` to exact approved absolute directories separated by the operating system path separator (`;` on Windows). These are process environment variables. In WPF choose a directory, enter optional exclusion globs and explicitly approve indexing. The directory must exactly match a configured root. Hosted demonstration mode denies registration.

The browser exposes status and stop controls; it has no folder picker. TXT, Markdown and PDF files are scanned every 30 seconds. Hashes prevent re-extracting unchanged files. Changed files replace retrieval content, deleted/excluded files leave retrieval, and loss of root authorization withholds indexed content. Failed extraction is visible per file. Stop removes indexed copies without modifying originals.

Budgets: 2000 visited files, 4 MiB per file, 32 MiB read per scan, 100 PDF pages, 200,000 extracted characters per file and 10 million new extracted characters per scan. Symlinks and escaping paths are rejected. Source files are never edited. Operator-controlled roots must not be writable by hostile users: path replacement during a filesystem read is not protected by an OS-level directory handle. Extraction runs in a background thread; hard subprocess memory/time isolation and per-file job cancellation remain gaps.

## Evaluation dashboard

Save a deliberately redacted local query with expected owned source IDs, or a Python syntax example with its expected error state. Run the case and inspect/download its report. Deleting a source should turn a formerly passing retrieval case into a failed case. Python is parsed without executing it. Cases and results survive restart and are scoped to their workspace.

Reports include case hashes, formula/configuration versions, source hashes, elapsed time, failures and a synthetic waiting-task probe through the real `Runtime.interrupt` method. That probe does **not** establish cloud-provider or audio-queue cancellation performance. No model requests, host commands or external writes are replayed. Subjective/model-graded evaluation, richer tool adapters, latency distributions and configuration comparison charts remain open.

## Evidence and release gaps

The final backend regression run passed 52 tests. WPF Debug build passed with zero warnings/errors. An Edge journey verified offline save/reconnect/reload, local calendar approval, evaluation execution and a 390px layout without horizontal overflow or JavaScript errors. Google tests use mocked responses, not a live account. Existing test tooling emits a Starlette/httpx deprecation warning.

Still required: interactive WPF journeys, updated packaged installation, full keyboard/screen-reader and light/dark visual review, physical-device checks, long-running performance/recovery profiling and live Google consent/token tests. No deployment, paid subscription, signing or automatic update execution was performed.
