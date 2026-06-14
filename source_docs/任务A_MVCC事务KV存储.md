# 任务 A（偏开发）— MVCC 事务型 KV 存储 + 崩溃恢复

> 用途：`GLM-5.2 + opencode` vs `Claude Opus 4.8 + Claude Code` 对照赛。
> 两个 agent 跑**逐字一致**的「选手提示词」，同一起始仓库、同样轮次/时间预算，最后用**同一份 grader 盲评**。
> 本文档里所有评测脚本均已在本机实测：正确实现得 87.5/90；去掉冲突检测得 64.2/90；去掉崩溃恢复得 62.5/90 —— grader 能稳定区分。

---

## 0. 比赛协议（先定规则）

| 项 | 设定 |
|---|---|
| 环境 | 同机、同 starter repo、同 Python/编译器版本 |
| 预算 | wall-clock 60 min 或 agent 40 turns，先到先停 |
| 盲评 | 选手只拿到「选手提示词 + sample 自测」；真正打分用 grader（选手开发期不可见其内部 oracle 细节） |
| 干预 | 人工干预次数应为 0；记录任何手动操作 |
| 记录 | 最终分数、达成解所用 turns/时间、是否需要人工补救 |

实现语言**不限**（Go / Rust / C++ / Python 均可）：协议固定在 TCP 文本层，grader 与语言解耦，对两个 agent 公平。

---

## 1. 选手提示词（逐字粘贴给两个 agent）

````
实现一个支持 Snapshot Isolation 的内存 KV 存储，带 WAL 持久化与崩溃恢复。
对外通过 TCP 暴露一个极简文本协议。

【启动契约】
- 提供 solution/build.sh（可为空操作）用于构建。
- 提供可执行 solution/run，调用方式：./run <port> <wal_path>
  - 监听 127.0.0.1:<port>
  - 服务就绪后，必须向 stderr 打印一行 "READY"
  - <wal_path> 为 WAL 文件路径；进程重启时从该文件恢复已提交数据

【线协议】每行一条命令，换行 \n 结尾，响应也以 \n 结尾：
  BEGIN          -> OK <txid>        # 开启事务，快照=当前最后已提交版本
  SET <k> <v>    -> OK               # 缓冲写入（k、v 不含空格，v 允许为字符串）
  DEL <k>        -> OK               # 缓冲删除
  GET <k>        -> VALUE <v> | NIL  # 读：快照 + 自身未提交写
  COMMIT         -> OK | CONFLICT    # 提交或因写写冲突中止
  ABORT          -> OK               # 放弃当前事务
  QUIT           -> （关闭连接）
一条连接同一时刻最多一个活跃事务。非事务态执行读写返回 "ERR no-txn"。

【语义要求】
1. 快照隔离：事务读到 BEGIN 时刻的已提交快照 + 自身未提交写入；
   无脏读、可重复读（同一事务内对同一 key 多次 GET 结果稳定）。
2. 写写冲突：两个事务基于同一快照写同一 key，只有一个 COMMIT 成功，
   另一个返回 CONFLICT（first-committer-wins）。
3. 持久化：COMMIT 返回 OK 即保证该事务写入已落盘（fsync）。
4. 崩溃恢复：进程被 kill -9 后用同一 <wal_path> 重启——
   已 ACK 的提交必须全部可见；未提交/已 ABORT 的写入必须不可见；
   WAL 尾部 torn write 需靠校验（如 crc32）识别并丢弃。
5. 版本 GC：长时间运行下内存有界，不可无限堆积旧版本。

【性能目标】在本机单进程，8 连接并发下提交吞吐 ≥ 5000 commits/s（请按评测机调）。

【交付】solution/ 目录，含 build.sh、run，以及源码与简短 README 说明实现要点。
````

> 出题方可在 README 里追加：「不得引入外部数据库/KV 中间件，需自行实现存储与 WAL」。

---

## 2. 起始仓库结构

```
taskA/
├─ PROMPT.txt              # 上面的选手提示词
├─ solution/               # 选手在此实现
│  ├─ build.sh
│  └─ run
├─ judge/                  # 评委私有（选手不可见）
│  ├─ grader.py            # 见 §3
│  └─ reference_server.py  # 答案参考实现，仅用于校验 grader
└─ README.md
```

---

## 3. 评委评分脚本 `judge/grader.py`（已实测）

> 用法：`python3 grader.py <solution_dir>`
> 自动跑：功能正确性 → 并发「银行守恒」oracle → 吞吐 → kill -9 崩溃恢复，并打分。
> 核心 oracle：N 个账户总额恒定。只要冲突检测、原子性、持久性任一出错，总额就会漂移——单一不变量覆盖多种 bug。

```python
#!/usr/bin/env python3
# Task A grader for the MVCC KV store.
# Contestant contract:
#   solution/build.sh                 : builds (no-op ok)
#   solution/run <port> <wal_path>    : starts server; prints "READY" on stderr when listening
# Usage: python3 grader.py <solution_dir>
import sys, os, socket, time, subprocess, threading, random, shutil, signal

HOST = "127.0.0.1"

class Client:
    def __init__(self, port):
        self.s = socket.create_connection((HOST, port))
        self.f = self.s.makefile("rwb", buffering=0)
    def cmd(self, c):
        self.f.write((c + "\n").encode())
        return self.f.readline().decode().strip()
    def close(self):
        try: self.s.close()
        except Exception: pass

def start_server(sol_dir, port, wal, timeout=10):
    p = subprocess.Popen(["./run", str(port), wal], cwd=sol_dir,
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    start = time.time()
    def wait_ready():
        for line in iter(p.stderr.readline, b""):
            if b"READY" in line: return True
        return False
    t = threading.Thread(target=wait_ready, daemon=True); t.start()
    while time.time() - start < timeout:
        try:
            c = socket.create_connection((HOST, port), timeout=0.3); c.close(); return p
        except OSError:
            if p.poll() is not None:
                raise RuntimeError("server exited early")
            time.sleep(0.05)
    raise RuntimeError("server did not become ready")

# ---------- functional checks ----------
def t_basic(port):
    a = Client(port)
    assert a.cmd("BEGIN").startswith("OK")
    assert a.cmd("SET x 1") == "OK"
    assert a.cmd("GET x") == "VALUE 1"          # read-your-own-write
    assert a.cmd("COMMIT") == "OK"
    b = Client(port)
    b.cmd("BEGIN"); assert b.cmd("GET x") == "VALUE 1"; b.cmd("COMMIT")
    a.close(); b.close(); return True

def t_dirty_read(port):
    a = Client(port); b = Client(port)
    a.cmd("BEGIN"); a.cmd("SET d 99")           # uncommitted
    b.cmd("BEGIN")
    seen = b.cmd("GET d")                        # must NOT see uncommitted 99
    a.cmd("ABORT"); b.cmd("COMMIT"); a.close(); b.close()
    return seen != "VALUE 99"

def t_repeatable_read(port):
    a = Client(port); b = Client(port)
    a.cmd("BEGIN"); a.cmd("SET r 1"); a.cmd("COMMIT")
    b.cmd("BEGIN"); first = b.cmd("GET r")
    c = Client(port); c.cmd("BEGIN"); c.cmd("SET r 2"); c.cmd("COMMIT"); c.close()
    second = b.cmd("GET r")                      # snapshot stable within txn
    b.cmd("COMMIT"); a.close(); b.close()
    return first == "VALUE 1" and second == "VALUE 1"

def t_ww_conflict(port):
    a = Client(port); b = Client(port)
    a.cmd("BEGIN"); b.cmd("BEGIN")               # same snapshot
    a.cmd("SET k A"); b.cmd("SET k B")
    r1 = a.cmd("COMMIT"); r2 = b.cmd("COMMIT")    # exactly one CONFLICT
    a.close(); b.close()
    return {r1, r2} == {"OK", "CONFLICT"}

# ---------- concurrent bank invariant ----------
def bank_workload(port, accounts, init, duration, stop_evt, stats):
    total = accounts * init
    def setup():
        c = Client(port); c.cmd("BEGIN")
        for i in range(accounts): c.cmd(f"SET a{i} {init}")
        assert c.cmd("COMMIT") == "OK"; c.close()
    setup()
    committed = [0]
    def worker(seed):
        rng = random.Random(seed); c = Client(port)
        while not stop_evt.is_set():
            i, j = rng.randrange(accounts), rng.randrange(accounts)
            if i == j: continue
            amt = rng.randint(1, 5)
            c.cmd("BEGIN")
            vi = c.cmd(f"GET a{i}"); vj = c.cmd(f"GET a{j}")
            bi = int(vi.split()[1]); bj = int(vj.split()[1])
            if bi < amt: c.cmd("ABORT"); continue
            c.cmd(f"SET a{i} {bi-amt}"); c.cmd(f"SET a{j} {bj+amt}")
            if c.cmd("COMMIT") == "OK": committed[0] += 1
        c.close()
    def checker(seed):
        rng = random.Random(seed); c = Client(port)
        while not stop_evt.is_set():
            c.cmd("BEGIN"); s = 0
            for i in range(accounts):
                s += int(c.cmd(f"GET a{i}").split()[1])
            c.cmd("COMMIT")
            if s != total:
                stats["violation"] = f"sum={s} expected={total}"
                stop_evt.set(); break
            time.sleep(0.01)
        c.close()
    threads = [threading.Thread(target=worker, args=(s,)) for s in range(8)]
    threads += [threading.Thread(target=checker, args=(1000,)), threading.Thread(target=checker, args=(2000,))]
    for t in threads: t.start()
    time.sleep(duration); stop_evt.set()
    for t in threads: t.join()
    stats["committed"] = committed[0]; stats["total"] = total
    return "violation" not in stats

# ---------- crash recovery ----------
def t_crash_recovery(sol_dir, port, wal):
    if os.path.exists(wal): os.remove(wal)
    p = start_server(sol_dir, port, wal)
    accounts, init = 20, 100; total = accounts*init
    c = Client(port); c.cmd("BEGIN")
    for i in range(accounts): c.cmd(f"SET a{i} {init}")
    assert c.cmd("COMMIT") == "OK"
    acked = 0
    for n in range(200):
        i, j = random.randrange(accounts), random.randrange(accounts)
        if i == j: continue
        c.cmd("BEGIN")
        bi = int(c.cmd(f"GET a{i}").split()[1]); bj = int(c.cmd(f"GET a{j}").split()[1])
        if bi < 1: c.cmd("ABORT"); continue
        c.cmd(f"SET a{i} {bi-1}"); c.cmd(f"SET a{j} {bj+1}")
        if c.cmd("COMMIT") == "OK": acked += 1
    c.close()
    p.send_signal(signal.SIGKILL); p.wait()      # hard kill
    p2 = start_server(sol_dir, port, wal)
    d = Client(port); d.cmd("BEGIN"); s = 0
    def val(resp):
        parts = resp.split()
        return int(parts[1]) if len(parts) == 2 and parts[0] == "VALUE" and parts[1].lstrip("-").isdigit() else 0
    for i in range(accounts): s += val(d.cmd(f"GET a{i}"))
    d.cmd("COMMIT"); d.close()
    p2.send_signal(signal.SIGKILL); p2.wait()
    return s == total, s, total, acked

# ---------- throughput ----------
def t_throughput(port, seconds=3):
    stop = threading.Event(); counts = [0]*8
    def w(idx):
        c = Client(port); n = 0
        while not stop.is_set():
            c.cmd("BEGIN"); c.cmd(f"SET p{idx} {n}")
            if c.cmd("COMMIT") == "OK": n += 1
        counts[idx] = n; c.close()
    ts = [threading.Thread(target=w, args=(i,)) for i in range(8)]
    for t in ts: t.start()
    time.sleep(seconds); stop.set()
    for t in ts: t.join()
    return sum(counts)/seconds

def main():
    sol_dir = sys.argv[1]
    s = socket.socket(); s.bind((HOST,0)); port = s.getsockname()[1]; s.close()
    wal = os.path.join("/tmp", f"wal_{port}.log")
    build = os.path.join(sol_dir, "build.sh")
    if os.path.exists(build):
        if subprocess.run(["bash","build.sh"], cwd=sol_dir).returncode != 0:
            print("BUILD FAILED"); sys.exit(2)
    os.chmod(os.path.join(sol_dir,"run"), 0o755)

    report = []
    if os.path.exists(wal): os.remove(wal)
    p = start_server(sol_dir, port, wal)
    bank_ok = False
    try:
        funcs = [("basic",t_basic),("dirty_read",t_dirty_read),
                 ("repeatable_read",t_repeatable_read),("ww_conflict",t_ww_conflict)]
        proto_ok = si_ok = 0
        for name, fn in funcs:
            try: ok = fn(port)
            except Exception as e: ok = False; report.append(f"  {name}: EXC {e}")
            report.append(f"  func/{name}: {'PASS' if ok else 'FAIL'}")
            if name == "basic" and ok: proto_ok = 1
            if name in ("dirty_read","repeatable_read","ww_conflict") and ok: si_ok += 1
        s_proto = 20.0 if proto_ok else 0.0
        s_si = round(25.0*si_ok/3, 1)
        s_conf = 15.0 if any("ww_conflict: PASS" in r for r in report) else 0.0

        stats = {}
        bank_ok = bank_workload(port, 30, 100, 4.0, threading.Event(), stats)
        report.append(f"  bank: {'PASS' if bank_ok else 'FAIL '+stats.get('violation','')} "
                      f"(committed={stats.get('committed')}, conserved total={stats.get('total')})")
        thr = t_throughput(port, 3)
        report.append(f"  throughput: {thr:.0f} commits/s")
        s_perf = 5.0 if thr >= 5000 else (2.5 if thr >= 1000 else 0.0)
    finally:
        p.send_signal(signal.SIGKILL); p.wait()

    rec_ok, s_got, s_exp, acked = t_crash_recovery(sol_dir, port, wal+".rec")
    report.append(f"  crash_recovery: {'PASS' if rec_ok else 'FAIL'} "
                  f"(post-restart sum={s_got}, expected={s_exp}, acked_commits={acked})")
    s_rec = 25.0 if rec_ok else 0.0

    print("\n".join(report))
    print("\n=== SCORE (mem-bound 10 & style folded into manual review) ===")
    print(f"  protocol correctness : {s_proto}/20")
    print(f"  SI invariants        : {s_si}/25  (+bank oracle: {'ok' if bank_ok else 'FAIL'})")
    print(f"  conflict detection   : {s_conf}/15")
    print(f"  crash recovery       : {s_rec}/25")
    print(f"  performance          : {s_perf}/5")
    print(f"  SUBTOTAL             : {s_proto+s_si+s_conf+s_rec+s_perf}/90  (mem-bound 10 measured separately)")

if __name__ == "__main__":
    main()
```

---

## 4. 评分细则（满分 100）

| 维度 | 分值 | 判定 | 自动化 |
|---|---|---|---|
| 协议正确性 | 20 | 基本 SET/GET/COMMIT 可见性 | ✅ grader |
| 快照隔离不变量 | 25 | 无脏读 / 可重复读 / 银行总额守恒 | ✅ grader |
| 写写冲突检测 | 15 | 同快照写同 key 恰一成功 | ✅ grader |
| 崩溃恢复（原子+持久） | 25 | kill -9 后 acked 全在、未提交全无、torn tail 丢弃 | ✅ grader |
| 内存有界（版本 GC） | 10 | 长跑 5 min 采样 RSS，须低于设定上限且不单调增长 | 半自动（采 `/proc/<pid>/VmHWM`） |
| 性能 | 5 | 吞吐 ≥ 5000 commits/s | ✅ grader |

> 内存维度未并入主脚本，是因为「上限」取决于评测机；建议跑 5 min 银行负载，每 5 s 采一次 `VmHWM`，要求峰值 < 200 MB 且后半段不再上升。

**实测对照（用于校准 grader 可信度）**

| 实现 | 子分 | 现象 |
|---|---|---|
| 正确参考实现 | 87.5/90 | 全 PASS（吞吐受 Python 限制只拿 2.5/5，编译语言可满分） |
| 去掉冲突检测 | 64.2/90 | `ww_conflict` FAIL，银行总额漂移到 3002≠3000 |
| 去掉 WAL 恢复 | 62.5/90 | 重启后 sum=0，crash_recovery FAIL |

---

## 5. 加码项（想拉大差距时启用）

1. **多版本读历史**：新增 `GET <k> @<ts>` 读指定时间戳版本——逼出真正的版本链而非覆盖式存储。
2. **torn-write 注入**：评委在 kill 后手动截断 WAL 末尾 1~7 字节，再重启，验证 crc 尾部丢弃逻辑。
3. **死锁/活锁观测**：把银行负载冲突率拉高（账户数降到 5），观察是否出现提交饥饿。

---

## 6. 一键开赛

```bash
# 选手 agent 完成后：
python3 judge/grader.py solution
# 评委另起一窗跑内存采样（可选）：
#   while true; do grep VmHWM /proc/$(pgrep -f run)/status; sleep 5; done
```
