// MVCC in-memory KV store with Snapshot Isolation, WAL persistence & crash recovery.
//
// Design summary:
//   * Per-key version chain (ascending commit_ts). Reads at snapshot scan from
//     the newest version backwards to the first with commit_ts <= snapshot.
//   * Write-write conflict = first-committer-wins: on COMMIT, if the latest
//     committed version of any written key has commit_ts > my snapshot, CONFLICT.
//   * Group commit via a dedicated WAL writer thread: many short transactions
//     share one write+fsync. COMMIT applies to the in-memory store first
//     (under the global lock), enqueues an ordered WAL record, then waits for
//     the writer's fsync before replying OK. Apply order == WAL order, so on
//     recovery every ACKed commit is present.
//   * Each WAL record = [len(4)][crc32(4)][payload]. Recovery stops at the
//     first record that fails length/CRC checks (torn tail) and truncates it.
//   * Version GC: a version older than the newest version readable by the
//     oldest active snapshot is unreclaimable only if some active snapshot
//     falls in its visibility window; we drop the resulting removable prefix.

#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <signal.h>
#include <errno.h>
#include <string.h>
#include <algorithm>
#include <set>

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

// ===================== CRC32 (IEEE 802.3, reflected) =====================
static uint32_t g_crc_table[256];
static void init_crc() {
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int k = 0; k < 8; k++)
            c = (c & 1) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
        g_crc_table[i] = c;
    }
}
static uint32_t crc32_compute(const uint8_t* data, size_t len) {
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++)
        c = g_crc_table[(c ^ data[i]) & 0xFFu] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

// ===================== Little-endian serialization =====================
static void put_u32(std::string& s, uint32_t v) {
    s.push_back((char)(v & 0xFF));
    s.push_back((char)((v >> 8) & 0xFF));
    s.push_back((char)((v >> 16) & 0xFF));
    s.push_back((char)((v >> 24) & 0xFF));
}
static void put_u64(std::string& s, uint64_t v) {
    for (int i = 0; i < 8; i++) s.push_back((char)((v >> (i * 8)) & 0xFF));
}
static uint32_t get_u32(const uint8_t* p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint64_t get_u64(const uint8_t* p) {
    uint64_t v = 0;
    for (int i = 0; i < 8; i++) v |= (uint64_t)p[i] << (i * 8);
    return v;
}

// ===================== MVCC store =====================
struct Version {
    uint64_t commit_ts;
    bool deleted;
    std::string value;
};

static std::mutex g_mtx;
static std::unordered_map<std::string, std::vector<Version>> g_store;
static uint64_t g_last_committed_ts = 0;
static std::multiset<uint64_t> g_active_snapshots;
static std::atomic<uint64_t> g_txid{0};

// Drop the removable prefix of a key's version chain.
// `versions` is sorted ascending by commit_ts. v_i (i < n-1) is needed iff some
// active snapshot lies in [v_i.commit_ts, v_{i+1}.commit_ts); v_{n-1} is always kept.
static void gc_key(std::vector<Version>& versions) {
    const int n = (int)versions.size();
    if (n <= 1) return;
    int first_keep = 0;
    for (int i = 0; i < n - 1; i++) {
        uint64_t lo = versions[i].commit_ts;
        uint64_t hi = versions[i + 1].commit_ts;
        auto it = g_active_snapshots.lower_bound(lo);
        if (it != g_active_snapshots.end() && *it < hi) {
            first_keep = i;
            goto done;
        }
        first_keep = i + 1;
    }
done:
    if (first_keep > 0) {
        versions.erase(versions.begin(), versions.begin() + first_keep);
    }
}

// ===================== WAL =====================
struct WalJob {
    std::string record;  // [len][crc][payload]
    std::mutex mtx;
    std::condition_variable cv;
    bool done = false;
};

static std::mutex g_wal_qmtx;
static std::condition_variable g_wal_cv;
static std::vector<WalJob*> g_wal_pending;
static int g_wal_fd = -1;

// Concatenate pending records, write once, fsync once, signal each waiter.
static void wal_writer_loop() {
    std::vector<WalJob*> batch;
    std::string all;
    while (true) {
        {
            std::unique_lock<std::mutex> lk(g_wal_qmtx);
            g_wal_cv.wait(lk, [] { return !g_wal_pending.empty(); });
            batch.swap(g_wal_pending);
        }
        all.clear();
        for (auto* job : batch) all += job->record;
        const char* p = all.data();
        size_t remaining = all.size();
        while (remaining > 0) {
            ssize_t n = write(g_wal_fd, p, remaining);
            if (n < 0) {
                if (errno == EINTR) continue;
                perror("write wal");
                _exit(1);
            }
            p += n;
            remaining -= (size_t)n;
        }
        fsync(g_wal_fd);
        for (auto* job : batch) {
            {
                std::lock_guard<std::mutex> lk(job->mtx);
                job->done = true;
                job->cv.notify_one();  // notify under lock so the cv stays valid
            }
        }
        batch.clear();
    }
}

static void wal_enqueue(WalJob* job) {
    std::lock_guard<std::mutex> lk(g_wal_qmtx);
    g_wal_pending.push_back(job);
    g_wal_cv.notify_one();
}

// ===================== Recovery =====================
static size_t g_recovered_size = 0;

static void recover(const std::string& path) {
    int fd = open(path.c_str(), O_RDONLY);
    if (fd < 0) return;

    size_t valid_offset = 0;
    auto read_full = [&](uint8_t* buf, size_t n) -> bool {
        size_t got = 0;
        while (got < n) {
            ssize_t r = read(fd, buf + got, n - got);
            if (r == 0) return false;
            if (r < 0) {
                if (errno == EINTR) continue;
                return false;
            }
            got += (size_t)r;
        }
        return true;
    };

    while (true) {
        uint8_t hdr[8];
        if (!read_full(hdr, 8)) break;
        uint32_t len = get_u32(hdr);
        uint32_t crc = get_u32(hdr + 4);
        if (len == 0 || len > (1u << 28)) break;  // sanity bound (256MB)
        std::vector<uint8_t> payload(len);
        if (!read_full(payload.data(), len)) break;           // torn tail
        if (crc32_compute(payload.data(), len) != crc) break;  // corrupt tail
        if (len < 12) break;                                   // malformed
        uint64_t commit_ts = get_u64(payload.data());
        uint32_t num_entries = get_u32(payload.data() + 8);
        size_t off = 12;
        bool ok = true;
        for (uint32_t i = 0; i < num_entries; i++) {
            if (off + 4 > len) { ok = false; break; }
            uint32_t klen = get_u32(payload.data() + off); off += 4;
            if (off + klen > len) { ok = false; break; }
            std::string key((const char*)payload.data() + off, klen); off += klen;
            if (off + 1 > len) { ok = false; break; }
            uint8_t op = payload[off]; off += 1;
            if (off + 4 > len) { ok = false; break; }
            uint32_t vlen = get_u32(payload.data() + off); off += 4;
            if (off + vlen > len) { ok = false; break; }
            std::string value((const char*)payload.data() + off, vlen); off += vlen;
            Version v;
            v.commit_ts = commit_ts;
            v.deleted = (op == 1);
            v.value = std::move(value);
            g_store[std::move(key)].push_back(std::move(v));
        }
        if (!ok) break;  // should not happen (crc passed) but be safe
        if (commit_ts > g_last_committed_ts) g_last_committed_ts = commit_ts;
        valid_offset += 8 + len;
    }
    close(fd);
    g_recovered_size = valid_offset;
}

// ===================== Network helpers =====================
static bool write_all(int fd, const char* data, size_t len) {
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = write(fd, data + sent, len - sent);
        if (n < 0) {
            if (errno == EINTR) continue;
            return false;
        }
        sent += (size_t)n;
    }
    return true;
}

// ===================== Connection handler =====================
struct TxnState {
    bool active = false;
    uint64_t txid = 0;
    uint64_t snapshot_ts = 0;
    // key -> (op, value); op: 0=SET, 1=DEL
    std::unordered_map<std::string, std::pair<uint8_t, std::string>> write_set;
};

static void erase_snapshot(uint64_t snap) {
    auto it = g_active_snapshots.find(snap);
    if (it != g_active_snapshots.end()) g_active_snapshots.erase(it);
}

static void handle_conn(int conn_fd) {
    int one = 1;
    setsockopt(conn_fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));

    std::string inbuf;
    char rbuf[8192];
    std::string outbuf;
    TxnState txn;

    auto respond = [&](const std::string& s) {
        outbuf += s;
        outbuf.push_back('\n');
    };
    auto cleanup_txn = [&]() {
        if (txn.active) {
            std::lock_guard<std::mutex> lk(g_mtx);
            erase_snapshot(txn.snapshot_ts);
            txn.active = false;
            txn.write_set.clear();
        }
    };
    auto flush = [&]() -> bool {
        if (outbuf.empty()) return true;
        bool ok = write_all(conn_fd, outbuf.data(), outbuf.size());
        outbuf.clear();
        return ok;
    };

    while (true) {
        if (!flush()) { cleanup_txn(); close(conn_fd); return; }

        size_t nl;
        while ((nl = inbuf.find('\n')) == std::string::npos) {
            ssize_t n = read(conn_fd, rbuf, sizeof(rbuf));
            if (n < 0) {
                if (errno == EINTR) continue;
                cleanup_txn();
                close(conn_fd);
                return;
            }
            if (n == 0) {
                cleanup_txn();
                close(conn_fd);
                return;
            }
            inbuf.append(rbuf, (size_t)n);
        }

        std::string line = inbuf.substr(0, nl);
        inbuf.erase(0, nl + 1);
        if (!line.empty() && line.back() == '\r') line.pop_back();

        size_t sp1 = line.find(' ');
        std::string cmd = (sp1 == std::string::npos) ? line : line.substr(0, sp1);

        if (cmd == "BEGIN") {
            if (txn.active) { respond("ERR nested-txn"); continue; }
            uint64_t snap;
            {
                std::lock_guard<std::mutex> lk(g_mtx);
                snap = g_last_committed_ts;
                g_active_snapshots.insert(snap);
            }
            uint64_t tid = ++g_txid;
            txn.active = true;
            txn.snapshot_ts = snap;
            txn.txid = tid;
            txn.write_set.clear();
            respond("OK " + std::to_string(tid));
        } else if (cmd == "SET" || cmd == "DEL") {
            if (!txn.active) { respond("ERR no-txn"); continue; }
            if (sp1 == std::string::npos) { respond("ERR syntax"); continue; }
            size_t key_start = sp1 + 1;
            if (cmd == "SET") {
                size_t sp2 = line.find(' ', key_start);
                if (sp2 == std::string::npos) { respond("ERR syntax"); continue; }
                std::string key = line.substr(key_start, sp2 - key_start);
                std::string value = line.substr(sp2 + 1);
                txn.write_set[std::move(key)] = {0, std::move(value)};
            } else {
                std::string key = line.substr(key_start);
                txn.write_set[std::move(key)] = {1, std::string()};
            }
            respond("OK");
        } else if (cmd == "GET") {
            if (!txn.active) { respond("ERR no-txn"); continue; }
            if (sp1 == std::string::npos) { respond("ERR syntax"); continue; }
            std::string key = line.substr(sp1 + 1);
            auto ws_it = txn.write_set.find(key);
            if (ws_it != txn.write_set.end()) {
                if (ws_it->second.first == 1) respond("NIL");
                else respond("VALUE " + ws_it->second.second);
            } else {
                std::lock_guard<std::mutex> lk(g_mtx);
                auto it = g_store.find(key);
                if (it == g_store.end() || it->second.empty()) {
                    respond("NIL");
                } else {
                    const Version* found = nullptr;
                    for (auto v_it = it->second.rbegin(); v_it != it->second.rend(); ++v_it) {
                        if (v_it->commit_ts <= txn.snapshot_ts) { found = &*v_it; break; }
                    }
                    if (found && !found->deleted) respond("VALUE " + found->value);
                    else respond("NIL");
                }
            }
        } else if (cmd == "COMMIT") {
            if (!txn.active) { respond("ERR no-txn"); continue; }
            WalJob job;
            bool committed;
            {
                std::lock_guard<std::mutex> lk(g_mtx);
                bool conflict = false;
                for (auto& kv : txn.write_set) {
                    auto it = g_store.find(kv.first);
                    if (it != g_store.end() && !it->second.empty() &&
                        it->second.back().commit_ts > txn.snapshot_ts) {
                        conflict = true;
                        break;
                    }
                }
                if (conflict) {
                    committed = false;
                } else {
                    uint64_t commit_ts = ++g_last_committed_ts;
                    std::string payload;
                    put_u64(payload, commit_ts);
                    put_u32(payload, (uint32_t)txn.write_set.size());
                    for (auto& kv : txn.write_set) {
                        put_u32(payload, (uint32_t)kv.first.size());
                        payload.append(kv.first);
                        payload.push_back((char)kv.second.first);
                        put_u32(payload, (uint32_t)kv.second.second.size());
                        payload.append(kv.second.second);
                        Version ver;
                        ver.commit_ts = commit_ts;
                        ver.deleted = (kv.second.first == 1);
                        ver.value = kv.second.second;
                        g_store[kv.first].push_back(std::move(ver));
                    }
                    for (auto& kv : txn.write_set) {
                        auto it = g_store.find(kv.first);
                        if (it != g_store.end()) gc_key(it->second);
                    }
                    uint32_t crc = crc32_compute((const uint8_t*)payload.data(), payload.size());
                    job.record.clear();
                    put_u32(job.record, (uint32_t)payload.size());
                    put_u32(job.record, crc);
                    job.record.append(payload);
                    wal_enqueue(&job);
                    committed = true;
                }
            }
            if (committed) {
                std::unique_lock<std::mutex> lk(job.mtx);
                job.cv.wait(lk, [&] { return job.done; });
                respond("OK");
            } else {
                respond("CONFLICT");
            }
            {
                std::lock_guard<std::mutex> lk(g_mtx);
                erase_snapshot(txn.snapshot_ts);
            }
            txn.active = false;
            txn.write_set.clear();
        } else if (cmd == "ABORT") {
            if (!txn.active) { respond("ERR no-txn"); continue; }
            {
                std::lock_guard<std::mutex> lk(g_mtx);
                erase_snapshot(txn.snapshot_ts);
            }
            txn.active = false;
            txn.write_set.clear();
            respond("OK");
        } else if (cmd == "QUIT") {
            flush();
            cleanup_txn();
            close(conn_fd);
            return;
        } else {
            // unknown / empty command -> still reply one line so the client
            // never desyncs waiting for a response.
            respond("ERR unknown-cmd");
        }
    }
}

// ===================== Main =====================
int main(int argc, char** argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: %s <port> <wal_path>\n", argv[0]);
        return 1;
    }
    int port = atoi(argv[1]);
    std::string wal_path = argv[2];

    signal(SIGPIPE, SIG_IGN);
    init_crc();

    recover(wal_path);

    if (truncate(wal_path.c_str(), (off_t)g_recovered_size) < 0 && errno != ENOENT) {
        // non-fatal
    }
    g_wal_fd = open(wal_path.c_str(), O_WRONLY | O_APPEND | O_CREAT, 0644);
    if (g_wal_fd < 0) { perror("open wal"); return 1; }

    std::thread wal_thread(wal_writer_loop);
    wal_thread.detach();

    int listen_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (listen_fd < 0) { perror("socket"); return 1; }
    int opt = 1;
    setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(listen_fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("bind");
        return 1;
    }
    if (listen(listen_fd, 128) < 0) { perror("listen"); return 1; }

    fprintf(stderr, "READY\n");
    fflush(stderr);

    while (true) {
        int conn_fd = accept(listen_fd, nullptr, nullptr);
        if (conn_fd < 0) {
            if (errno == EINTR) continue;
            continue;
        }
        std::thread([conn_fd] { handle_conn(conn_fd); }).detach();
    }
    return 0;
}
