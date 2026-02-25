# langfuse-opencode

[English](README.md) | [한국어](README.ko.md)

Automatic [Langfuse](https://langfuse.com) tracing for OpenCode using local plugin hooks.
This project forwards OpenCode `event` stream payloads to a Python hook and reconstructs assistant turns into Langfuse traces.

## Status (February 25, 2026)

- ✅ OpenCode + OpenRouter free-model run verified end-to-end
- ✅ `session.created` / `turn` / `session.idle` traces confirmed in Langfuse
- ✅ Turn metadata includes `session_id`, `user_id`, `hostname`, parts, and message-level history
- Progress docs: [English](./PROGRESS.md) | [한국어](./PROGRESS.ko.md)

## Features

- Event-hook based integration (`langfuse_plugin.js` -> `langfuse_hook.py`)
- Fail-open design (never blocks OpenCode)
- Reliable event forwarding (sync hook invocation to reduce end-of-session event loss)
- Runtime gate: `TRACE_TO_LANGFUSE=true`
- Supports:
  - `LANGFUSE_PUBLIC_KEY`
  - `LANGFUSE_SECRET_KEY`
  - `LANGFUSE_BASE_URL`
  - `LANGFUSE_USER_ID`
  - `OPENCODE_LANGFUSE_LOG_LEVEL` (`DEBUG|INFO|WARN|ERROR`)
- Turn reconstruction for assistant output from:
  - `message.updated`
  - `message.part.updated`
- Lifecycle traces for:
  - `session.created`
  - `session.idle`
  - `session.error`
  - `session.compacted`
- Metadata tags include `opencode` and `product=reconstruction`
- Turn metadata includes `session_id`, `user_id`, `hostname`, and per-turn user/assistant parts
- Turn metadata also includes per-message history from `message.updated` events (`message_events.user`, `message_events.assistant`)

## Quick Start

```bash
git clone https://github.com/BAEM1N/langfuse-opencode.git
cd langfuse-opencode
bash install.sh
```

Windows PowerShell:

```powershell
git clone https://github.com/BAEM1N/langfuse-opencode.git
cd langfuse-opencode
.\install.ps1
```

## Manual Setup

1. Install SDK:

```bash
python3 -m pip install --upgrade langfuse
```

2. Install plugin + hook:

```bash
mkdir -p ~/.config/opencode/plugins ~/.config/opencode/hooks ~/.config/opencode/state/langfuse
cp langfuse_plugin.js ~/.config/opencode/plugins/langfuse_plugin.js
cp langfuse_hook.py ~/.config/opencode/hooks/langfuse_hook.py
chmod +x ~/.config/opencode/hooks/langfuse_hook.py
```

3. Create `~/.config/opencode/.env`:

```env
TRACE_TO_LANGFUSE=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_USER_ID=opencode-user
OPENCODE_LANGFUSE_LOG_LEVEL=INFO
OPENCODE_LANGFUSE_MAX_MESSAGE_EVENTS_PER_MESSAGE=30
```

4. Merge plugin registration into `~/.config/opencode/opencode.json`:

```json
{
  "plugin": [
    "file:///Users/<you>/.config/opencode/plugins/langfuse_plugin.js"
  ]
}
```

> Keep existing `opencode.json` values and append this plugin path only if missing.

## Validation

```bash
python3 -m py_compile langfuse_hook.py
node --check langfuse_plugin.js
```

## Files

- `langfuse_plugin.js`: OpenCode local plugin (`event` hook)
- `langfuse_hook.py`: Python trace emitter + stateful reconstruction
- `install.sh`, `install.ps1`: interactive installers with merge-safe config update

## License

MIT
