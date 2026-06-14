#!/bin/bash
# Requires: npm i -g lighthouse @axe-core/cli ; chromium installed
URL="$1"   # e.g. file:///abs/path/index.html or http://localhost:8080
lighthouse "$URL" --quiet --chrome-flags="--headless" \
  --only-categories=accessibility,performance \
  --output=json --output-path=./lh.json
node -e '
  const r=require("./lh.json");
  const a11y=Math.round(r.categories.accessibility.score*100);
  const perf=Math.round(r.categories.performance.score*100);
  let pts=0; pts += a11y>=95?7:(a11y>=90?4:0); pts += perf>=90?4:(perf>=80?2:0);
  console.log(`a11y=${a11y} perf=${perf} -> Lighthouse pts=${pts}/11`);
'
axe "$URL" --exit   # hard-fails on any critical accessibility violation