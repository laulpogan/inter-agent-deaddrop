#!/usr/bin/env bash
# inter-agent-deaddrop one-click bootstrap.
#
# Two modes:
#   init  — create a new wire repo, invite peer, install your own daemon
#   join  — accept invite, add your pubkey, install your own daemon
#
# Usage:
#   bash install.sh init --my-handle <h> --peer-github <user> --peer-handle <h> [--repo-name <name>]
#   bash install.sh join <wire-repo-url> --my-handle <h> --peer-handle <h>
#
# Prereqs:
#   - gh CLI authed (`gh auth status`)
#   - python3 + pip
#   - git
#   - curl
#
# What it does:
#   init mode (creating party):
#     1. Verifies prereqs
#     2. Creates private repo via gh
#     3. Generates Ed25519 keypair
#     4. Bootstraps _coordination/ with PROTOCOL.md, tiers.json, empty JSONLs, trust.json (with your pubkey)
#     5. Initial commit + push
#     6. Invites peer's GitHub user as collaborator
#     7. Installs systemd-user / launchd daemon
#     8. Prints share-URL for the peer
#
#   join mode (joining party):
#     1. Verifies prereqs
#     2. Accepts wire-repo invitation
#     3. Clones with HTTPS+token (uses gh CLI)
#     4. Generates Ed25519 keypair
#     5. Adds your pubkey to existing trust.json, commits + pushes
#     6. Configures and installs daemon
#     7. Sends first signed heartbeat
#     8. Prints status

set -euo pipefail

usage() {
  sed -n '/^#/,/^$/p' "$0" | sed 's/^# \?//' | head -40
  exit 2
}

die() { echo "FATAL: $*" >&2; exit 1; }
log() { echo "[install] $*" >&2; }

[ "${1:-}" = "" ] && usage

MODE="$1"; shift

# Parse common flags
MY_HANDLE=""
PEER_HANDLE=""
PEER_GITHUB=""
WIRE_URL=""
REPO_NAME=""

while [ $# -gt 0 ]; do
  case "$1" in
    --my-handle) MY_HANDLE="$2"; shift 2;;
    --peer-handle) PEER_HANDLE="$2"; shift 2;;
    --peer-github) PEER_GITHUB="$2"; shift 2;;
    --repo-name) REPO_NAME="$2"; shift 2;;
    https://github.com/*) WIRE_URL="$1"; shift;;
    *) echo "unknown arg: $1"; usage;;
  esac
done

# ===== prereq checks =====
need() { command -v "$1" >/dev/null 2>&1 || die "missing: $1"; }
need gh
need python3
need git
need curl

gh auth status >/dev/null 2>&1 || die "gh not authed (run \`gh auth login\`)"
GH_USER=$(gh api user --jq .login)
log "gh authed as: $GH_USER"

python3 -c "import nacl" >/dev/null 2>&1 || python3 -c "import cryptography" >/dev/null 2>&1 || {
  log "installing pynacl (Ed25519 backend)"
  python3 -m pip install --user --break-system-packages pynacl >/dev/null 2>&1 || \
    die "could not install pynacl; install manually: pip install pynacl"
}

# ===== validate handle format =====
validate_handle() {
  local h="$1"
  echo "$h" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' || \
    die "handle '$h' must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}"
}

# ===== detect repo locations =====
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEADDROP_DIR=""
if [ -f "$SCRIPT_DIR/PROTOCOL.md" ]; then
  DEADDROP_DIR="$SCRIPT_DIR"
elif [ -d "$HOME/Source/inter-agent-deaddrop" ]; then
  DEADDROP_DIR="$HOME/Source/inter-agent-deaddrop"
else
  log "cloning inter-agent-deaddrop reference repo"
  git clone --quiet https://github.com/laulpogan/inter-agent-deaddrop.git "$HOME/Source/inter-agent-deaddrop"
  DEADDROP_DIR="$HOME/Source/inter-agent-deaddrop"
fi

KEY_DIR="$HOME/.config/inter-agent-deaddrop"
mkdir -p "$KEY_DIR" && chmod 700 "$KEY_DIR"

# ===== keypair gen helper =====
gen_keypair() {
  local handle="$1"
  if [ -f "$KEY_DIR/$handle.key" ] && [ -f "$KEY_DIR/$handle.pub.json" ]; then
    log "keypair already exists at $KEY_DIR/$handle.{key,pub.json}"
    return 0
  fi
  python3 "$DEADDROP_DIR/v3/keygen.py" "$handle" --out-dir "$KEY_DIR" >/dev/null
  log "generated keypair: $KEY_DIR/$handle.{key,pub.json}"
}

# ===== install daemon helper =====
install_daemon() {
  local wire_dir="$1"
  local my_handle="$2"
  local peer_handle="$3"

  # daemon code
  cp "$DEADDROP_DIR/examples/git-as-wire/wire-daemon.py" "$wire_dir/.wire-daemon.py"
  chmod +x "$wire_dir/.wire-daemon.py"

  # config
  cat > "$wire_dir/.wire-config.json" <<JSON
{
  "agent": "$my_handle",
  "outbound_file": "_coordination/${my_handle}_to_${peer_handle}.jsonl",
  "inbound_file": "_coordination/${peer_handle}_to_${my_handle}.jsonl",
  "heartbeat_cadence_sec": 90,
  "fast_poll_sec": 2,
  "remote": "origin",
  "branch": "main"
}
JSON

  # service unit
  case "$(uname -s)" in
    Linux*)
      mkdir -p "$HOME/.config/systemd/user"
      cat > "$HOME/.config/systemd/user/wire-daemon.service" <<UNIT
[Unit]
Description=inter-agent-deaddrop wire daemon ($my_handle)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$wire_dir
ExecStart=/usr/bin/env python3 $wire_dir/.wire-daemon.py $wire_dir
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
UNIT
      systemctl --user daemon-reload
      systemctl --user enable --now wire-daemon
      sleep 2
      log "daemon status: $(systemctl --user is-active wire-daemon)"
      ;;
    Darwin*)
      local plist="$HOME/Library/LaunchAgents/io.${my_handle}.wire-daemon.plist"
      cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>io.${my_handle}.wire-daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>python3</string>
    <string>$wire_dir/.wire-daemon.py</string>
    <string>$wire_dir</string>
  </array>
  <key>WorkingDirectory</key><string>$wire_dir</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>$wire_dir/.wire-daemon.log</string>
  <key>StandardErrorPath</key><string>$wire_dir/.wire-daemon.log</string>
</dict>
</plist>
PLIST
      launchctl unload "$plist" 2>/dev/null || true
      launchctl load "$plist"
      sleep 2
      log "launchd loaded: $(launchctl list | grep wire-daemon || echo 'NOT FOUND')"
      ;;
    *)
      log "WARN: no auto-daemon install for $(uname -s); run \`python3 $wire_dir/.wire-daemon.py $wire_dir\` manually"
      ;;
  esac
}

# ===== INIT MODE =====
init_mode() {
  [ -z "$MY_HANDLE" ] && die "init: --my-handle required"
  [ -z "$PEER_HANDLE" ] && die "init: --peer-handle required"
  [ -z "$PEER_GITHUB" ] && die "init: --peer-github required (peer's GitHub username)"
  validate_handle "$MY_HANDLE"
  validate_handle "$PEER_HANDLE"
  [ -z "$REPO_NAME" ] && REPO_NAME="${MY_HANDLE}-${PEER_HANDLE}-wire"

  log "creating private repo: $GH_USER/$REPO_NAME"
  gh repo create "$GH_USER/$REPO_NAME" --private \
    --description "inter-agent-deaddrop wire ($MY_HANDLE <-> $PEER_HANDLE)" \
    >/dev/null
  log "repo created"

  WIRE_DIR="$HOME/wire/$REPO_NAME"
  rm -rf "$WIRE_DIR" && mkdir -p "$(dirname "$WIRE_DIR")"
  TOKEN=$(gh auth token)
  git clone --quiet "https://${GH_USER}:${TOKEN}@github.com/${GH_USER}/${REPO_NAME}.git" "$WIRE_DIR"
  cd "$WIRE_DIR"

  # bootstrap structure
  mkdir -p _coordination/archive
  cp "$DEADDROP_DIR/PROTOCOL.md" _coordination/
  cp "$DEADDROP_DIR/tiers.json" _coordination/
  touch "_coordination/${MY_HANDLE}_to_${PEER_HANDLE}.jsonl"
  touch "_coordination/${PEER_HANDLE}_to_${MY_HANDLE}.jsonl"
  touch _coordination/decisions.jsonl
  touch _coordination/incident_log.jsonl

  # keypair
  gen_keypair "$MY_HANDLE"
  MY_KEY=$(cat "$KEY_DIR/$MY_HANDLE.pub.json" | python3 -c "import json,sys; print(json.load(sys.stdin)['key'])")
  MY_KEY_ID=$(cat "$KEY_DIR/$MY_HANDLE.pub.json" | python3 -c "import json,sys; print(json.load(sys.stdin)['key_id'])")

  # initial trust.json with only MY key (peer adds theirs on join)
  python3 - <<PY
import json, datetime
trust = {
  "version": 1,
  "agents": {
    "$MY_HANDLE": {
      "public_keys": [{
        "key_id": "$MY_KEY_ID",
        "key": "$MY_KEY",
        "added_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "active": True
      }]
    }
  }
}
with open("_coordination/trust.json", "w") as f:
    json.dump(trust, f, indent=2)
    f.write("\n")
PY

  # README for the wire repo
  cat > README.md <<README
# wire repo: $MY_HANDLE <-> $PEER_HANDLE

inter-agent-deaddrop coordination wire created by \`install.sh init\`.

- Owner: $MY_HANDLE
- Peer: $PEER_HANDLE
- Spec: https://github.com/laulpogan/inter-agent-deaddrop
- Bootstrapped: $(date -u +%Y-%m-%dT%H:%M:%SZ)

## Files

\`_coordination/\` holds the wire (PROTOCOL.md, tiers.json, JSONL inboxes, trust.json).
$MY_HANDLE side daemons run via systemd-user / launchd.

## Joining as peer

Run on your machine:
\`\`\`
bash <(curl -sSL https://raw.githubusercontent.com/laulpogan/inter-agent-deaddrop/main/install.sh) join \\
  https://github.com/$GH_USER/$REPO_NAME \\
  --my-handle $PEER_HANDLE --peer-handle $MY_HANDLE
\`\`\`
README

  # commit + push
  git -c user.name="$MY_HANDLE" -c user.email="$MY_HANDLE@local" -c commit.gpgsign=false add -A
  git -c user.name="$MY_HANDLE" -c user.email="$MY_HANDLE@local" -c commit.gpgsign=false commit -q \
    -m "Bootstrap wire repo for $MY_HANDLE <-> $PEER_HANDLE"
  git push --quiet origin main

  # invite peer (skip if peer is the same gh user as OP, which only happens in self-test)
  if [ "$PEER_GITHUB" = "$GH_USER" ]; then
    log "peer GitHub == repo owner; skipping collaborator invite"
  else
    log "inviting GitHub user $PEER_GITHUB as collaborator"
    if gh api -X PUT "repos/$GH_USER/$REPO_NAME/collaborators/$PEER_GITHUB" -f permission=push >/dev/null 2>&1; then
      log "invite sent"
    else
      log "WARN: could not invite $PEER_GITHUB (may need manual invite via gh repo collaborator add)"
    fi
  fi

  # install daemon
  install_daemon "$WIRE_DIR" "$MY_HANDLE" "$PEER_HANDLE"

  echo
  echo "===== INIT COMPLETE ====="
  echo "wire URL: https://github.com/$GH_USER/$REPO_NAME"
  echo "your handle: $MY_HANDLE"
  echo "peer handle: $PEER_HANDLE"
  echo "peer GitHub: $PEER_GITHUB (invited as collaborator)"
  echo
  echo "share with peer:"
  echo "  bash <(curl -sSL https://raw.githubusercontent.com/laulpogan/inter-agent-deaddrop/main/install.sh) join \\"
  echo "    https://github.com/$GH_USER/$REPO_NAME \\"
  echo "    --my-handle $PEER_HANDLE --peer-handle $MY_HANDLE"
  echo
  echo "daemon installed; will sync at heartbeat cadence (90s default)."
}

# ===== JOIN MODE =====
join_mode() {
  [ -z "$WIRE_URL" ] && die "join: wire repo URL required as positional arg"
  [ -z "$MY_HANDLE" ] && die "join: --my-handle required"
  [ -z "$PEER_HANDLE" ] && die "join: --peer-handle required"
  validate_handle "$MY_HANDLE"
  validate_handle "$PEER_HANDLE"

  # parse owner/repo from URL
  OWNER_REPO=$(echo "$WIRE_URL" | sed -E 's|https://github.com/||;s|.git$||')
  OWNER=$(echo "$OWNER_REPO" | cut -d/ -f1)
  REPO=$(echo "$OWNER_REPO" | cut -d/ -f2)

  log "joining wire: $OWNER/$REPO"

  # Accept any pending invitation
  INVITE_ID=$(gh api /user/repository_invitations --jq ".[] | select(.repository.full_name==\"$OWNER_REPO\") | .id" | head -1 || true)
  if [ -n "$INVITE_ID" ]; then
    log "accepting collaborator invite (id=$INVITE_ID)"
    gh api -X PATCH "/user/repository_invitations/$INVITE_ID" >/dev/null
    sleep 1
  else
    log "no pending invite (already accepted, or OP didn't invite this account)"
  fi

  # clone with token
  WIRE_DIR="$HOME/wire/$REPO"
  rm -rf "$WIRE_DIR" && mkdir -p "$(dirname "$WIRE_DIR")"
  TOKEN=$(gh auth token)
  git clone --quiet "https://${GH_USER}:${TOKEN}@github.com/${OWNER}/${REPO}.git" "$WIRE_DIR" || \
    die "clone failed; verify invitation accepted + token has repo scope"
  cd "$WIRE_DIR"

  # gen keypair
  gen_keypair "$MY_HANDLE"
  MY_KEY=$(cat "$KEY_DIR/$MY_HANDLE.pub.json" | python3 -c "import json,sys; print(json.load(sys.stdin)['key'])")
  MY_KEY_ID=$(cat "$KEY_DIR/$MY_HANDLE.pub.json" | python3 -c "import json,sys; print(json.load(sys.stdin)['key_id'])")

  # add my pubkey to trust.json
  python3 - <<PY
import json, datetime
from pathlib import Path
p = Path("_coordination/trust.json")
trust = json.loads(p.read_text())
agents = trust.setdefault("agents", {})
entry = agents.setdefault("$MY_HANDLE", {"public_keys": []})
existing = [k for k in entry["public_keys"] if k["key_id"] == "$MY_KEY_ID"]
if not existing:
    entry["public_keys"].append({
        "key_id": "$MY_KEY_ID",
        "key": "$MY_KEY",
        "added_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "active": True
    })
    p.write_text(json.dumps(trust, indent=2) + "\n")
PY

  # ensure my outbound JSONL exists
  touch "_coordination/${MY_HANDLE}_to_${PEER_HANDLE}.jsonl"
  touch "_coordination/${PEER_HANDLE}_to_${MY_HANDLE}.jsonl"

  git -c user.name="$MY_HANDLE" -c user.email="$MY_HANDLE@local" -c commit.gpgsign=false add -A
  git -c user.name="$MY_HANDLE" -c user.email="$MY_HANDLE@local" -c commit.gpgsign=false commit -q \
    -m "Add $MY_HANDLE pubkey ($MY_KEY_ID) to trust + initialize JSONLs"
  git push --quiet origin main

  # install daemon
  install_daemon "$WIRE_DIR" "$MY_HANDLE" "$PEER_HANDLE"

  # send first signed heartbeat
  log "sending first signed heartbeat"
  python3 - <<PY
import sys, json, datetime
from pathlib import Path
sys.path.insert(0, "$DEADDROP_DIR/v3")
sys.path.insert(0, "$DEADDROP_DIR/examples")
from signing import signed_append_jsonl, b64decode

priv = Path("$KEY_DIR/$MY_HANDLE.key").read_bytes()
pub_record = json.loads(Path("$KEY_DIR/$MY_HANDLE.pub.json").read_text())
pub = b64decode(pub_record["key"])
ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
msg = {
  "timestamp": ts,
  "from": "$MY_HANDLE",
  "type": "heartbeat",
  "subject": "online via install.sh join",
  "body": {"wakeup_count": 1, "state": "idle", "last_action": "joined wire via install.sh", "next_eta": ts, "inbox_unread_count": 0},
  "refs": ["https://github.com/laulpogan/inter-agent-deaddrop/blob/main/ONBOARDING.md"],
  "priority": "low",
  "correlation_id": ts,
  "ack_required": False,
}
signed_append_jsonl(Path("_coordination/${MY_HANDLE}_to_${PEER_HANDLE}.jsonl"), msg, priv, pub, "$MY_HANDLE")
print(f"signed heartbeat: key_id={msg.get('correlation_id')}")
PY

  # nudge daemon to push immediately
  case "$(uname -s)" in
    Linux*)
      PID=$(systemctl --user show wire-daemon -p MainPID --value || echo)
      [ -n "$PID" ] && [ "$PID" != "0" ] && kill -USR1 "$PID" 2>/dev/null || true
      ;;
    Darwin*)
      PID=$(pgrep -f "wire-daemon.py.*$REPO" | head -1 || echo)
      [ -n "$PID" ] && kill -USR1 "$PID" 2>/dev/null || true
      ;;
  esac

  echo
  echo "===== JOIN COMPLETE ====="
  echo "wire URL: $WIRE_URL"
  echo "your handle: $MY_HANDLE"
  echo "peer handle: $PEER_HANDLE"
  echo "your key_id: $MY_KEY_ID"
  echo
  echo "trust.json updated with your pubkey + pushed."
  echo "first signed heartbeat sent + daemon nudged."
  echo "peer's daemon will fetch within ~90s; ack expected within ~3min."
  echo
  echo "watch your inbound:"
  echo "  tail -f $WIRE_DIR/_coordination/${PEER_HANDLE}_to_${MY_HANDLE}.jsonl"
}

case "$MODE" in
  init) init_mode;;
  join) join_mode;;
  *) usage;;
esac
