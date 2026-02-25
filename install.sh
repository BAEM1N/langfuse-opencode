#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="langfuse-opencode"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OPENCODE_DIR="$HOME/.config/opencode"
PLUGINS_DIR="$OPENCODE_DIR/plugins"
HOOKS_DIR="$OPENCODE_DIR/hooks"
STATE_DIR="$OPENCODE_DIR/state/langfuse"
PLUGIN_SRC="$SCRIPT_DIR/langfuse_plugin.js"
HOOK_SRC="$SCRIPT_DIR/langfuse_hook.py"
PLUGIN_DST="$PLUGINS_DIR/langfuse_plugin.js"
HOOK_DST="$HOOKS_DIR/langfuse_hook.py"
ENV_FILE="$OPENCODE_DIR/.env"
CONFIG_FILE="$OPENCODE_DIR/opencode.json"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  ${PROJECT_NAME} installer               ║"
echo "╚══════════════════════════════════════════╝"
echo ""

step "Checking Python..."
PYTHON=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  error "Python 3.8+ is required."
  exit 1
fi

PY_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$($PYTHON -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$($PYTHON -c 'import sys; print(sys.version_info.minor)')
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 8 ]]; }; then
  error "Python 3.8+ required, found $PY_VERSION"
  exit 1
fi
info "Found $PYTHON ($PY_VERSION)"

step "Installing langfuse Python SDK..."
$PYTHON -m pip install --quiet --upgrade langfuse
info "langfuse SDK installed."

step "Installing plugin + hook files..."
mkdir -p "$PLUGINS_DIR" "$HOOKS_DIR" "$STATE_DIR"
cp "$PLUGIN_SRC" "$PLUGIN_DST"
cp "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_DST"
info "Plugin: $PLUGIN_DST"
info "Hook:   $HOOK_DST"

echo ""
step "Configuring Langfuse credentials..."
read -rp "  Langfuse Public Key  : " LF_PUBLIC_KEY
read -rsp "  Langfuse Secret Key  : " LF_SECRET_KEY
echo ""
read -rp "  Langfuse Base URL    [https://cloud.langfuse.com]: " LF_BASE_URL
LF_BASE_URL="${LF_BASE_URL:-https://cloud.langfuse.com}"
read -rp "  User ID              [opencode-user]: " LF_USER_ID
LF_USER_ID="${LF_USER_ID:-opencode-user}"

if [[ -z "$LF_PUBLIC_KEY" || -z "$LF_SECRET_KEY" ]]; then
  error "Public and Secret keys are required."
  exit 1
fi

step "Writing credentials to $ENV_FILE..."
mkdir -p "$OPENCODE_DIR"
cat > "$ENV_FILE" <<ENVEOF
# Langfuse credentials for langfuse-opencode
TRACE_TO_LANGFUSE=true
LANGFUSE_PUBLIC_KEY=${LF_PUBLIC_KEY}
LANGFUSE_SECRET_KEY=${LF_SECRET_KEY}
LANGFUSE_BASE_URL=${LF_BASE_URL}
LANGFUSE_USER_ID=${LF_USER_ID}
OPENCODE_LANGFUSE_LOG_LEVEL=INFO
OPENCODE_LANGFUSE_MAX_MESSAGE_EVENTS_PER_MESSAGE=30
ENVEOF
info "Credentials written."

step "Merging plugin registration into $CONFIG_FILE..."
$PYTHON - "$CONFIG_FILE" "$PLUGIN_DST" <<'PYEOF'
import json
import os
import sys

config_path = sys.argv[1]
plugin_path = sys.argv[2]
plugin_uri = f"file://{plugin_path}"

if os.path.exists(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        try:
            config = json.load(f)
            if not isinstance(config, dict):
                config = {}
        except Exception:
            config = {}
else:
    config = {}

plugins = config.get('plugin')
if not isinstance(plugins, list):
    plugins = []

if plugin_uri not in plugins and plugin_path not in plugins:
    plugins.append(plugin_uri)

# Deduplicate while preserving order
seen = set()
unique = []
for p in plugins:
    if not isinstance(p, str):
        continue
    if p in seen:
        continue
    seen.add(p)
    unique.append(p)

config['plugin'] = unique

with open(config_path, 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
    f.write('\n')

print(f"  Registered plugin: {plugin_path}")
print(f"  Total plugins: {len(unique)}")
PYEOF

step "Verifying installation..."
$PYTHON -c "import langfuse; print('langfuse SDK: OK')" || warn "langfuse import failed"
$PYTHON -m py_compile "$HOOK_DST" && info "Hook syntax: OK"
node --check "$PLUGIN_DST" >/dev/null 2>&1 && info "Plugin syntax: OK" || warn "Node check failed"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Installation complete!                  ║"
echo "╚══════════════════════════════════════════╝"
echo ""
info "OpenCode events will now be forwarded to Langfuse."
info "Config: $CONFIG_FILE"
info "Env:    $ENV_FILE"
info "State:  $STATE_DIR"
