# Memory provenance — October 31, 2026

Implemented backend records and browser/WPF controls preserve source references, scope, expiry and revision history. Existing memories use `source_unavailable`; their origin is not invented. Corrections preserve historical content. Expired/deleted memories are excluded from new retrieval; previous conversation messages remain unchanged.

## Manual acceptance still required

Open the memory workspace in the browser or the desktop continuity window. Create an explicit memory, save it, reload and inspect its source/history. Correct the content and confirm both revisions remain inspectable. Select a conversation message, review it before saving, and inspect the source reference. Choose conversation scope and verify that saving preserves the selected conversation. Set an expiry and verify it is excluded from later retrieval. Export the provenance, then delete the memory and confirm it disappears from future retrieval.

An assistant suggestion is not a verified fact. A retrieved source does not prove it determined an answer. Conflicting revisions should produce an error rather than overwrite a newer edit.

## Automated evidence

- October 31: all 44 backend regression tests passed in isolated temporary data, including three provenance tests covering legacy migration, revision history, restart, stale writes, source ownership, scope, expiry, deletion and API validation.
- WPF debug build passed with zero warnings/errors after correcting two declaration errors and retaining selected memory/conversation IDs across refresh.
- Browser and native interactive acceptance, release packaging and accessibility checks remain pending. A successful build does not establish those results.
