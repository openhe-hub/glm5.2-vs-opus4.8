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

if [[ ! -d "$WS/solution" ]]; then
  echo "Missing solution directory: $WS/solution" >&2
  exit 2
fi

python3 "$ROOT/taskA/private_judge/grader.py" "$WS/solution"
