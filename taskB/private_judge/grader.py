#!/usr/bin/env python3
import sys, os, json, time, subprocess, threading, glob
TL_SEC = 2.0; ML_MB = 256; KILL_GRACE = 0.5
def peak_rss_kb(pid):
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmHWM:"): return int(line.split()[1])
    except Exception:
        pass
    try:
        out = subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)],
                                      stderr=subprocess.DEVNULL, text=True)
        out = out.strip()
        return int(out) if out else None
    except Exception:
        return None
    return None
def run_case(run_path, in_path, tl):
    with open(in_path, "rb") as fin: data = fin.read()
    proc = subprocess.Popen([run_path], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    peak={"kb":0}; stop=threading.Event()
    def sampler():
        while not stop.is_set():
            v=peak_rss_kb(proc.pid)
            if v and v>peak["kb"]: peak["kb"]=v
            time.sleep(0.005)
    t=threading.Thread(target=sampler,daemon=True); t.start()
    start=time.time()
    try:
        out,err=proc.communicate(input=data,timeout=tl)
        elapsed=time.time()-start; verdict="OK"
    except subprocess.TimeoutExpired:
        proc.kill()
        try: proc.communicate(timeout=KILL_GRACE)
        except Exception: pass
        out,err,elapsed,verdict=b"",b"",tl,"TLE"
    stop.set(); t.join(timeout=0.1)
    return verdict,elapsed,peak["kb"],out
def normalize(b):
    return [ln.strip() for ln in b.decode("utf-8","replace").split("\n") if ln.strip()!=""]
def main():
    sol_dir,tests_dir=sys.argv[1],sys.argv[2]
    build=os.path.join(sol_dir,"build.sh")
    if os.path.exists(build):
        print("[build]")
        if subprocess.run(["bash","build.sh"],cwd=sol_dir).returncode!=0:
            print("BUILD FAILED"); sys.exit(2)
    run_path=os.path.join(sol_dir,"run"); os.chmod(run_path,0o755)
    meta={}; mp=os.path.join(tests_dir,"meta.json")
    if os.path.exists(mp): meta=json.load(open(mp))
    cats={"small":[0,0],"large":[0,0],"edge":[0,0]}
    worst_time=0.0; peak_mem=0; tle=0; mle=0
    for in_path in sorted(glob.glob(os.path.join(tests_dir,"*.in"))):
        name=os.path.basename(in_path)[:-3]
        ans_path=os.path.join(tests_dir,name+".ans")
        cat=meta.get(name,{}).get("category","large")
        cats.setdefault(cat,[0,0])[1]+=1
        verdict,elapsed,peak_kb,out=run_case(run_path,in_path,TL_SEC)
        worst_time=max(worst_time,elapsed); peak_mem=max(peak_mem,peak_kb)
        status=verdict
        if verdict=="OK":
            if peak_kb>ML_MB*1024: status="MLE"; mle+=1
            else:
                exp=normalize(open(ans_path,"rb").read()); got=normalize(out)
                if got==exp: status="AC"; cats[cat][0]+=1
                else: status="WA"
        elif verdict=="TLE": tle+=1
        print(f"  {name:18s} {status:4s}  {elapsed:6.3f}s  {peak_kb/1024:6.1f}MB  [{cat}]")
    def pct(c): p,t=cats[c]; return (p/t*100) if t else 100.0
    small_ok=pct("small"); large_ok=pct("large")
    s_small=round(0.30*small_ok,1); s_large=round(0.30*large_ok,1)
    s_perf = 25.0 if (tle==0 and large_ok>=99.0) else (12.0 if tle<=1 else 0.0)
    s_mem  = 10.0 if (mle==0 and peak_mem<=ML_MB*1024) else 0.0
    print("\n=== SCORE (style 5 pts graded manually) ===")
    print(f"  small correctness : {s_small}/30  ({small_ok:.0f}%)")
    print(f"  large correctness : {s_large}/30  ({large_ok:.0f}%)")
    print(f"  performance       : {s_perf}/25   (worst {worst_time:.3f}s, TLE={tle})")
    print(f"  memory            : {s_mem}/10    (peak {peak_mem/1024:.1f}MB, MLE={mle})")
    print(f"  SUBTOTAL          : {s_small+s_large+s_perf+s_mem}/95")
if __name__=="__main__": main()
