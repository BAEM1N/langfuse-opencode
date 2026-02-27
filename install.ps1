$ErrorActionPreference = "Stop"

$PROJECT_NAME = "langfuse-opencode"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$OPENCODE_DIR = Join-Path $env:USERPROFILE ".config/opencode"
$PLUGINS_DIR = Join-Path $OPENCODE_DIR "plugins"
$HOOKS_DIR = Join-Path $OPENCODE_DIR "hooks"
$STATE_DIR = Join-Path $OPENCODE_DIR "state/langfuse"
$PLUGIN_SRC = Join-Path $SCRIPT_DIR "langfuse_plugin.js"
$HOOK_SRC = Join-Path $SCRIPT_DIR "langfuse_hook.py"
$PLUGIN_DST = Join-Path $PLUGINS_DIR "langfuse_plugin.js"
$HOOK_DST = Join-Path $HOOKS_DIR "langfuse_hook.py"
$ENV_FILE = Join-Path $OPENCODE_DIR ".env"
$CONFIG_FILE = Join-Path $OPENCODE_DIR "opencode.json"

function Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "[ERROR] $msg" -ForegroundColor Red }
function Step($msg) { Write-Host "[STEP] $msg" -ForegroundColor Cyan }

Write-Host ""
Write-Host "=========================================="
Write-Host "  $PROJECT_NAME installer"
Write-Host "=========================================="
Write-Host ""

Step "Checking Python..."
$py = $null
foreach ($cmd in @("python", "python3")) {
  try { & $cmd --version 2>$null | Out-Null; $py = $cmd; break } catch {}
}
if (-not $py) { Err "Python 3.8+ is required."; exit 1 }

$major = & $py -c "import sys; print(sys.version_info.major)"
$minor = & $py -c "import sys; print(sys.version_info.minor)"
if ([int]$major -lt 3 -or ([int]$major -eq 3 -and [int]$minor -lt 8)) {
  Err "Python 3.8+ is required."; exit 1
}
Info "Found $py"

Step "Installing langfuse SDK..."
& $py -m pip install --quiet --upgrade langfuse
Info "langfuse SDK installed."

Step "Installing plugin + hook files..."
New-Item -ItemType Directory -Force -Path $PLUGINS_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $HOOKS_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $STATE_DIR | Out-Null
Copy-Item $PLUGIN_SRC $PLUGIN_DST -Force
Copy-Item $HOOK_SRC $HOOK_DST -Force
Info "Plugin: $PLUGIN_DST"
Info "Hook:   $HOOK_DST"

Write-Host ""
Step "Configuring Langfuse credentials..."
$pk = Read-Host "  Langfuse Public Key"
$sk = Read-Host "  Langfuse Secret Key" -AsSecureString
$skPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sk)
)
$url = Read-Host "  Langfuse Base URL [https://cloud.langfuse.com]"
if (-not $url) { $url = "https://cloud.langfuse.com" }
$uid = Read-Host "  User ID [opencode-user]"
if (-not $uid) { $uid = "opencode-user" }

if (-not $pk -or -not $skPlain) {
  Err "Public and Secret keys are required."; exit 1
}

Step "Writing credentials to $ENV_FILE..."
New-Item -ItemType Directory -Force -Path $OPENCODE_DIR | Out-Null
@"
# Langfuse credentials for langfuse-opencode
TRACE_TO_LANGFUSE=true
LANGFUSE_PUBLIC_KEY=$pk
LANGFUSE_SECRET_KEY=$skPlain
LANGFUSE_BASE_URL=$url
LANGFUSE_USER_ID=$uid
OPENCODE_LANGFUSE_LOG_LEVEL=INFO
OPENCODE_LANGFUSE_MAX_MESSAGE_EVENTS_PER_MESSAGE=30
"@ | Set-Content -Encoding utf8 $ENV_FILE
Info "Credentials written."

Step "Merging plugin registration into $CONFIG_FILE..."
& $py - $CONFIG_FILE $PLUGIN_DST @'
import json
import os
import sys

config_path, plugin_path = sys.argv[1:3]
plugin_uri = f"file://{plugin_path}"

if os.path.exists(config_path):
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
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

seen = set()
unique = []
for p in plugins:
    if isinstance(p, str) and p not in seen:
        seen.add(p)
        unique.append(p)

config['plugin'] = unique

with open(config_path, 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
    f.write('\n')

print(f"  Registered plugin: {plugin_path}")
print(f"  Total plugins: {len(unique)}")
'@

Step "Verifying installation..."
try { & $py -c "import langfuse; print('langfuse SDK: OK')" } catch { Warn "langfuse import failed" }
try { & $py -m py_compile $HOOK_DST; Info "Hook syntax: OK" } catch { Warn "Hook syntax check failed" }
try { node --check $PLUGIN_DST | Out-Null; Info "Plugin syntax: OK" } catch { Warn "Node check failed" }

Write-Host ""
Write-Host "=========================================="
Write-Host "  Installation complete!"
Write-Host "=========================================="
Write-Host ""
Info "OpenCode events will now be forwarded to Langfuse."
Info "Config: $CONFIG_FILE"
Info "Env:    $ENV_FILE"
Info "State:  $STATE_DIR"
