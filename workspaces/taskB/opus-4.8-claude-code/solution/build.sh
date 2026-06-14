#!/usr/bin/env bash
set -euo pipefail
# Compile the solution. Output binary lives next to this script.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
c++ -O2 -std=c++17 -o "$DIR/sol" "$DIR/main.cpp"
