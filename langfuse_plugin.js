import fs from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';

const ALLOWED_EVENTS = new Set([
  'session.created',
  'session.idle',
  'session.error',
  'session.compacted',
  'message.updated',
  'message.part.updated',
]);

function resolveHookPath() {
  if (process.env.OPENCODE_LANGFUSE_HOOK_PATH) {
    return process.env.OPENCODE_LANGFUSE_HOOK_PATH;
  }
  return path.join(process.env.HOME || '~', '.config', 'opencode', 'hooks', 'langfuse_hook.py');
}

function debugDump(payload) {
  try {
    const enabled = String(process.env.OPENCODE_LANGFUSE_PLUGIN_DEBUG || '').toLowerCase();
    if (!['1', 'true', 'yes', 'on'].includes(enabled)) return;
    const stateDir = path.join(process.env.HOME || '~', '.config', 'opencode', 'state', 'langfuse');
    fs.mkdirSync(stateDir, { recursive: true });
    fs.appendFileSync(
      path.join(stateDir, 'plugin_events.ndjson'),
      JSON.stringify({ ts: new Date().toISOString(), payload }) + '\n',
      'utf8',
    );
  } catch {
    // fail-open
  }
}

function forwardToHook(payload) {
  try {
    debugDump(payload);
    spawnSync('python3', [resolveHookPath()], {
      input: JSON.stringify(payload || {}),
      stdio: ['pipe', 'ignore', 'ignore'],
      env: process.env,
      timeout: 5000,
    });
  } catch {
    // fail-open: never block OpenCode
  }
}

export const LangfuseOpenCodePlugin = async () => {
  return {
    event: async ({ event }) => {
      const eventType = String(event?.type || '').toLowerCase();
      if (!ALLOWED_EVENTS.has(eventType)) {
        return;
      }
      forwardToHook({
        source: 'opencode-plugin',
        captured_at: new Date().toISOString(),
        event,
      });
    },
  };
};
