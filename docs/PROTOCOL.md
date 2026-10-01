# Owned HTTP and realtime contract

The running service publishes HTTP OpenAPI at `/openapi.json` and an interactive reference at `/docs`. All `/api` operations after session bootstrap require the owned cookie or a Bearer credential. Writes from foreign browser origins are rejected. Native sockets can use a Bearer header; AuraScript uses `wednesday.v1` plus `token.<opaque credential>` WebSocket subprotocols.

Connect to `/ws?conversation_id=<owned id>`. Omitting the ID creates a conversation. The first event returns saved history and preferences. All service events include:

```json
{"version":1,"type":"stream_chunk","session_id":"opaque","conversation_id":"opaque","turn_id":"opaque","sequence":2,"content":"A token"}
```

Sequence numbers increase per connection. `audio_sequence` increases per turn, starting at zero. `audio_format` is `mp3` or `wav`; `audio_b64` encodes the full playable chunk. Clients discard audio/content for interrupted turn IDs. Session, reminder, cleared, context and wake control events have a null turn ID and remain deliverable after interruption. Reconnect restores persisted history; it does not claim to revive an aborted provider computation.

| Client message | Operation |
|---|---|
| `text` + `content`, optional `tts` | Start a new turn, cancelling the prior active task |
| `audio` + `audio_b64`, `language`, `tts` | Transcribe finalized audio, then respond |
| `interrupt` | Cancel active generation and ordered speech |
| `clear` | Begin a new durable conversation and clear selected-file context |
| `code_context` + `file`, `content` | Set explicitly selected context; empty content clears it |
| `image`/`screen` + `image_b64`, `prompt` | Analyze a user-selected image as an interruptible task |
| `reminder_ack` + `reminder_id` | Mark an owned reminder delivered |

Server events: `session`, `stream_start`, `stream_chunk`, `audio_chunk`, `stream_end`, `transcript`, `stt_start`, `interrupted`, `cleared`, `context_updated`, `reminder`, `wake_detected`, `error`, `stt_error`, `speech_unavailable`. Errors carry a user-readable content and stable error code where applicable. Payload bounds: text/code 12,000 characters, audio 10 MB, selected image 8 MB, document 10 MB. Unsupported inputs fail explicitly.

Fixtures are in `fixtures/events.v1.json`; ordering, cancellation and control independence have automated tests. REST operations expose owned conversations, document ingestion, memories, reminders, preferences/personas, workflows, tool receipts, provider capabilities, workspace export and language diagnostics. Reminders accept offset-aware ISO dates or local ISO dates with an IANA timezone; nonexistent DST clock times are rejected, and the resolved UTC instant remains fixed across polling.
