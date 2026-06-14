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

TESTS="$ROOT/taskB/private_judge/tests"
if [[ ! -d "$TESTS" ]]; then
  echo "Missing Task B tests: $TESTS" >&2
  echo "Run: scripts/make_taskB_tests.sh" >&2
  exit 2
fi

if [[ ! -d "$WS/solution" ]]; then
  echo "Missing solution directory: $WS/solution" >&2
  exit 2
fi

python3 "$ROOT/taskB/private_judge/grader.py" "$WS/solution" "$TESTS"
