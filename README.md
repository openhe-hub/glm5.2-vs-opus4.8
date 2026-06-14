# GLM 5.2 vs Claude Opus 4.8 Coding Contest

这是一次小型对照赛：`GLM-5.2 + opencode` vs `Claude Opus 4.8 + Claude Code`。三个任务覆盖后端工程、算法竞赛和前端审美，两个 agent 使用同样题面、同样 starter、同样评分脚本。

## 三点结论

1. **能力**：GLM-5.2 的最终交付质量仍小于 Claude Opus 4.8，但差距没有速度体验那么大。粗略体感上，GLM-5.2 大概落在 Claude Opus 4.5 - Opus 4.6 之间，或者在 GPT-5.2-Codex / GPT-5.3-Codex 之间。
2. **速度**：GLM-5.2 + opencode 这一关拉了，整体大概是 Claude Code 的 **3-5 倍耗时**。如果按开发效率计分，差距会被明显拉开。
3. **价格**：Claude Code 使用的是 **Max $100/month** 订阅；GLM 使用的是国际版 **Lite $16/month** 订阅。国内 coding plan 约便宜一半，但目前基本抢不到；另外 GLM-5.2 在 peak hours 有 **3x 惩罚倍率**，真实性价比要结合地区、计划和使用时段看。

## 任务设计

| Task | 类型 | 内容 | 主要考察 |
|---|---|---|---|
| A | 后端工程 | MVCC 事务型 KV 存储，带 WAL 持久化与 kill -9 崩溃恢复 | 协议实现、并发控制、快照隔离、写写冲突、fsync、恢复 |
| B | 算法 | 离线动态连通性，实时输出最大连通分量 | 算法识别、可撤销并查集、线段树分治、性能 |
| C | 前端 / UI | 高端设计品牌 FORM 的单页产品页和交互式配置器 | 审美、排版、响应式、可访问性、动效、状态设计 |

## 分数统计

时间扣分规则：同一 task 内，以更快完成者为基准；另一方每多慢 1 倍扣 5 分。

```text
time_penalty = max(0, round(slower_time / faster_time - 1)) * 5
adjusted_score = raw_score - time_penalty
```

| Task | Contestant | Raw score | Time penalty | Adjusted score | Notes |
|---|---:|---:|---:|---:|---|
| A | Claude Opus 4.8 + Claude Code | 90 / 90 | 0 | 90 / 90 | 自动评测满分 |
| A | GLM-5.2 + opencode | 90 / 90 | 15 | 75 / 90 | 约 4x Claude，扣 `3*5` |
| B | Claude Opus 4.8 + Claude Code | 95 / 95 | 0 | 95 / 95 | 自动评测满分 |
| B | GLM-5.2 + opencode | 95 / 95 | 5 | 90 / 95 | 约 2x Claude，扣 `1*5` |
| C | Claude Opus 4.8 + Claude Code | 97 / 100 | 0 | 97 / 100 | 客观 40/40；主观 95/100，折算美学 57/60 |
| C | GLM-5.2 + opencode | 94 / 100 | 15 | 79 / 100 | 客观 40/40；主观 90/100，折算美学 54/60；约 4x Claude，扣 `3*5` |

| Contestant | Raw total | Time penalty | Adjusted total |
|---|---:|---:|---:|
| Claude Opus 4.8 + Claude Code | 282 / 285 | 0 | 282 / 285 |
| GLM-5.2 + opencode | 279 / 285 | 35 | 244 / 285 |

**一句话总结**：GLM-5.2 的代码能力仍弱于 Claude Opus 4.8，但已经能完成高难任务；真正拖后腿的是响应速度和 agent loop 体验。Claude Code 在“同样时间内更快完成高质量交付”这个维度上优势很大。

## 仓库结构

```text
source_docs/                 原始题面
taskA|taskB|taskC/public/    选手可见 prompt
taskA|taskB|taskC/private_judge/
                             评测脚本、reference、审计工具
workspaces/<task>/<agent>/   两个 agent 的最终交付
scripts/                     一键评分脚本
SCOREBOARD.md                详细分数记录
```

两个 agent 目录名：

```text
glm-5.2-opencode
opus-4.8-claude-code
```

## 复现评分

Task A：

```bash
scripts/grade_taskA.sh workspaces/taskA/glm-5.2-opencode
scripts/grade_taskA.sh workspaces/taskA/opus-4.8-claude-code
```

Task B：

```bash
scripts/make_taskB_tests.sh
scripts/grade_taskB.sh workspaces/taskB/glm-5.2-opencode
scripts/grade_taskB.sh workspaces/taskB/opus-4.8-claude-code
```

Task C 客观闸门：

```bash
pip install playwright
playwright install chromium

scripts/grade_taskC_gate.sh workspaces/taskC/glm-5.2-opencode
scripts/grade_taskC_gate.sh workspaces/taskC/opus-4.8-claude-code
```

Task C Lighthouse / axe：

```bash
npm i -g lighthouse @axe-core/cli
python3 -m http.server 8080 -d workspaces/taskC/glm-5.2-opencode/solution
bash taskC/private_judge/run_audit.sh http://127.0.0.1:8080/index.html
```

## 公平性约定

- 同一 task 下两个 agent 使用同样 prompt、同样 starter、同样时间和 turn 预算。
- agent 开发期不接触 `private_judge/`、`source_docs/` 或另一个选手目录。
- 人工干预、额外提示、运行时长、turn 数单独记录。
- 最终只从各自 `solution/` 目录评分。

## 说明

这个 benchmark 不是严格学术评测，更像一次可复现的实战观察。它同时测了模型能力、coding agent 外壳、工具调用节奏、provider 延迟和价格体验。原始分说明 GLM-5.2 能力很强；时间扣分说明在当前 opencode + GLM-5.2 组合下，真实开发效率仍然明显落后于 Claude Code。
