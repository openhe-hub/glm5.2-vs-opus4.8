#!/usr/bin/env bash
set -euo pipefail

# Resolve the directory of this script (so build works from any CWD).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CXX="${CXX:-c++}"
CXXFLAGS="${CXXFLAGS:--O3 -DNDEBUG -std=c++17 -pthread -Wall}"

# Pick a compiler: prefer clang++, fall back to g++.
if command -v clang++ >/dev/null 2>&1; then
    CXX="clang++"
elif command -v g++ >/dev/null 2>&1; then
    CXX="g++"
fi

mkdir -p "$DIR/bin"
echo "[build] $CXX $CXXFLAGS"
"$CXX" $CXXFLAGS -o "$DIR/bin/kvserver" "$DIR/src/main.cpp"
echo "[build] ok -> $DIR/bin/kvserver"
