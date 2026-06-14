#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <utility>
#include <unordered_map>
#include <chrono>
#include <algorithm>
using namespace std;

static uint64_t splitmix64(uint64_t x) {
    x += 0x9e3779b97f4a7c15;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9;
    x = (x ^ (x >> 27)) * 0x94d049bb133111eb;
    return x ^ (x >> 31);
}
struct CustomHash {
    size_t operator()(uint64_t x) const {
        static const uint64_t FIXED_RANDOM =
            chrono::steady_clock::now().time_since_epoch().count();
        return splitmix64(x + FIXED_RANDOM);
    }
};

struct DSU {
    vector<int> parent, sz;
    vector<int> cnt;       // cnt[s] = number of components of size s
    int cur_max;
    vector<pair<int,int>> hist;   // (v_attached, u_old_size) or (-1,-1) for no-op
    vector<int> max_hist;         // saved cur_max before each unite

    void init(int n) {
        parent.resize((size_t)n + 1);
        sz.assign((size_t)n + 1, 1);
        cnt.assign((size_t)n + 2, 0);
        for (int i = 1; i <= n; i++) parent[i] = i;
        cnt[1] = n;
        cur_max = (n > 0) ? 1 : 0;
    }

    int find(int x) {
        while (parent[x] != x) x = parent[x];
        return x;
    }

    void unite(int u, int v) {
        u = find(u); v = find(v);
        if (u == v) {
            hist.push_back({-1, -1});
            max_hist.push_back(cur_max);
            return;
        }
        if (sz[u] < sz[v]) swap(u, v);
        int su = sz[u], sv = sz[v];
        parent[v] = u;
        sz[u] = su + sv;
        cnt[su]--; cnt[sv]--; cnt[su + sv]++;
        hist.push_back({v, su});
        max_hist.push_back(cur_max);
        if (su + sv > cur_max) cur_max = su + sv;
    }

    void rollback() {
        auto p = hist.back();
        hist.pop_back();
        cur_max = max_hist.back();
        max_hist.pop_back();
        int v = p.first, su = p.second;
        if (v == -1) return;
        int u = parent[v];
        int combined = sz[u];
        sz[u] = su;
        parent[v] = v;
        cnt[combined]--;
        cnt[su]++;
        cnt[sz[v]]++;
    }
};

static DSU dsu;
static vector<vector<pair<int,int>>> tree;
static int qid_at_time[300005];
static vector<int> ans;

static void insert(int node, int l, int r, int ql, int qr, int u, int v) {
    if (ql > qr || qr < l || r < ql) return;
    if (ql <= l && r <= qr) {
        tree[node].push_back({u, v});
        return;
    }
    int mid = (l + r) >> 1;
    insert(node * 2, l, mid, ql, qr, u, v);
    insert(node * 2 + 1, mid + 1, r, ql, qr, u, v);
}

static void solve(int node, int l, int r) {
    for (auto &e : tree[node]) dsu.unite(e.first, e.second);
    if (l == r) {
        if (qid_at_time[l]) ans[qid_at_time[l]] = dsu.cur_max;
    } else {
        int mid = (l + r) >> 1;
        solve(node * 2, l, mid);
        solve(node * 2 + 1, mid + 1, r);
    }
    for (size_t i = 0; i < tree[node].size(); i++) dsu.rollback();
}

static string readall() {
    string s;
    char tmp[1 << 16];
    size_t k;
    while ((k = fread(tmp, 1, sizeof(tmp), stdin)) > 0)
        s.append(tmp, k);
    return s;
}

int main() {
    string data = readall();
    size_t pos = 0;
    auto skipws = [&]() {
        while (pos < data.size() && (unsigned char)data[pos] <= ' ') pos++;
    };
    auto readInt = [&]() -> long long {
        skipws();
        bool neg = false;
        if (pos < data.size() && data[pos] == '-') { neg = true; pos++; }
        long long x = 0;
        while (pos < data.size() && data[pos] >= '0' && data[pos] <= '9') {
            x = x * 10 + (data[pos] - '0'); pos++;
        }
        return neg ? -x : x;
    };
    auto readChar = [&]() -> char {
        skipws();
        return pos < data.size() ? data[pos++] : 0;
    };

    int n = (int)readInt();
    int q = (int)readInt();

    dsu.init(n);
    tree.assign((size_t)4 * q + 10, {});
    int query_count = 0;

    unordered_map<long long, int, CustomHash> add_time;
    add_time.reserve((size_t)q * 2 + 16);

    for (int t = 1; t <= q; t++) {
        char op = readChar();
        if (op == '?') {
            query_count++;
            qid_at_time[t] = query_count;
        } else {
            int u = (int)readInt();
            int v = (int)readInt();
            int a = min(u, v), b = max(u, v);
            long long key = ((long long)a << 32) | (long long)(unsigned int)b;
            if (op == '-') {
                auto it = add_time.find(key);
                int at = it->second;
                add_time.erase(it);
                int L = at + 1, R = t - 1;
                if (L <= R) insert(1, 1, q, L, R, a, b);
            } else { // '+'
                add_time[key] = t;
            }
        }
    }

    for (auto &kv : add_time) {
        int at = kv.second;
        int L = at + 1, R = q;
        long long key = kv.first;
        int a = (int)(key >> 32);
        int b = (int)(key & 0xFFFFFFFFu);
        if (L <= R) insert(1, 1, q, L, R, a, b);
    }

    ans.assign((size_t)query_count + 1, 0);
    if (q >= 1) solve(1, 1, q);

    string out;
    out.reserve((size_t)query_count * 8 + 16);
    for (int i = 1; i <= query_count; i++) {
        out += to_string(ans[i]);
        out += '\n';
    }
    fwrite(out.data(), 1, out.size(), stdout);

    return 0;
}
