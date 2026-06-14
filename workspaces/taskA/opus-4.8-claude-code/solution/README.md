# Snapshot-Isolation KV Store (taskA)

In-memory key/value store with MVCC **snapshot isolation**, append-only **WAL**
with crc32 framing, group-commit fsync durability, and crash recovery. Exposed
over TCP with a line-based text protocol. Pure Go, no external dependencies.

## Build & run

```sh
./build.sh                 # go build -o kvsi .
./run <port> <wal_path>    # listens on 127.0.0.1:<port>, prints "READY" to stderr
```

`run` builds on demand if the binary is missing. On startup the WAL at
`<wal_path>` is replayed before the listener opens, so a restart with the same
path restores all committed data.

## Protocol

```
BEGIN          -> OK <txid>          # snapshot = latest committed version
SET <k> <v>    -> OK                 # buffered write (k,v contain no spaces)
DEL <k>        -> OK                 # buffered delete
GET <k>        -> VALUE <v> | NIL    # snapshot + own uncommitted writes
COMMIT         -> OK | CONFLICT      # first-committer-wins
ABORT          -> OK
QUIT           -> (closes connection)
```

Read/write outside a transaction returns `ERR no-txn`. One active transaction
per connection (`BEGIN` while active returns `ERR txn-active`).

## Implementation notes

**MVCC / snapshot isolation.** Each key holds a newest-first chain of versions
`{ts, value, deleted}`. A transaction captures `snapshot = commitTS` at `BEGIN`.
Reads return the newest committed version with `ts <= snapshot`, overridden by
the transaction's own buffered writes — giving no dirty reads and stable
repeatable reads. Commit timestamps come from a single monotonic counter.

**Write-write conflict (first-committer-wins).** Writes are buffered until
`COMMIT`. A single committer goroutine validates each transaction: if any key in
its write set has a committed version with `ts > snapshot`, someone committed
first and the transaction returns `CONFLICT`; otherwise it gets the next commit
timestamp and is applied. Validation + apply happen under one lock, so two
transactions racing on the same key resolve deterministically.

**Durability (WAL).** Each committed transaction is one self-describing record:
`crc32 | payloadLen | payload`, where the payload holds the commit timestamp and
its ops. The committer drains all pending commits into a batch, appends them, and
issues **one `fsync(2)` per batch (group commit)** before acking — so `COMMIT
-> OK` guarantees the write is flushed. We call the raw `fsync` syscall rather
than `os.File.Sync` (which is the much slower `F_FULLFSYNC` on macOS); plain
fsync flushes to the OS and device, surviving process kill and OS crash. Because
the WAL is append-only and ack happens only after the batch's fsync, no
acknowledged commit can be lost.

**Crash recovery.** On startup the WAL is read record by record; each record's
crc and length are verified. A truncated or corrupt tail (a torn write) fails the
check and is discarded, keeping every fully-written record before it. Replaying
in order reconstructs committed state; aborted/uncommitted writes were never
written to the WAL, so they cannot reappear.

**Version GC (bounded memory).** Old versions no longer visible to any live
snapshot are reclaimed. The GC horizon is the oldest active snapshot (or the
latest commit when none are active). Each write prunes its key's chain past the
horizon (handles hot keys); a background sweep every 500 ms prunes cold keys and
drops keys whose only surviving version is a tombstone visible to everyone.

**Throughput.** Group commit amortizes fsync across concurrent committers. On the
dev machine (Apple Silicon SSD), 8 connections sustain ~19k commits/s, well above
the 5000 commits/s target. (`test_smoke.py` exercises all semantics above,
including a `kill -9` restart, a torn-tail append, and the throughput check.)

## Tests

```sh
python3 test_smoke.py
```
