#!/usr/bin/env bash
#
# Open / close / status SSH tunnel from Mac to Spark mcp_agent_mail.
# Local port 8775 -> remote 127.0.0.1:8765
#
# Usage:
#   spark-tunnel.sh up      # open tunnel
#   spark-tunnel.sh down    # close tunnel
#   spark-tunnel.sh status  # show status
#   spark-tunnel.sh test    # ping the server through tunnel

set -euo pipefail

LOCAL_PORT=8775
REMOTE_HOST=promaxgb10-d325
REMOTE_PORT=8765
TOKEN_FILE=~/.config/mcp_agent_mail/spark_token

cmd="${1:-status}"

case "$cmd" in
  up)
    if lsof -ti:"$LOCAL_PORT" >/dev/null 2>&1; then
      echo "tunnel already up on :$LOCAL_PORT"
      lsof -i :"$LOCAL_PORT"
      exit 0
    fi
    ssh -fN -L "$LOCAL_PORT":127.0.0.1:"$REMOTE_PORT" "$REMOTE_HOST"
    sleep 1
    lsof -i :"$LOCAL_PORT" | head -3
    echo "tunnel up: localhost:$LOCAL_PORT -> $REMOTE_HOST:$REMOTE_PORT"
    ;;
  down)
    pid=$(lsof -ti:"$LOCAL_PORT" 2>/dev/null || true)
    if [ -z "$pid" ]; then
      echo "no tunnel on :$LOCAL_PORT"
      exit 0
    fi
    kill "$pid" 2>/dev/null || true
    sleep 1
    if lsof -ti:"$LOCAL_PORT" >/dev/null 2>&1; then
      echo "tunnel STILL UP on :$LOCAL_PORT"
      exit 1
    fi
    echo "tunnel closed"
    ;;
  status)
    if lsof -i :"$LOCAL_PORT" >/dev/null 2>&1; then
      echo "tunnel: UP"
      lsof -i :"$LOCAL_PORT"
    else
      echo "tunnel: DOWN"
    fi
    ;;
  test)
    if [ ! -f "$TOKEN_FILE" ]; then
      echo "missing $TOKEN_FILE"
      echo "fetch with: ssh $REMOTE_HOST 'cat ~/.config/mcp_agent_mail/server_token' > $TOKEN_FILE && chmod 600 $TOKEN_FILE"
      exit 1
    fi
    TOKEN=$(cat "$TOKEN_FILE")
    code=$(curl -sf -o /dev/null -w '%{http_code}' \
      -H "Authorization: Bearer $TOKEN" \
      -H 'Accept: application/json, text/event-stream' \
      -H 'Content-Type: application/json' \
      -X POST \
      -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"tunnel-test","version":"0.1"}}}' \
      "http://127.0.0.1:$LOCAL_PORT/api/" || echo 000)
    echo "ping localhost:$LOCAL_PORT/api/  -> code=$code"
    ;;
  *)
    echo "usage: $0 {up|down|status|test}"
    exit 2
    ;;
esac
