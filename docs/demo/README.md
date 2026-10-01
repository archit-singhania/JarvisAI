# Wednesday demonstration provenance

`wednesday-acceptance.webm` records the actual browser acceptance against an isolated local workspace. Memory/document names, source content and future reminder dates are fixture inputs. The recording exercises persistence, ownership, workflow receipts, export, preferences and mobile layouts. It deliberately shows a missing model as an error; it is not evidence of live inference or physical microphone operation.

Reproduce with a Wednesday service on port 8006 using a private temporary data directory and an allowed `http://127.0.0.1:8006` origin. Run `RECORD_DEMO=1 node tests/browser-smoke.cjs` from `aurascript` with Playwright/Chrome available. No real account credentials are embedded.
