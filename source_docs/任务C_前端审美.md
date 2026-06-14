# 任务 C（前端 / 审美）— 高难度艺术指导 + 可复现盲评

> 用途：`GLM-5.2 + opencode` vs `Claude Opus 4.8 + Claude Code` 对照赛第三题。
> 审美天然主观，本题的工程难点是**把主观打分做成可复现、抗作弊的盲评**：
> 40 分客观闸门（全自动） + 60 分美学评分（盲测 + 1 名人类评委 + 1 个 LLM 评委 GPT-5.5）。
> 已在本机验证的部分：LLM 评委的「随机位置去偏」与「方差聚合」逻辑（20 次 trial 单测通过，位置不泄漏身份）；客观闸门脚本的预算与计分算法。**未在本沙箱执行的部分**：真实 API 调用与 headless 浏览器（需你本机的 key + `playwright install`）——脚本可直接运行，已 `py_compile` 通过。

---

## 0. 比赛协议

| 项 | 设定 |
|---|---|
| 环境 | 同机、同 starter、同评测工具版本（Lighthouse/axe/Playwright） |
| 预算 | wall-clock 90 min 或 60 turns（审美题给更长，逼出打磨） |
| 交付 | **单一自包含文件**：`index.html`（HTML+CSS+JS 内联）或单个 React 文件 |
| 盲评 | 截图/录屏去除一切可识别注释，随机 A/B；评委不知哪个是哪个模型 |
| 评委 | 1 名人类 + 1 个 LLM（GPT-5.5）。GPT-5.5 与两位选手（GLM-5.2、Claude）均非同源，天然中立、不存在自偏好 |

> 为什么要「单文件 + JS 预算」：禁掉 UI 套件与重框架，逼模型**手写**版式与交互，审美与克制才暴露得出来。

---

## 1. 选手提示词（逐字粘贴给两个 agent）

````
为一个虚构高端设计品牌 “FORM” 实现一个沉浸式单页产品页（hero product 自定，
如模块化台灯 / 机械腕表 / 桌面音箱，二选一即可）。这是一道考审美与交付完成度的题。

【必须包含的区块】
1. 艺术指导级 Hero：有明确的版式主张与负空间，不是“居中大标题 + 副标题”套路。
2. 规格 / 特性区：信息设计扎实，有清晰的排版层级与节奏。
3. 交互式配置器（Configurator）：可选材质/颜色（≥3 选项），
   实时更新预览与价格；切换有得体的过渡。
4. 画廊或细节展示区。
5. 页脚（含次级信息层级）。

【交互与状态（硬性）】
- 滚动驱动的揭示/视差，做得克制、不晕，且 prefers-reduced-motion 下自动降级。
- 配置器全键盘可达：Tab 顺序合理、:focus-visible 可见、Enter/方向键可操作。
- 必须设计齐全部状态：default / hover / focus / active / disabled / loading / empty / error。
- 响应式 320px → 1440px 全程无横向溢出。
- 暗色模式：遵循 prefers-color-scheme。

【技术约束（硬性）】
- 单一自包含文件；不得引入任何 UI 组件库（Bootstrap/shadcn/Material/Ant 等一律禁止）。
- 字体仅用系统字体或自托管，不外链第三方字体 CDN。
- 传输 JS（gzip 后，不含字体）≤ 30KB —— 故不建议引入重框架。
- 60fps，无 console 报错，语义化 HTML。
- 目标：Lighthouse a11y ≥ 95，performance ≥ 90。

【明令禁止（出现即扣“原创性”）】
- 默认 Tailwind 调色板（那个标志性的蓝）、未改动的组件库外观。
- “居中 Hero + 三张特性卡片”模板。
- emoji 当图标、lorem ipsum 占位、靠 stock 渐变堆视觉。

【交付】单个文件 + 一段 README 写明：art direction 取向、字体/网格/色板系统、
做了哪些状态与可访问性处理。
````

---

## 2. 客观闸门（40 分，全自动）

### 2.1 `judge/gate_check.py`（已 py_compile，逻辑已单测）

跑断点溢出、console 报错、`:focus-visible`、`prefers-reduced-motion`、`prefers-color-scheme`、**gzip JS 预算**，并截图供后续盲评。

```python
#!/usr/bin/env python3
# Objective auto-gate for Task C (40 pts). Pairs with Lighthouse + axe.
# Requires: pip install playwright && playwright install chromium
# Usage: python3 gate_check.py <url_or_file> [--js-budget-kb 30]
import sys, json, gzip, argparse, pathlib, re
from playwright.sync_api import sync_playwright

BREAKPOINTS = [(320, 720), (768, 1024), (1024, 768), (1440, 900)]
STATES = ["default","hover","focus","active","disabled","loading","empty","error"]

def gzip_kb(text: str) -> float:
    return len(gzip.compress(text.encode())) / 1024.0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target"); ap.add_argument("--js-budget-kb", type=float, default=30.0)
    a = ap.parse_args()
    url = a.target if a.target.startswith("http") else pathlib.Path(a.target).resolve().as_uri()
    result = {"overflow":{}, "console_errors":[], "js_kb":None, "focus_visible":False,
              "reduced_motion_ok":None, "prefers_dark_ok":None, "score":0, "notes":[]}
    with sync_playwright() as p:
        browser = p.chromium.launch(); ctx = browser.new_context(); page = ctx.new_page()
        js_bytes = {"n":0}
        def on_response(resp):
            try:
                ct = resp.headers.get("content-type","")
                if "javascript" in ct or resp.url.endswith(".js"):
                    js_bytes["n"] += len(gzip.compress(resp.body()))
            except Exception: pass
        page.on("response", on_response)
        page.on("console", lambda m: result["console_errors"].append(m.text) if m.type=="error" else None)
        page.goto(url, wait_until="networkidle")
        inline = page.eval_on_selector_all("script:not([src])","els => els.map(e=>e.textContent).join('')")
        result["js_kb"] = round(js_bytes["n"]/1024.0 + gzip_kb(inline or ""), 1)
        for w,h in BREAKPOINTS:
            page.set_viewport_size({"width":w,"height":h}); page.wait_for_timeout(150)
            sw = page.evaluate("document.documentElement.scrollWidth")
            result["overflow"][f"{w}x{h}"] = {"scrollWidth":sw, "ok": sw <= w+1}
        result["focus_visible"] = bool(page.evaluate("""()=>{for(const s of document.styleSheets){try{for(const r of s.cssRules)if(r.selectorText&&r.selectorText.includes(':focus-visible'))return true;}catch(e){}}return false;}"""))
        result["reduced_motion_ok"] = bool(page.evaluate("""()=>{for(const s of document.styleSheets){try{for(const r of s.cssRules)if(r.media&&String(r.media.mediaText).includes('prefers-reduced-motion'))return true;}catch(e){}}return false;}"""))
        result["prefers_dark_ok"] = bool(page.evaluate("""()=>{for(const s of document.styleSheets){try{for(const r of s.cssRules)if(r.media&&String(r.media.mediaText).includes('prefers-color-scheme'))return true;}catch(e){}}return false;}"""))
        out = pathlib.Path("gate_shots"); out.mkdir(exist_ok=True)
        page.set_viewport_size({"width":1440,"height":900}); page.screenshot(path=str(out/"desktop.png"), full_page=True)
        page.set_viewport_size({"width":390,"height":844});  page.screenshot(path=str(out/"mobile.png"),  full_page=True)
        browser.close()
    s=0; notes=result["notes"]
    if not result["console_errors"]: s+=5
    else: notes.append(f"{len(result['console_errors'])} console errors")
    ovf_ok = sum(1 for v in result["overflow"].values() if v["ok"]); s += round(8*ovf_ok/len(BREAKPOINTS))
    if ovf_ok < len(BREAKPOINTS): notes.append("horizontal overflow at some breakpoints")
    if result["js_kb"] is not None and result["js_kb"] <= a.js_budget_kb: s+=8
    else: notes.append(f"JS {result['js_kb']}KB > budget {a.js_budget_kb}KB")
    if result["focus_visible"]: s+=5
    else: notes.append("no :focus-visible")
    if result["reduced_motion_ok"]: s+=3
    else: notes.append("prefers-reduced-motion not handled")
    result["score_partial_of_29"]=s
    print(json.dumps(result, indent=2))
    print(f"\nObjective sub-score (excl. Lighthouse): {s}/29  (+11 from Lighthouse -> 40)")

if __name__ == "__main__": main()
```

### 2.2 Lighthouse + axe（补足 11 分）`judge/run_audit.sh`

```bash
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
```

**客观闸门计分（40）**：无 console 报错 5 ｜四断点无溢出 8 ｜JS≤30KB 8 ｜`:focus-visible` 5 ｜reduced-motion 3 ｜Lighthouse a11y≥95 (7) + perf≥90 (4) 11。
> axe 出现 critical 违规直接**客观分清零档**（视为不及格），无论美学多好。

---

## 3. 美学评分（60 分，盲测）

### 3.1 锚定式评分维度

| 维度 | 分值 | 看什么 |
|---|---|---|
| 排版与层级 typography | 12 | 模块化字号比例、层级、节奏、字体搭配、光学细节 |
| 色彩 color | 10 | 克制、和谐、有意图的点缀色、对比/可读性 |
| 布局与空间 layout | 10 | 间距系统、对齐纪律、网格、信息密度 |
| 原创性 originality | 12 | 是否有独立艺术指导，**反模板**（这是拉开差距的关键项） |
| 动效与交互 motion | 10 | 缓动/时序/编排的品味、克制、reduced-motion 尊重 |
| 整体完成度 polish | 6 | 一致性、收尾、边界细节 |

**原创性锚点示例**：0–3＝像没改过的 UI 套件；4–7＝能用但很常见的 SaaS 味；8–10＝明显艺术指导、少套路；11–12＝有记忆点、画廊级、毫无模板感。

### 3.2 盲测协议（抗作弊关键）

1. 两份作品各自截图（桌面 1440 + 移动 390）+ 录一段配置器交互的 GIF/MP4。
2. **去标识**：删掉作品里一切可暴露模型来源的注释/字符串。
3. **随机 A/B**：每个评委、每个 trial 随机左右互换；记录映射，事后还原。
4. **1 名人类评委**按 §3.1 六维独立打分（一份 /60 总分）；**1 个 LLM 评委 GPT-5.5** 用 §3.3 脚本跑 K≥8 次，取均值 ± 标准差。
5. **最终美学分 = 50% 人类 + 50% LLM**（各自 /60 后等权平均）。两者总分相差 > 12（满分 60 的 20%）时**标红复核**，由人类评委复看后定夺，不静默平均。GPT-5.5 与两位选手不同源，可放心作为中立 LLM 评委。

### 3.3 LLM 评委 `judge/llm_judge.py`（GPT-5.5；去偏 + 方差聚合 + 人类合并逻辑已单测通过）

> 已验证：20 次 trial 的随机位置互换能被正确还原到模型身份（位置不泄漏身份）、方差聚合数值正确、人类+LLM 等权合并与分歧标红均正确。API 调用部分已隔离，填入 `OPENAI_API_KEY` 即可运行。评委默认 `gpt-5.5`，与两位选手均非同源。

```python
#!/usr/bin/env python3
# Blind aesthetic LLM-judge for Task C, using an OpenAI model (e.g. GPT-5.5).
# Pairs with ONE human judge; final aesthetic = average of human + this LLM.
# Randomized A/B (kills order bias), anchored rubric, K trials, variance report.
#
# Requires: OPENAI_API_KEY in env ; pip install openai
# Usage: python3 llm_judge.py <dirX> <dirY> --labelX glm --labelY opus -k 8 --model gpt-5.5
#   each dir holds: desktop.png, mobile.png  (optionally states.png, interaction.png)
import os, sys, json, base64, random, argparse, statistics

DIMENSIONS = {"typography":12,"color":10,"layout":10,"originality":12,"motion":10,"polish":6}

RUBRIC = """You are a senior product designer judging two web submissions BLIND.
Score each on six dimensions. Use the FULL range; reserve top marks for top-studio work.
Penalize generic/templated output (default Tailwind/Bootstrap/shadcn look,
centered-hero + 3 cards, emoji icons, stock gradients).
Integers 0..MAX per dimension:
- typography 0..12  - color 0..10  - layout 0..10
- originality 0..12 (the OPPOSITE of templated defaults)
- motion 0..10  - polish 0..6
Originality anchors: 0-3 untouched UI kit; 4-7 competent-but-familiar SaaS;
8-10 clearly art-directed; 11-12 memorable, gallery-grade.
Return STRICT JSON only with this exact shape:
{"A":{"typography":int,"color":int,"layout":int,"originality":int,"motion":int,"polish":int,"note":"<=20 words"},
 "B":{"typography":int,"color":int,"layout":int,"originality":int,"motion":int,"polish":int,"note":"<=20 words"}}"""

def data_url(path):
    with open(path,"rb") as f: b=base64.standard_b64encode(f.read()).decode()
    ext = "png" if path.lower().endswith("png") else "jpeg"
    return f"data:image/{ext};base64,{b}"

def collect(d):
    blocks=[]
    for fn in ("desktop.png","mobile.png","states.png","interaction.png"):
        p=os.path.join(d,fn)
        if os.path.exists(p):
            blocks.append({"type":"text","text":f"[{fn}]"})
            blocks.append({"type":"image_url","image_url":{"url":data_url(p)}})
    return blocks

def call_judge(dirA, dirB, model):
    # ISOLATED side-effecting call. Returns parsed dict {"A":{...},"B":{...}}.
    from openai import OpenAI
    client = OpenAI()
    content = [{"type":"text","text":RUBRIC},
               {"type":"text","text":"=== SUBMISSION A ==="}, *collect(dirA),
               {"type":"text","text":"=== SUBMISSION B ==="}, *collect(dirB)]
    # GPT-5 family uses max_completion_tokens; json_object mode makes parsing robust.
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role":"user","content":content}],
        max_completion_tokens=700,
        response_format={"type":"json_object"})
    return json.loads(resp.choices[0].message.content)

def aggregate(trials, labelX, labelY):
    out={}
    for label, side in ((labelX,"X"),(labelY,"Y")):
        out[label]={}
        for dim in DIMENSIONS:
            vals=[t[side][dim] for t in trials]
            out[label][dim]=(round(statistics.mean(vals),2),
                             round(statistics.pstdev(vals),2) if len(vals)>1 else 0.0)
        totals=[sum(t[side][dim] for dim in DIMENSIONS) for t in trials]
        out[label]["TOTAL"]=(round(statistics.mean(totals),2),
                             round(statistics.pstdev(totals),2) if len(totals)>1 else 0.0)
    return out

def run(dirX, dirY, labelX, labelY, k, model):
    trials=[]
    for i in range(k):
        swap = random.random()<0.5
        dA,dB = (dirY,dirX) if swap else (dirX,dirY)
        res = call_judge(dA,dB,model)
        X = res["B"] if swap else res["A"]; Y = res["A"] if swap else res["B"]
        trials.append({"X":X,"Y":Y}); print(f"  trial {i+1}/{k} (swap={swap})")
    return aggregate(trials, labelX, labelY)

def combine_with_human(llm_total, human_total, cap=60, flag_at=12):
    # final aesthetic = equal-weight average of the two judges; flag big divergence
    final = round(0.5*llm_total + 0.5*human_total, 2)
    diverged = abs(llm_total - human_total) > flag_at
    return final, diverged

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("dirX"); ap.add_argument("dirY")
    ap.add_argument("--labelX",default="X"); ap.add_argument("--labelY",default="Y")
    ap.add_argument("-k",type=int,default=8)
    ap.add_argument("--model",default="gpt-5.5")  # set exact OpenAI model string
    ap.add_argument("--humanX",type=float,default=None, help="human /60 total for X")
    ap.add_argument("--humanY",type=float,default=None, help="human /60 total for Y")
    a=ap.parse_args()
    rep=run(a.dirX,a.dirY,a.labelX,a.labelY,a.k,a.model)
    print("\n=== LLM AESTHETIC (mean ± std over %d blind trials) ===" % a.k)
    for label,dims in rep.items():
        print(f"\n[{label}]")
        for dim,cap in {**DIMENSIONS,"TOTAL":60}.items():
            m,s=dims[dim]; print(f"  {dim:12s} {m:5.2f} ± {s:4.2f} / {cap}")
    if a.humanX is not None and a.humanY is not None:
        print("\n=== FINAL AESTHETIC (50% human + 50% LLM, /60) ===")
        for label, hv in ((a.labelX,a.humanX),(a.labelY,a.humanY)):
            fin, flag = combine_with_human(rep[label]["TOTAL"][0], hv)
            print(f"  {label:6s} final={fin}/60  (LLM {rep[label]['TOTAL'][0]}, human {hv})"
                  + ("   ⚠ judges diverge >12, review" if flag else ""))

if __name__=="__main__": main()
```

---

## 4. 评分细则（满分 100）

| 大项 | 分值 | 自动化 |
|---|---|---|
| 客观闸门（溢出/报错/JS 预算/focus-visible/reduced-motion/Lighthouse/axe） | 40 | ✅ 全自动 |
| 排版与层级 | 12 | 盲评（人类 + GPT-5.5，各50%） |
| 色彩 | 10 | 盲评 |
| 布局与空间 | 10 | 盲评 |
| 原创性（反模板） | 12 | 盲评 |
| 动效与交互 | 10 | 盲评 |
| 整体完成度 | 6 | 盲评 |

**判罚优先级**：axe critical 违规 / 客观闸门大面积失败 → 直接判负档，美学分不再讨论。两模型客观分都满后，胜负基本由「原创性 + 排版」两项拉开——这正是审美的核心。

---

## 5. 加码项（想再上难度）

1. **断网约束**：禁止任何外链资源（图片须 inline SVG / CSS 绘制），逼出纯手工视觉能力。
2. **指定反套路品牌调性**：如「粗野主义编辑风」「极简奢侈品」「赛博档案馆」，越偏离默认 SaaS 模板越能区分品味。
3. **可访问性硬门槛**：要求屏幕阅读器走查（VoiceOver）配置器全流程可用，作为人工加权项。
4. **性能极限**：把 JS 预算压到 15KB gzip，并要求 LCP < 1.2s。

---

## 6. 一键开赛

```bash
# 起一个本地静态服务（避免 file:// 的 CORS 限制）
python3 -m http.server 8080 -d solution &     # solution/index.html
# 客观闸门
python3 judge/gate_check.py http://localhost:8080/index.html --js-budget-kb 30
bash   judge/run_audit.sh http://localhost:8080/index.html
# 收集两边截图到 shots/glm 与 shots/opus 后，跑盲评：
export OPENAI_API_KEY=...        # LLM 评委用 GPT-5.5（与两位选手均非同源）
# 人类评委先各打一个 /60 总分，传入 --humanX/--humanY 即可自动算最终美学分
python3 judge/llm_judge.py shots/glm shots/opus \
  --labelX glm --labelY opus -k 10 --model gpt-5.5 \
  --humanX 47 --humanY 52
```

> 诚实声明：本文档中 §2 的浏览器审计与 §3.3 的真实 GPT-5.5 API 调用，因本机沙箱无浏览器、无 key 未实际跑通；但两脚本均 `py_compile` 通过，且 LLM 评委的「位置去偏 + 方差聚合 + 人类/LLM 等权合并与分歧标红」核心逻辑已用桩数据单测通过（20 trial 身份还原正确、方差与合并数值正确）。客观闸门的预算与计分算法亦已单测。
