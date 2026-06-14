# MVCC KV store with Snapshot Isolation, WAL & crash recovery

Single-file C++17 implementation (`src/main.cpp`). Build with `./build.sh`,
run with `./run <port> <wal_path>`.

## Architecture

**Versioned store.** Each key maps to a vector of `Version{commit_ts, deleted, value}`
kept in ascending `commit_ts` order. A monotonic counter `g_last_committed_ts`
assigns commit timestamps.

**Snapshot isolation.** `BEGIN` captures `snapshot_ts = g_last_committed_ts` and
records it in `g_active_snapshots`. `GET` returns the buffered write if any,
else the newest committed version with `commit_ts <= snapshot_ts` (no dirty
reads, stable across the transaction). `COMMIT` does first-committer-wins: for
every written key, if the latest committed version has `commit_ts > snapshot_ts`
the transaction aborts with `CONFLICT`, otherwise it applies and wins.

**Group-committed WAL.** A single mutex (`g_mtx`) guards the in-memory state and
makes commit_ts assignment + WAL enqueue atomic, so commit order, apply order
and on-disk WAL order are identical. A dedicated writer thread pulls the pending
queue, concatenates all records into one `write()` + `fsync()`, then signals each
waiter. `COMMIT` applies under the lock, enqueues the record, releases the lock,
and only replies `OK` after its record is fsync'd. Because WAL order equals
apply order, if any transaction B is durable then every transaction that applied
before B is also durable — so applying before fsync never leaks an un-durable
commit past an ACK.

**WAL record format.** `[len:u32][crc32:u32][payload]`, payload =
`[commit_ts:u64][n_entries:u32] ( [klen:u32][key][op:u8][vlen:u32][value] )…`.
Recovery reads records until EOF, a short read, or a CRC mismatch (torn tail),
replays the valid prefix, then `truncate()`s the file to the last valid offset
before reopening for append — so new writes never strand behind a torn tail.

**Version GC.** After each commit, affected keys drop their removable prefix: a
non-newest version `v_i` is kept iff some active snapshot falls in
`[v_i.commit_ts, v_{i+1}.commit_ts)`. This keeps per-key version count bounded
by the number of concurrent snapshots plus one. Verified: ~320 k commits onto
10 keys stays at ~1.5 MB RSS with no growth.

**Networking.** `SO_REUSEADDR` listener on `127.0.0.1`, thread-per-connection
with `TCP_NODELAY`, line-buffered request parser that handles pipelined
commands. Prints `READY` to stderr once listening.

## Performance

On the dev machine (Apple clang `-O3`, localhost), measured with a C client
doing `BEGIN/SET/GET/COMMIT` per transaction:

| workload | throughput |
| --- | --- |
| 8 conns, pipelined | ~30 000 commits/s |
| 8 conns, one RTT per command | ~18 000 commits/s |
| 8 conns, 10 hot keys, full churn | ~37 000 commits/s |

The group-commit writer amortizes fsync across concurrent committers; raw
fsync on this box is ~21 µs, so throughput scales well past the 5 000/s target.

## Files
- `src/main.cpp` — full implementation.
- `build.sh` — compiles `bin/kvserver` with clang++ (falls back to g++).
- `run` — execs `bin/kvserver <port> <wal_path>`.
