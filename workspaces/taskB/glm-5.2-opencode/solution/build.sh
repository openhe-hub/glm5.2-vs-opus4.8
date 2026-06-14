#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
g++ -O2 -std=c++17 -o "$DIR/sol" "$DIR/main.cpp"
