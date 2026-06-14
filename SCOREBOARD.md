# Contest Scoreboard

评分采用两层：

1. 原始任务分：由各 task 的 grader 或盲评产生。
2. 时间扣分：同一 task 内，以更快完成者为基准；另一方每多慢 1 倍，扣 5 分。

时间扣分公式：

```text
time_penalty = max(0, round(slower_time / faster_time - 1)) * 5
adjusted_score = raw_score - time_penalty
```

实际操作中，如果只记录了近似倍数，可直接按人工确认的额外慢倍数扣分。

## Current Results

| Task | Contestant | Raw score | Time penalty | Adjusted score | Notes |
|---|---:|---:|---:|---:|---|
| A | Claude Opus 4.8 + Claude Code | 90 / 90 | 0 | 90 / 90 | 自动评测满分 |
| A | GLM-5.2 + opencode | 90 / 90 | 15 | 75 / 90 | 约 4x Claude，用额外慢 3 倍扣 `3*5` |
| B | Claude Opus 4.8 + Claude Code | 95 / 95 | 0 | 95 / 95 | 自动评测满分 |
| B | GLM-5.2 + opencode | 95 / 95 | 5 | 90 / 95 | 约 2x Claude，用额外慢 1 倍扣 `1*5` |
| C | Claude Opus 4.8 + Claude Code | 97 / 100 | 0 | 97 / 100 | 客观闸门暂记 40/40；人类主观 95/100，折算美学 57/60 |
| C | GLM-5.2 + opencode | 94 / 100 | 15 | 79 / 100 | 客观闸门 40/40；人类主观 90/100，折算美学 54/60；约 4x Claude，用额外慢 3 倍扣 `3*5` |

## Totals So Far

| Contestant | Raw total | Time penalty | Adjusted total |
|---|---:|---:|---:|
| Claude Opus 4.8 + Claude Code | 282 / 285 | 0 | 282 / 285 |
| GLM-5.2 + opencode | 279 / 285 | 35 | 244 / 285 |
