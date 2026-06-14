#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <workspace_dir>" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WS="$1"
if [[ "$WS" != /* ]]; then
  WS="$ROOT/$WS"
fi

HTML="$WS/solution/index.html"
if [[ ! -f "$HTML" ]]; then
  echo "Missing required file: $HTML" >&2
  exit 2
fi

PORT="$(python3 - <<'PY'
import socket
s=socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"

python3 -m http.server "$PORT" --bind 127.0.0.1 -d "$WS/solution" >/tmp/taskC-http-"$PORT".log 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" >/dev/null 2>&1 || true' EXIT
sleep 0.5

cd "$ROOT"
python3 taskC/private_judge/gate_check.py "http://127.0.0.1:$PORT/index.html" --js-budget-kb 30
