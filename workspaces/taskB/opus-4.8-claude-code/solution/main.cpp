#include <cstdio>
#include <vector>
#include <unordered_map>
#include <cstdint>
using namespace std;

// ---------- fast input ----------
static const int BUFSZ = 1 << 22;
static char ibuf[BUFSZ];
static int ipos = 0, ilen = 0;
static inline int gc() {
    if (ipos == ilen) {
        ilen = (int)fread(ibuf, 1, BUFSZ, stdin);
        ipos = 0;
        if (ilen == 0) return -1;
    }
    return ibuf[ipos++];
}
static inline bool readInt(int &out) {
    int c = gc();
    while (c != '-' && (c < '0' || c > '9')) {
        if (c == -1) return false;
        c = gc();
    }
    int sgn = 1;
    if (c == '-') { sgn = -1; c = gc(); }
    int x = 0;
    while (c >= '0' && c <= '9') { x = x * 10 + (c - '0'); c = gc(); }
    out = x * sgn;
    return true;
}
// read a single non-space token's first char (for the operation symbol)
static inline int readOp() {
    int c = gc();
    while (c == ' ' || c == '\n' || c == '\r' || c == '\t') c = gc();
    return c; // '+', '-', '?' or -1
}

// ---------- DSU with rollback ----------
static int par[300005], rnk[300005], sz_[300005];
static int maxComp;

struct Change { int ra, rb; int prevMax; bool incRank; };
static vector<Change> hist;

static inline int findRoot(int x) {
    while (par[x] != x) x = par[x];
    return x;
}

static inline void unite(int u, int v) {
    int ru = findRoot(u), rv = findRoot(v);
    if (ru == rv) {
        hist.push_back({-1, -1, maxComp, false});
        return;
    }
    if (rnk[ru] < rnk[rv]) { int t = ru; ru = rv; rv = t; }
    int prevMax = maxComp;
    bool incRank = false;
    par[rv] = ru;
    sz_[ru] += sz_[rv];
    if (rnk[ru] == rnk[rv]) { rnk[ru]++; incRank = true; }
    if (sz_[ru] > maxComp) maxComp = sz_[ru];
    hist.push_back({ru, rv, prevMax, incRank});
}

static inline void rollbackTo(size_t snap) {
    while (hist.size() > snap) {
        Change c = hist.back();
        hist.pop_back();
        if (c.ra != -1) {
            if (c.incRank) rnk[c.ra]--;
            sz_[c.ra] -= sz_[c.rb];
            par[c.rb] = c.rb;
        }
        maxComp = c.prevMax;
    }
}

// ---------- segment tree over timeline [0, T-1] ----------
static int T;
static vector<pair<int,int>> *tree;

static void addEdge(int node, int l, int r, int ql, int qr, int u, int v) {
    if (qr < l || r < ql) return;
    if (ql <= l && r <= qr) {
        tree[node].push_back({u, v});
        return;
    }
    int mid = (l + r) >> 1;
    addEdge(node << 1, l, mid, ql, qr, u, v);
    addEdge(node << 1 | 1, mid + 1, r, ql, qr, u, v);
}

static unsigned char *isQuery;
static int *answer;

static void dfs(int node, int l, int r) {
    size_t snap = hist.size();
    for (auto &e : tree[node]) unite(e.first, e.second);
    if (l == r) {
        if (isQuery[l]) answer[l] = maxComp;
    } else {
        int mid = (l + r) >> 1;
        dfs(node << 1, l, mid);
        dfs(node << 1 | 1, mid + 1, r);
    }
    rollbackTo(snap);
}

int main() {
    int n, q;
    if (!readInt(n)) return 0;
    readInt(q);

    T = q;
    tree = new vector<pair<int,int>>[(size_t)4 * q + 4];
    isQuery = new unsigned char[q];
    answer = new int[q];
    for (int i = 0; i < q; i++) { isQuery[i] = 0; answer[i] = 0; }

    for (int i = 1; i <= n; i++) { par[i] = i; rnk[i] = 0; sz_[i] = 1; }
    maxComp = (n >= 1) ? 1 : 0;

    // edge -> index when added
    unordered_map<long long, int> active;
    active.reserve(1 << 16);

    auto keyOf = [&](int u, int v) -> long long {
        if (u > v) { int t = u; u = v; v = t; }
        return (long long)u * (long long)(n + 1) + v;
    };

    for (int i = 0; i < q; i++) {
        int op = readOp();
        if (op == '+') {
            int u, v; readInt(u); readInt(v);
            active[keyOf(u, v)] = i;
        } else if (op == '-') {
            int u, v; readInt(u); readInt(v);
            long long k = keyOf(u, v);
            auto it = active.find(k);
            int start = it->second;
            active.erase(it);
            // edge present during operations [start, i-1]
            if (start <= i - 1) addEdge(1, 0, T - 1, start, i - 1, u, v);
        } else { // '?'
            isQuery[i] = 1;
        }
    }
    // edges still active at the end: present through [start, q-1]
    for (auto &kv : active) {
        long long k = kv.first;
        int start = kv.second;
        int v = (int)(k % (long long)(n + 1));
        int u = (int)(k / (long long)(n + 1));
        addEdge(1, 0, T - 1, start, q - 1, u, v);
    }

    hist.reserve(1 << 20);
    dfs(1, 0, T - 1);

    // output answers in order
    string out;
    out.reserve((size_t)q * 3);
    char tmp[16];
    for (int i = 0; i < q; i++) {
        if (isQuery[i]) {
            int len = 0;
            int x = answer[i];
            if (x == 0) tmp[len++] = '0';
            else { while (x > 0) { tmp[len++] = char('0' + x % 10); x /= 10; } }
            while (len > 0) out.push_back(tmp[--len]);
            out.push_back('\n');
        }
    }
    fwrite(out.data(), 1, out.size(), stdout);
    return 0;
}
