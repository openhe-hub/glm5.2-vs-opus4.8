#!/usr/bin/env python3
# Usage: python3 gen.py <n> <q> <seed> [pquery]
import sys, random
def main():
    n=int(sys.argv[1]); q=int(sys.argv[2]); seed=int(sys.argv[3])
    pquery=float(sys.argv[4]) if len(sys.argv)>4 else 0.35
    rng=random.Random(seed)
    present=set(); present_list=[]; pos={}; lines=[f"{n} {q}"]
    def add_edge():
        for _ in range(20):
            u=rng.randint(1,n); v=rng.randint(1,n)
            if u==v: continue
            if u>v: u,v=v,u
            if (u,v) in present: continue
            present.add((u,v)); pos[(u,v)]=len(present_list); present_list.append((u,v))
            return f"+ {u} {v}"
        return None
    def del_edge():
        if not present_list: return None
        i=rng.randrange(len(present_list)); e=present_list[i]
        last=present_list.pop()
        if i<len(present_list): present_list[i]=last; pos[last]=i
        present.discard(e); pos.pop(e,None)
        return f"- {e[0]} {e[1]}"
    produced=0
    while produced<q:
        r=rng.random()
        if r<pquery: lines.append("?"); produced+=1; continue
        density=len(present_list)/max(1,n)
        if present_list and rng.random()<min(0.5,density): line=del_edge()
        else: line=add_edge()
        if line is None: line=del_edge() or "?"
        lines.append(line); produced+=1
    sys.stdout.write('\n'.join(lines)+'\n')
if __name__=='__main__': main()