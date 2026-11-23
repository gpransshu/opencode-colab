
#!/usr/bin/env python3
"""
OpenCode Google Colab Bootstrap
================================

PERSISTENT GOOGLE DRIVE STORAGE:
    OpenCode/Environment/
        opencode.json
        AGENTS.md
        agents/
        skills/
        commands/
        plugins/
        mcp/
        auth/

    OpenCode/Sessions/full/
    OpenCode/Backups/
    OpenCode/Runtime/

RUNTIME ONLY:
    MCP gateway token

FEATURES:
    - Persistent global OpenCode configuration
    - Persistent MCP server definitions
    - Hidden gateway token input every new runtime
    - MCP token available in Colab Terminal
    - OpenCode authentication restoration
    - Full session restoration
    - Five-second session export backup
    - Five-second authentication backup
    - Existing configuration preserved during migration
"""

import getpass
import os
import subprocess
from pathlib import Path


# ============================================================
# 1. MOUNT GOOGLE DRIVE
# ============================================================

try:
    from google.colab import drive
except ImportError:
    raise SystemExit("This bootstrap must run inside Google Colab.")

print("\n[MCP/OPENCODE] Mounting Google Drive...")

drive.mount("/content/drive", force_remount=False)

if not Path("/content/drive/MyDrive").is_dir():
    raise SystemExit("Google Drive mount failed.")


# ============================================================
# 2. REQUEST GATEWAY TOKEN
# ============================================================

print("\n[MCP] Gateway authentication")

MCP_GATEWAY_TOKEN = getpass.getpass(
    "Paste your MCP gateway token (input is hidden): "
).strip()

if not MCP_GATEWAY_TOKEN:
    raise SystemExit("Gateway token was not provided.")

if len(MCP_GATEWAY_TOKEN) < 32:
    raise SystemExit("Gateway token appears invalid or too short.")


# ============================================================
# 3. ENVIRONMENT
# ============================================================

ENV = os.environ.copy()

ENV["MCP_GATEWAY_TOKEN"] = MCP_GATEWAY_TOKEN
ENV["OPENCODE_SETUP_ONLY"] = "1"

SETUP_SCRIPT = r'''#!/usr/bin/env bash

set -Eeuo pipefail

# ============================================================
# CONFIGURATION
# ============================================================

DRIVE_ROOT="/content/drive/MyDrive/OpenCode"

CONFIG_DIR="$DRIVE_ROOT/Environment"
SESSIONS_DIR="$DRIVE_ROOT/Sessions/full"
BACKUP_DIR="$DRIVE_ROOT/Backups"
RUNTIME_DIR="$DRIVE_ROOT/Runtime"

PROJECTS_DIR="/content/projects"

LOCAL_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
LOCAL_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/opencode"

BIN_DIR="$HOME/.opencode/bin"
OPENCODE="$BIN_DIR/opencode"

INTERVAL=5

TOKEN_FILE="/content/.opencode-mcp-token"
BASHRC="$HOME/.bashrc"

PUBLIC_DOMAIN="https://starlit-raft-dispersed.ngrok-free.dev"


# ============================================================
# HELPERS
# ============================================================

log() {
    printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

need() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Missing dependency: $1"
        exit 1
    }
}


# ============================================================
# VERIFY DRIVE
# ============================================================

if [[ ! -d /content/drive/MyDrive ]]; then
    echo "Google Drive is not mounted."
    exit 2
fi

need curl
need python3
need git


# ============================================================
# CREATE PERSISTENT DIRECTORIES
# ============================================================

mkdir -p \
    "$CONFIG_DIR" \
    "$SESSIONS_DIR" \
    "$BACKUP_DIR" \
    "$RUNTIME_DIR" \
    "$PROJECTS_DIR" \
    "$CONFIG_DIR/agents" \
    "$CONFIG_DIR/skills" \
    "$CONFIG_DIR/commands" \
    "$CONFIG_DIR/plugins" \
    "$CONFIG_DIR/mcp" \
    "$CONFIG_DIR/auth"


# ============================================================
# SAVE TOKEN IN CURRENT RUNTIME ONLY
# ============================================================

if [[ -z "${MCP_GATEWAY_TOKEN:-}" ]]; then
    echo "MCP_GATEWAY_TOKEN was not supplied."
    exit 4
fi

umask 077

printf '%s' "$MCP_GATEWAY_TOKEN" > "$TOKEN_FILE"

chmod 600 "$TOKEN_FILE"


# ============================================================
# MAKE TOKEN AVAILABLE TO COLAB TERMINAL
# ============================================================

TOKEN_START="# >>> OPENCODE MCP TOKEN >>>"
TOKEN_END="# <<< OPENCODE MCP TOKEN <<<"

python3 - "$BASHRC" "$TOKEN_FILE" "$TOKEN_START" "$TOKEN_END" <<'PYTOKEN'

import sys
from pathlib import Path

bashrc = Path(sys.argv[1])
token_file = sys.argv[2]
start = sys.argv[3]
end = sys.argv[4]

# FIXED: Use triple-double-quotes here.
# The enclosing SETUP_SCRIPT uses triple-single-quotes.

block = f"""{start}
if [ -r "{token_file}" ]; then
    export MCP_GATEWAY_TOKEN="$(cat "{token_file}")"
fi
{end}"""

old = bashrc.read_text() if bashrc.exists() else ""

if start in old and end in old:

    before = old.split(start, 1)[0]
    after = old.split(end, 1)[1]

    updated = before.rstrip() + "\n\n" + block + after

else:

    updated = old.rstrip() + "\n\n" + block + "\n"

bashrc.write_text(updated)

PYTOKEN


# ============================================================
# INSTALL OPENCODE
# ============================================================

log "Checking OpenCode installation"

if [[ ! -x "$OPENCODE" ]]; then

    curl -fsSL https://opencode.ai/v2/install | bash

fi

if [[ ! -x "$OPENCODE" ]]; then

    FOUND="$(command -v opencode || true)"

    if [[ -n "$FOUND" ]]; then
        OPENCODE="$FOUND"
    fi

fi

if [[ ! -x "$OPENCODE" ]]; then
    echo "OpenCode binary could not be found."
    exit 3
fi

export PATH="$(dirname "$OPENCODE"):$PATH"

mkdir -p /usr/local/bin

ln -sf "$OPENCODE" /usr/local/bin/opencode

grep -qxF 'export PATH="/usr/local/bin:$PATH"' "$HOME/.bashrc" 2>/dev/null || \
    printf '\nexport PATH="/usr/local/bin:$PATH"\n' >> "$HOME/.bashrc"

"$OPENCODE" --version


# ============================================================
# MIGRATE GLOBAL CONFIGURATION TO GOOGLE DRIVE
# ============================================================

log "Preparing persistent OpenCode configuration"

mkdir -p "$(dirname "$LOCAL_CONFIG")"

if [[ -d "$LOCAL_CONFIG" && ! -L "$LOCAL_CONFIG" ]]; then

    # Copy existing configuration without overwriting
    # files that already exist on Google Drive.

    cp -an "$LOCAL_CONFIG/." "$CONFIG_DIR/"

    mv "$LOCAL_CONFIG" \
        "${LOCAL_CONFIG}.pre-drive.$(date +%s)"

fi

if [[ -L "$LOCAL_CONFIG" ]]; then
    rm "$LOCAL_CONFIG"
fi

ln -s "$CONFIG_DIR" "$LOCAL_CONFIG"


# ============================================================
# DEFAULT AGENTS FILE
# ============================================================

if [[ ! -f "$CONFIG_DIR/AGENTS.md" ]]; then

cat > "$CONFIG_DIR/AGENTS.md" <<'EOF'
# Personal OpenCode instructions

- Prefer maintainable implementations.
- Explain significant changes before broad edits.
- Run relevant tests after code changes.
- Never expose API keys, passwords or private credentials.
EOF

fi


# ============================================================
# CONFIGURE MCP SERVERS
# ============================================================

log "Configuring persistent MCP servers"

python3 - "$CONFIG_DIR/opencode.json" "$PUBLIC_DOMAIN" <<'PYMCP'

import json
import shutil
import sys

from pathlib import Path
from datetime import datetime

config_file = Path(sys.argv[1])
domain = sys.argv[2]

if config_file.exists():

    backup = config_file.with_name(
        "opencode-before-mcp-" +
        datetime.now().strftime("%Y%m%d-%H%M%S") +
        ".json.bak"
    )

    shutil.copy2(config_file, backup)

    try:

        config = json.loads(
            config_file.read_text(encoding="utf-8")
        )

    except Exception as exc:

        raise SystemExit(
            "Existing opencode.json is not strict JSON. "
            "A backup was created at " + str(backup) +
            ". Convert JSONC comments or trailing commas before rerunning. "
            + str(exc)
        )

else:

    config = {
        "$schema": "https://opencode.ai/config.json"
    }

if not isinstance(config, dict):
    raise SystemExit("OpenCode configuration root must be an object.")

mcp = config.setdefault("mcp", {})

if not isinstance(mcp, dict):
    raise SystemExit("Existing mcp configuration is not an object.")

servers = mcp.setdefault("servers", {})

if not isinstance(servers, dict):
    raise SystemExit("Existing mcp.servers configuration is not an object.")

servers["local-terminal"] = {
    "type": "remote",
    "url": domain + "/terminal/mcp",
    "oauth": False,
    "headers": {
        "Authorization": "Bearer {env:MCP_GATEWAY_TOKEN}"
    }
}

servers["local-playwright"] = {
    "type": "remote",
    "url": domain + "/playwright/mcp",
    "oauth": False,
    "headers": {
        "Authorization": "Bearer {env:MCP_GATEWAY_TOKEN}"
    }
}

temporary = config_file.with_suffix(".json.tmp")

temporary.write_text(
    json.dumps(config, indent=2) + "\n",
    encoding="utf-8"
)

temporary.replace(config_file)

print("Persistent MCP configuration saved.")
print("Configured: local-terminal")
print("Configured: local-playwright")

PYMCP


# ============================================================
# RESTORE AUTHENTICATION
# ============================================================

log "Restoring OpenCode authentication"

mkdir -p "$LOCAL_DATA"
mkdir -p "$CONFIG_DIR/auth"

if [[ -f "$CONFIG_DIR/auth/auth.json" &&
      ! -f "$LOCAL_DATA/auth.json" ]]; then

    cp -p \
        "$CONFIG_DIR/auth/auth.json" \
        "$LOCAL_DATA/auth.json"

fi


# ============================================================
# RESTORE FULL SESSIONS
# ============================================================

log "Restoring full sessions"

RESTORE_LOG="$RUNTIME_DIR/restore-$(date +%Y%m%d-%H%M%S).log"

python3 - "$OPENCODE" "$SESSIONS_DIR" "$RESTORE_LOG" <<'PYRESTORE'

import json
import pathlib
import subprocess
import sys

binary, folder, logpath = sys.argv[1:]

folder = pathlib.Path(folder)

def log(message):

    with open(logpath, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def ids(value):

    output = set()

    def walk(x):

        if isinstance(x, dict):

            sid = x.get("id")

            if isinstance(sid, str) and sid.startswith("ses_"):
                output.add(sid)

            for v in x.values():
                walk(v)

        elif isinstance(x, list):

            for v in x:
                walk(v)

    walk(value)

    return output

try:

    result = subprocess.run(
        [binary, "session", "list", "--format", "json"],
        capture_output=True,
        text=True,
        timeout=90
    )

    current = (
        ids(json.loads(result.stdout or "[]"))
        if result.returncode == 0
        else set()
    )

except Exception:

    current = set()

for file in sorted(folder.glob("*.json")):

    try:

        exported = json.loads(
            file.read_text(encoding="utf-8")
        )

        exported_ids = ids(exported)

        if exported_ids and exported_ids.issubset(current):

            log("Already present; skipped " + file.name)
            continue

        result = subprocess.run(
            [binary, "session", "import", str(file)],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode:

            log(
                "IMPORT FAILED " + file.name +
                ": " + result.stderr[-700:]
            )

        else:

            current |= exported_ids
            log("Imported " + file.name)

    except Exception as exc:

        log("RESTORE ERROR " + file.name + ": " + repr(exc))

PYRESTORE


# ============================================================
# FIVE-SECOND SESSION + AUTH BACKUP WORKER
# ============================================================

log "Creating session backup worker"

cat > /content/opencode-session-backup.py <<'PYBACKUP'

import json
import os
import re
import subprocess
import time
import tempfile
import shutil

from pathlib import Path

OPENCODE = os.environ["OPENCODE_BIN"]

DEST = Path(os.environ["OPENCODE_SESSIONS_DIR"])

LOG = Path(os.environ["OPENCODE_BACKUP_LOG"])

AUTH_SOURCE = Path(os.environ["OPENCODE_AUTH_SOURCE"])

AUTH_BACKUP = Path(os.environ["OPENCODE_AUTH_BACKUP"])

INTERVAL = int(
    os.environ.get("OPENCODE_BACKUP_INTERVAL", "5")
)

DEST.mkdir(parents=True, exist_ok=True)

LOG.parent.mkdir(parents=True, exist_ok=True)

def log(message):

    with LOG.open("a", encoding="utf-8") as f:

        f.write(
            time.strftime("%Y-%m-%d %H:%M:%S ") +
            message + "\n"
        )

def backup_auth():

    if AUTH_SOURCE.is_file():

        AUTH_BACKUP.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        fd, tmp = tempfile.mkstemp(
            prefix="auth",
            suffix=".tmp",
            dir=AUTH_BACKUP.parent
        )

        try:

            with AUTH_SOURCE.open("rb") as src, \
                 os.fdopen(fd, "wb") as dst:

                shutil.copyfileobj(src, dst)

                dst.flush()
                os.fsync(dst.fileno())

            os.chmod(tmp, 0o600)

            os.replace(tmp, AUTH_BACKUP)

        finally:

            if os.path.exists(tmp):
                os.unlink(tmp)

def main():

    log("Session exporter and auth backup started")

    while True:

        try:

            backup_auth()

            result = subprocess.run(
                [
                    OPENCODE,
                    "session",
                    "list",
                    "--format",
                    "json"
                ],
                capture_output=True,
                text=True,
                timeout=90
            )

            if result.returncode:

                raise RuntimeError(
                    "session list: " + result.stderr[-700:]
                )

            data = json.loads(result.stdout or "[]")

            if isinstance(data, dict):

                data = data.get(
                    "sessions",
                    data.get("data", [])
                )

            for item in data if isinstance(data, list) else []:

                sid = (
                    item.get("id", "")
                    if isinstance(item, dict)
                    else ""
                )

                if not re.fullmatch(
                    r"ses_[A-Za-z0-9_-]+",
                    sid
                ):
                    continue

                cwd = (
                    item.get("directory")
                    if isinstance(item, dict)
                    else None
                )

                exported = subprocess.run(
                    [
                        OPENCODE,
                        "session",
                        "export",
                        sid
                    ],
                    cwd=cwd or None,
                    capture_output=True,
                    text=True,
                    timeout=120
                )

                if exported.returncode:

                    log(
                        f"Export failed {sid}: " +
                        exported.stderr[-500:]
                    )

                    continue

                try:

                    json.loads(exported.stdout)

                    target = DEST / (sid + ".json")

                    fd, tmp = tempfile.mkstemp(
                        prefix=sid,
                        suffix=".tmp",
                        dir=DEST
                    )

                    with os.fdopen(
                        fd,
                        "w",
                        encoding="utf-8"
                    ) as out:

                        out.write(exported.stdout)

                        out.flush()
                        os.fsync(out.fileno())

                    os.replace(tmp, target)

                    log("Saved full export " + sid)

                except Exception as exc:

                    log(f"Invalid export {sid}: {exc}")

        except Exception as exc:

            log("Backup cycle error: " + repr(exc))

        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()

PYBACKUP


# ============================================================
# RESTART BACKUP WORKER
# ============================================================

PIDFILE="/content/opencode-session-backup.pid"

if [[ -f "$PIDFILE" ]]; then

    OLD_PID="$(cat "$PIDFILE" || true)"

    if [[ "$OLD_PID" =~ ^[0-9]+$ ]] &&
       kill -0 "$OLD_PID" 2>/dev/null; then

        kill "$OLD_PID" 2>/dev/null || true

    fi

fi

export OPENCODE_BIN="$OPENCODE"

export OPENCODE_SESSIONS_DIR="$SESSIONS_DIR"

export OPENCODE_BACKUP_LOG="$RUNTIME_DIR/session-backup.log"

export OPENCODE_AUTH_SOURCE="$LOCAL_DATA/auth.json"

export OPENCODE_AUTH_BACKUP="$CONFIG_DIR/auth/auth.json"

export OPENCODE_BACKUP_INTERVAL="$INTERVAL"

nohup python3 /content/opencode-session-backup.py \
    >/content/opencode-session-backup.out \
    2>&1 </dev/null &

echo $! > "$PIDFILE"


# ============================================================
# FINISH
# ============================================================

mkdir -p "$PROJECTS_DIR"

cd "$PROJECTS_DIR"

log "OpenCode environment ready"

cat <<EOF

============================================================
OPENCODE COLAB READY
============================================================

Persistent Google Drive:
$DRIVE_ROOT

Global configuration:
$CONFIG_DIR

MCP configuration:
$CONFIG_DIR/opencode.json

Full sessions:
$SESSIONS_DIR

Authentication backup:
$CONFIG_DIR/auth/auth.json

Projects:
$PROJECTS_DIR

MCP servers:
- local-terminal
- local-playwright

Gateway token:
Current runtime only.

Session/auth backup:
Every ${INTERVAL} seconds.

Open Colab Terminal and type:

    source ~/.bashrc
    opencode

============================================================

EOF

if [[ "${OPENCODE_SETUP_ONLY:-0}" == "1" ]]; then

    log "Setup complete. Open Colab Terminal and run opencode."

    exit 0

fi

exec "$OPENCODE"

'''


# ============================================================
# 4. EXECUTE BOOTSTRAP
# ============================================================

setup_file = Path("/content/opencode_colab_setup.sh")

setup_file.write_text(
    SETUP_SCRIPT,
    encoding="utf-8"
)

setup_file.chmod(0o700)

print("\n[OPENCODE] Running bootstrap...")

subprocess.run(
    ["bash", str(setup_file)],
    check=True,
    env=ENV
)

print("\n==============================================")
print(" OPENCODE COLAB BOOTSTRAP FINISHED")
print("==============================================")
print("Google Drive configuration: persistent")
print("MCP definitions: persistent")
print("Gateway token: runtime only")
print("Session restoration: enabled")
print("Five-second backups: enabled")
print("\nOpen Colab Terminal and execute:")
print("opencode")
