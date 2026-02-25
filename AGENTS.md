# Agent Setup Guide

This repository provides OpenCode -> Langfuse integration.

## Scope

- Plugin: `langfuse_plugin.js`
- Hook: `langfuse_hook.py`
- Installers: `install.sh`, `install.ps1`

## Setup rules for agents

1. Keep integration fail-open (never block OpenCode event flow).
2. Respect `TRACE_TO_LANGFUSE=true` gate.
3. Preserve user config when editing `~/.config/opencode/opencode.json`:
   - merge into `plugin` array
   - do not overwrite unrelated keys
4. Keep credentials in `~/.config/opencode/.env`.
5. Maintain turn reconstruction behavior using:
   - `message.updated`
   - `message.part.updated`
6. Keep lifecycle tracing for:
   - `session.created`
   - `session.idle`
   - `session.error`
   - `session.compacted`
