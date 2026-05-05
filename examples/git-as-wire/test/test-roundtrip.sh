#!/usr/bin/env bash
#
# Local two-clone integration test for git-as-wire transport.
#
# Simulates two operators with two clones of a shared bare repo. Each side
# appends a heartbeat, runs the daemon once to push, then runs the daemon on
# the OTHER side to verify it sees the message.
#
# No network needed. No remote git host. Just /tmp.

set -euo pipefail

TEST_DIR=${TEST_DIR:-/tmp/inter-agent-deaddrop-wiretest}
DAEMON="$(cd "$(dirname "$0")"/.. && pwd)/wire-daemon.py"

# Clean slate
rm -rf "$TEST_DIR"
mkdir -p "$TEST_DIR"
cd "$TEST_DIR"

echo "=== 1. create bare repo (simulating GitHub) ==="
git init --bare -q wire.git -b main

echo "=== 2. bootstrap commit from a third dir ==="
git clone -q wire.git bootstrap
cd bootstrap
mkdir -p _coordination
touch _coordination/{agent_a_to_agent_b,agent_b_to_agent_a,decisions,incident_log}.jsonl
echo '# placeholder' > _coordination/PROTOCOL.md
git -c user.name=op -c user.email=op@test.local -c commit.gpgsign=false add -A
git -c user.name=op -c user.email=op@test.local -c commit.gpgsign=false commit -q -m "Bootstrap wire repo"
git push -q origin main
cd ..
rm -rf bootstrap

echo "=== 3. clone for agent_a ==="
git clone -q wire.git a
cd a
git config user.name agent_a
git config user.email agent_a@test.local
git config commit.gpgsign false
cat > .wire-config.json <<EOF
{
  "agent": "agent_a",
  "outbound_file": "_coordination/agent_a_to_agent_b.jsonl",
  "inbound_file": "_coordination/agent_b_to_agent_a.jsonl",
  "heartbeat_cadence_sec": 90,
  "remote": "origin",
  "branch": "main"
}
EOF
cd ..

echo "=== 4. clone for agent_b ==="
git clone -q wire.git b
cd b
git config user.name agent_b
git config user.email agent_b@test.local
git config commit.gpgsign false
cat > .wire-config.json <<EOF
{
  "agent": "agent_b",
  "outbound_file": "_coordination/agent_b_to_agent_a.jsonl",
  "inbound_file": "_coordination/agent_a_to_agent_b.jsonl",
  "heartbeat_cadence_sec": 90,
  "remote": "origin",
  "branch": "main"
}
EOF
cd ..

echo "=== 5. agent_a appends a heartbeat ==="
TS_A=$(date -u +%Y-%m-%dT%H:%M:%SZ)
python3 -c "
import json, sys
sys.path.insert(0, '$(cd "$(dirname "$0")"/../.. && pwd)')
from safe_append_jsonl import safe_append_jsonl
from pathlib import Path
safe_append_jsonl(Path('$TEST_DIR/a/_coordination/agent_a_to_agent_b.jsonl'), {
    'timestamp': '$TS_A',
    'from': 'agent_a',
    'type': 'heartbeat',
    'subject': 'bootstrap',
    'body': {'wakeup_count': 1, 'state': 'idle', 'last_action': 'wire test bootstrap', 'next_eta': '$TS_A', 'inbox_unread_count': 0},
    'refs': [],
    'priority': 'low',
    'correlation_id': '$TS_A',
    'ack_required': False
})
print('appended to a_to_b')
"

echo "=== 6. daemon tick on agent_a (push) ==="
python3 "$DAEMON" "$TEST_DIR/a" --once 2>&1 | tail -8

echo "=== 7. daemon tick on agent_b (fetch + see new msg) ==="
python3 "$DAEMON" "$TEST_DIR/b" --once 2>&1 | tail -8

echo "=== 8. agent_b replies ==="
TS_B=$(date -u +%Y-%m-%dT%H:%M:%SZ)
python3 -c "
import json, sys
sys.path.insert(0, '$(cd "$(dirname "$0")"/../.. && pwd)')
from safe_append_jsonl import safe_append_jsonl
from pathlib import Path
safe_append_jsonl(Path('$TEST_DIR/b/_coordination/agent_b_to_agent_a.jsonl'), {
    'timestamp': '$TS_B',
    'from': 'agent_b',
    'type': 'ack',
    'subject': 'observed agent_a bootstrap',
    'body': 'saw your heartbeat. wire works.',
    'refs': [],
    'priority': 'low',
    'correlation_id': '$TS_A',
    'ack_required': False
})
print('appended to b_to_a')
"

echo "=== 9. daemon tick on agent_b (push reply) ==="
python3 "$DAEMON" "$TEST_DIR/b" --once 2>&1 | tail -8

echo "=== 10. daemon tick on agent_a (fetch reply) ==="
python3 "$DAEMON" "$TEST_DIR/a" --once 2>&1 | tail -8

echo "=== 11. verify both sides see both messages ==="
A_OUT=$(awk 'END{print NR}' "$TEST_DIR/a/_coordination/agent_a_to_agent_b.jsonl")
A_IN=$(awk 'END{print NR}' "$TEST_DIR/a/_coordination/agent_b_to_agent_a.jsonl")
B_OUT=$(awk 'END{print NR}' "$TEST_DIR/b/_coordination/agent_b_to_agent_a.jsonl")
B_IN=$(awk 'END{print NR}' "$TEST_DIR/b/_coordination/agent_a_to_agent_b.jsonl")

echo "agent_a: outbound=$A_OUT inbound=$A_IN"
echo "agent_b: outbound=$B_OUT inbound=$B_IN"

if [ "$A_OUT" = 1 ] && [ "$A_IN" = 1 ] && [ "$B_OUT" = 1 ] && [ "$B_IN" = 1 ]; then
  echo
  echo "=== PASS: round-trip complete ==="
  echo
  echo "Bare repo log:"
  git -C "$TEST_DIR/wire.git" log --oneline
  exit 0
else
  echo
  echo "=== FAIL: line counts wrong (expected 1/1/1/1) ==="
  exit 1
fi
