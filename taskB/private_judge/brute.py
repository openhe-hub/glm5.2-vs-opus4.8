#!/usr/bin/env python3
import sys
from collections import defaultdict, deque
def main():
    data = sys.stdin.read().split('\n'); idx = 0
    n, q = map(int, data[idx].split()); idx += 1
    adj = defaultdict(set); out = []
    for _ in range(q):
        parts = data[idx].split(); idx += 1
        if parts[0] == '?':
            seen = [False]*(n+1); best = 0
            for s in range(1, n+1):
                if seen[s]: continue
                cnt = 0; dq = deque([s]); seen[s] = True
                while dq:
                    x = dq.popleft(); cnt += 1
                    for y in adj[x]:
                        if not seen[y]: seen[y] = True; dq.append(y)
                best = max(best, cnt)
            out.append(str(best))
        else:
            u, v = int(parts[1]), int(parts[2])
            if parts[0] == '+': adj[u].add(v); adj[v].add(u)
            else: adj[u].discard(v); adj[v].discard(u)
    sys.stdout.write('\n'.join(out) + ('\n' if out else ''))
if __name__ == '__main__': main()