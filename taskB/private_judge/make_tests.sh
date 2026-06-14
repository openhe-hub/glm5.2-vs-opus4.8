#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
g++ -O2 -std=c++17 -o reference reference.cpp
mkdir -p tests
python3 gen.py 8 30 11 0.4 > tests/small_01.in
python3 brute.py < tests/small_01.in > tests/small_01.ans
python3 gen.py 300000 300000 7 0.35 > tests/large_01.in
./reference < tests/large_01.in > tests/large_01.ans
python3 gen.py 200000 300000 99 0.5 > tests/large_02.in
./reference < tests/large_02.in > tests/large_02.ans
printf '100000 5\n?\n+ 1 2\n?\n- 1 2\n?\n' > tests/edge_01.in
./reference < tests/edge_01.in > tests/edge_01.ans
python3 - <<'PY2'
import json
json.dump({
  "small_01":{"category":"small"},
  "large_01":{"category":"large"},
  "large_02":{"category":"large"},
  "edge_01":{"category":"edge"}
}, open("tests/meta.json","w"), indent=2)
PY2
