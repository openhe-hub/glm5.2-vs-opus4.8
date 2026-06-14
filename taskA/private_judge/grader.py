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