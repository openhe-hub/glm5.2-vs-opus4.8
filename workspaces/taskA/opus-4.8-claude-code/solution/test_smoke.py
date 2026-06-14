#!/usr/bin/env python3
"""Functional + crash-recovery + throughput tests for the KV store."""
import socket, subprocess, sys, os, time, threading, tempfile, signal

HOST = "127.0.0.1"

class Conn:
    def __init__(self, port):
        self.s = socket.create_connection((HOST, port))
        self.f = self.s.makefile("rwb")
    def cmd(self, line):
        self.f.write((line + "\n").encode()); self.f.flush()
        return self.f.readline().decode().rstrip("\n")
    def close(self):
        try: self.f.write(b"QUIT\n"); self.f.flush()
        except Exception: pass
        self.s.close()

def wait_ready(proc):
    while True:
        line = proc.stderr.readline()
        if not line:
            raise RuntimeError("server died before READY")
        if line.decode().strip() == "READY":
            return

def start(port, wal):
    p = subprocess.Popen(["./kvsi", str(port), wal], stderr=subprocess.PIPE)
    wait_ready(p)
    return p

def expect(got, want, msg):
    assert got == want, f"{msg}: got {got!r} want {want!r}"
    print(f"  ok: {msg}")

def main():
    port = 19911
    wal = tempfile.mktemp(prefix="wal_")
    if os.path.exists(wal): os.remove(wal)
    p = start(port, wal)
    try:
        # --- basic + snapshot isolation ---
        a = Conn(port); b = Conn(port)
        expect(a.cmd("GET x"), "ERR no-txn", "read outside txn")
        expect(a.cmd("BEGIN").split()[0], "OK", "begin a")
        expect(a.cmd("SET x 1"), "OK", "set x=1")
        expect(a.cmd("GET x"), "VALUE 1", "own write visible")
        expect(a.cmd("COMMIT"), "OK", "commit a")

        expect(b.cmd("BEGIN").split()[0], "OK", "begin b snapshot")
        expect(b.cmd("GET x"), "VALUE 1", "b sees committed x")

        # repeatable read: c begins, a updates x, c must still see old
        c = Conn(port)
        c.cmd("BEGIN")
        expect(c.cmd("GET x"), "VALUE 1", "c initial read")
        a.cmd("BEGIN"); a.cmd("SET x 2"); expect(a.cmd("COMMIT"), "OK", "a commit x=2")
        expect(c.cmd("GET x"), "VALUE 1", "repeatable read (c still sees 1)")
        c.cmd("COMMIT")
        d = Conn(port); d.cmd("BEGIN")
        expect(d.cmd("GET x"), "VALUE 2", "new txn sees x=2")
        d.cmd("COMMIT")

        # --- write-write conflict (first-committer-wins) ---
        t1 = Conn(port); t2 = Conn(port)
        t1.cmd("BEGIN"); t2.cmd("BEGIN")
        t1.cmd("SET k 100"); t2.cmd("SET k 200")
        expect(t1.cmd("COMMIT"), "OK", "t1 commits k")
        expect(t2.cmd("COMMIT"), "CONFLICT", "t2 conflict on k")
        # after conflict, t2 must start fresh
        expect(t2.cmd("GET k"), "ERR no-txn", "t2 has no active txn after conflict")
        t2.cmd("BEGIN"); expect(t2.cmd("GET k"), "VALUE 100", "first-committer-wins value")
        t2.cmd("COMMIT")

        # --- delete semantics ---
        e = Conn(port); e.cmd("BEGIN"); e.cmd("DEL k"); expect(e.cmd("GET k"), "NIL", "own delete visible")
        expect(e.cmd("COMMIT"), "OK", "commit delete")
        f = Conn(port); f.cmd("BEGIN"); expect(f.cmd("GET k"), "NIL", "deleted key gone"); f.cmd("COMMIT")

        # --- abort ---
        g = Conn(port); g.cmd("BEGIN"); g.cmd("SET ab 9"); expect(g.cmd("ABORT"), "OK", "abort")
        h = Conn(port); h.cmd("BEGIN"); expect(h.cmd("GET ab"), "NIL", "aborted write not visible"); h.cmd("COMMIT")

        for cn in (a,b,c,d,t1,t2,e,f,g,h): cn.close()

        # snapshot a few known committed values for recovery check
        chk = Conn(port); chk.cmd("BEGIN")
        x_val = chk.cmd("GET x"); chk.cmd("COMMIT"); chk.close()
        print(f"  pre-crash x = {x_val}")

        # --- crash recovery (kill -9) ---
        # commit a durable value, then hard-kill and restart
        z = Conn(port); z.cmd("BEGIN"); z.cmd("SET durable yes"); expect(z.cmd("COMMIT"), "OK", "commit durable")
        z.close()
        time.sleep(0.05)
        p.send_signal(signal.SIGKILL); p.wait()
        print("  killed -9, restarting...")
        p = start(port, wal)
        r = Conn(port); r.cmd("BEGIN")
        expect(r.cmd("GET durable"), "VALUE yes", "durable commit survived crash")
        expect(r.cmd("GET x"), "VALUE 2", "x survived crash")
        expect(r.cmd("GET k"), "NIL", "deleted k still gone after crash")
        expect(r.cmd("GET ab"), "NIL", "aborted write absent after crash")
        r.cmd("COMMIT"); r.close()

        # --- torn-tail handling: append garbage, must still recover ---
        p.send_signal(signal.SIGKILL); p.wait()
        with open(wal, "ab") as wf:
            wf.write(b"\xde\xad\xbe\xef\x10\x00\x00\x00partialjunk")  # bogus trailing record
        p = start(port, wal)
        r = Conn(port); r.cmd("BEGIN")
        expect(r.cmd("GET durable"), "VALUE yes", "recovery ignores torn tail")
        r.cmd("COMMIT"); r.close()

        # --- throughput: 8 connections, sequential commits each ---
        N_CONN, PER = 8, 4000
        def worker(idx, out):
            cn = Conn(port); cnt = 0
            for i in range(PER):
                cn.cmd("BEGIN")
                cn.cmd(f"SET c{idx}_{i % 50} {i}")
                if cn.cmd("COMMIT") == "OK": cnt += 1
            cn.close(); out[idx] = cnt
        out = [0]*N_CONN
        ts = [threading.Thread(target=worker, args=(i,out)) for i in range(N_CONN)]
        t0 = time.time()
        for t in ts: t.start()
        for t in ts: t.join()
        dt = time.time()-t0
        total = sum(out)
        print(f"  throughput: {total} commits in {dt:.3f}s = {total/dt:.0f} commits/s")
        assert total/dt >= 5000, f"throughput too low: {total/dt:.0f}/s"
        print("  ok: throughput >= 5000 commits/s")

        print("\nALL TESTS PASSED")
    finally:
        try: p.send_signal(signal.SIGKILL); p.wait()
        except Exception: pass
        if os.path.exists(wal): os.remove(wal)

if __name__ == "__main__":
    main()
