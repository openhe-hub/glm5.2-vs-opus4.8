# GLM 5.2 vs Claude Opus 4.8 Contest Harness

这个目录已经把三个挑战拆成公平的赛场结构：

- `source_docs/`: 第三方 AI 给出的原始 Markdown 题面，保留备查。
- `taskA/public/PROMPT.txt`: Task A 选手可见提示词。
- `taskB/public/PROMPT.txt`: Task B 选手可见提示词。
- `taskC/public/PROMPT.txt`: Task C 选手可见提示词。
- `task*/private_judge/`: 评委私有 grader、reference、生成器等，不要放进 agent 上下文。
- `workspaces/<task>/<contestant>/`: agent 的隔离起跑目录。每个目录只包含同一份 `PROMPT.txt` 和空的 `solution/` starter。

两个 agent 目录是：

- `glm-5.2-opencode`
- `opus-4.8-claude-code`

每个 task 下各有这两个目录；现在三个任务一共六个 agent workspace。

建议启动方式：在对应目录下启动 agent，并只给它读本目录内容。

```bash
cd workspaces/taskA/glm-5.2-opencode
# paste PROMPT.txt to the agent, or ask it to read PROMPT.txt and implement solution/
```

赛后评分：

```bash
# Task A
scripts/grade_taskA.sh workspaces/taskA/glm-5.2-opencode

# Task B: 第一次评分前先生成 held-out tests
scripts/make_taskB_tests.sh
scripts/grade_taskB.sh workspaces/taskB/glm-5.2-opencode

# Task C: 客观闸门，需先安装 playwright/chromium
scripts/grade_taskC_gate.sh workspaces/taskC/glm-5.2-opencode

# Task C: Lighthouse + axe 补充分，需 npm 全局安装 lighthouse 与 @axe-core/cli
bash taskC/private_judge/run_audit.sh http://127.0.0.1:<port>/index.html
```

当前战报和时间扣分规则见 `SCOREBOARD.md`。

公平性约定：

- 同一 task 下两个 agent 使用同样 prompt、同样 starter、同样时间和 turn 预算。
- agent 开发期不要接触 `private_judge/`、`source_docs/` 或其它选手目录。
- 人工干预、额外提示、运行时长、turn 数都单独记录。
- 最终只从各自 `solution/` 目录评分。
