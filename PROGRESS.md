# Progress (2026-02-25)

## Completed
- OpenCode plugin + hook integration completed.
- OpenRouter free-model run verified end-to-end.
- Turn metadata enriched with message-level event history.
- Reliability patch applied:
  - plugin forwarding switched to synchronous hook invocation
  - hook now guards out-of-order updates and idle-flushes pending assistant turns

## Verified
- Hook/plugin syntax checks passed.
- `session.created` / `turn` / `session.idle` traces confirmed in Langfuse.
- Metadata checks confirmed (`session_id`, `user_id`, `hostname`, `message_events`).
- Regression check: previously missing final assistant turns were backfilled and new test session showed no missing turn IDs.

## Next
- Optional: add an opt-in delta-level capture mode for deep stream debugging.
