// Snapshot-Isolation in-memory KV store with WAL persistence + crash recovery.
//
// Wire protocol (one command per line, terminated by '\n'):
//   BEGIN          -> OK <txid>
//   SET <k> <v>    -> OK
//   DEL <k>        -> OK
//   GET <k>        -> VALUE <v> | NIL
//   COMMIT         -> OK | CONFLICT
//   ABORT          -> OK
//   QUIT           -> (connection closed)
//
// Concurrency control is MVCC snapshot isolation with first-committer-wins
// write-write conflict detection. Durability uses an append-only WAL with
// per-record crc32 framing; commits are made durable via group-commit fsync.
package main

import (
	"bufio"
	"encoding/binary"
	"errors"
	"fmt"
	"hash/crc32"
	"io"
	"net"
	"os"
	"strconv"
	"sync"
	"syscall"
	"time"
)

// ---------------------------------------------------------------------------
// MVCC store
// ---------------------------------------------------------------------------

// version is one node in a per-key version chain (newest first via prev).
type version struct {
	ts      uint64 // commit timestamp that produced this version
	val     string
	deleted bool
	prev    *version
}

type store struct {
	mu       sync.RWMutex
	data     map[string]*version
	commitTS uint64 // last committed timestamp (== latest snapshot)

	// activeSnaps is a refcount of snapshot timestamps held by live txns,
	// used to compute the GC horizon (oldest snapshot still readable).
	activeSnaps map[uint64]int
}

func newStore() *store {
	return &store{
		data:        make(map[string]*version),
		activeSnaps: make(map[uint64]int),
	}
}

// beginSnapshot registers a new reader at the current committed version.
func (s *store) beginSnapshot() uint64 {
	s.mu.Lock()
	snap := s.commitTS
	s.activeSnaps[snap]++
	s.mu.Unlock()
	return snap
}

// endSnapshotLocked drops one reference to a snapshot. Caller holds s.mu.
func (s *store) endSnapshotLocked(snap uint64) {
	if c := s.activeSnaps[snap]; c <= 1 {
		delete(s.activeSnaps, snap)
	} else {
		s.activeSnaps[snap] = c - 1
	}
}

func (s *store) endSnapshot(snap uint64) {
	s.mu.Lock()
	s.endSnapshotLocked(snap)
	s.mu.Unlock()
}

// readVisible returns the value visible at snapshot ts (committed only).
func (s *store) readVisible(key string, snap uint64) (string, bool) {
	s.mu.RLock()
	v := s.data[key]
	for v != nil && v.ts > snap {
		v = v.prev
	}
	s.mu.RUnlock()
	if v == nil || v.deleted {
		return "", false
	}
	return v.val, true
}

// gcHorizonLocked returns the oldest snapshot timestamp any live txn can read.
// Versions strictly older than the newest version with ts <= horizon are dead.
// Caller holds s.mu (read or write).
func (s *store) gcHorizonLocked() uint64 {
	if len(s.activeSnaps) == 0 {
		return s.commitTS
	}
	min := ^uint64(0)
	for ts := range s.activeSnaps {
		if ts < min {
			min = ts
		}
	}
	return min
}

// pruneChainLocked drops versions that no live snapshot can observe.
// We keep the newest version with ts <= horizon (and everything newer);
// anything older than that is unreachable. Caller holds s.mu (write).
func pruneChainLocked(head *version, horizon uint64) {
	v := head
	for v != nil {
		if v.ts <= horizon {
			// v is the newest version visible at the horizon; older ones are dead.
			v.prev = nil
			return
		}
		v = v.prev
	}
}

// ---------------------------------------------------------------------------
// Transaction
// ---------------------------------------------------------------------------

type writeOp struct {
	val     string
	deleted bool
}

type txn struct {
	id       uint64
	snapshot uint64
	writes   map[string]writeOp
}

// ---------------------------------------------------------------------------
// WAL
// ---------------------------------------------------------------------------

// Record framing on disk (little-endian):
//   u32 crc32(payload) | u32 len(payload) | payload
// payload:
//   u64 commitTS | u32 nOps | nOps * op
// op:
//   u8 kind(0=set,1=del) | u32 keyLen | key | (set only) u32 valLen | val
const (
	opSet byte = 0
	opDel byte = 1
)

var crcTable = crc32.MakeTable(crc32.Castagnoli)

type committedTxn struct {
	ts     uint64
	writes map[string]writeOp
}

func encodeRecord(ts uint64, writes map[string]writeOp) []byte {
	var p []byte
	var u64 [8]byte
	var u32 [4]byte
	binary.LittleEndian.PutUint64(u64[:], ts)
	p = append(p, u64[:]...)
	binary.LittleEndian.PutUint32(u32[:], uint32(len(writes)))
	p = append(p, u32[:]...)
	for k, w := range writes {
		if w.deleted {
			p = append(p, opDel)
		} else {
			p = append(p, opSet)
		}
		binary.LittleEndian.PutUint32(u32[:], uint32(len(k)))
		p = append(p, u32[:]...)
		p = append(p, k...)
		if !w.deleted {
			binary.LittleEndian.PutUint32(u32[:], uint32(len(w.val)))
			p = append(p, u32[:]...)
			p = append(p, w.val...)
		}
	}
	out := make([]byte, 8+len(p))
	binary.LittleEndian.PutUint32(out[0:4], crc32.Checksum(p, crcTable))
	binary.LittleEndian.PutUint32(out[4:8], uint32(len(p)))
	copy(out[8:], p)
	return out
}

// recover replays the WAL, returning committed txns in order plus the max ts.
// A truncated/corrupt tail (torn write) is detected via crc/length and dropped.
func recoverWAL(path string) ([]committedTxn, uint64, error) {
	f, err := os.Open(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, 0, nil
		}
		return nil, 0, err
	}
	defer f.Close()

	r := bufio.NewReaderSize(f, 1<<20)
	var txns []committedTxn
	var maxTS uint64
	var hdr [8]byte

	for {
		if _, err := io.ReadFull(r, hdr[:]); err != nil {
			break // EOF or torn header -> stop
		}
		crc := binary.LittleEndian.Uint32(hdr[0:4])
		plen := binary.LittleEndian.Uint32(hdr[4:8])
		if plen == 0 || plen > (1<<30) {
			break
		}
		p := make([]byte, plen)
		if _, err := io.ReadFull(r, p); err != nil {
			break // torn payload -> stop
		}
		if crc32.Checksum(p, crcTable) != crc {
			break // corrupt -> stop (discard tail)
		}
		ct, ok := decodePayload(p)
		if !ok {
			break
		}
		if ct.ts > maxTS {
			maxTS = ct.ts
		}
		txns = append(txns, ct)
	}
	return txns, maxTS, nil
}

func decodePayload(p []byte) (committedTxn, bool) {
	if len(p) < 12 {
		return committedTxn{}, false
	}
	off := 0
	ts := binary.LittleEndian.Uint64(p[off:])
	off += 8
	n := binary.LittleEndian.Uint32(p[off:])
	off += 4
	writes := make(map[string]writeOp, n)
	for i := uint32(0); i < n; i++ {
		if off+1 > len(p) {
			return committedTxn{}, false
		}
		kind := p[off]
		off++
		if off+4 > len(p) {
			return committedTxn{}, false
		}
		klen := int(binary.LittleEndian.Uint32(p[off:]))
		off += 4
		if off+klen > len(p) {
			return committedTxn{}, false
		}
		key := string(p[off : off+klen])
		off += klen
		if kind == opDel {
			writes[key] = writeOp{deleted: true}
			continue
		}
		if off+4 > len(p) {
			return committedTxn{}, false
		}
		vlen := int(binary.LittleEndian.Uint32(p[off:]))
		off += 4
		if off+vlen > len(p) {
			return committedTxn{}, false
		}
		writes[key] = writeOp{val: string(p[off : off+vlen])}
		off += vlen
	}
	return committedTxn{ts: ts, writes: writes}, true
}

// ---------------------------------------------------------------------------
// Server with group-commit pipeline
// ---------------------------------------------------------------------------

type commitReq struct {
	t      *txn
	result int // 0=ok, 1=conflict (filled by committer)
	done   chan struct{}
}

const (
	resOK = iota
	resConflict
)

type server struct {
	st  *store
	wal *os.File
	bw  *bufio.Writer

	commitCh chan *commitReq
	nextTxID uint64
	idMu     sync.Mutex
}

func newServer(st *store, wal *os.File) *server {
	return &server{
		st:       st,
		wal:      wal,
		bw:       bufio.NewWriterSize(wal, 1<<20),
		commitCh: make(chan *commitReq, 1024),
	}
}

func (s *server) allocTxID() uint64 {
	s.idMu.Lock()
	s.nextTxID++
	id := s.nextTxID
	s.idMu.Unlock()
	return id
}

// committer is the single goroutine that validates conflicts, assigns commit
// timestamps, appends to the WAL and performs one fsync per drained batch.
func (s *server) committer() {
	const maxBatch = 512
	batch := make([]*commitReq, 0, maxBatch)
	for first := range s.commitCh {
		batch = append(batch[:0], first)
	drain:
		for len(batch) < maxBatch {
			select {
			case r := <-s.commitCh:
				batch = append(batch, r)
			default:
				break drain
			}
		}

		wrote := false
		s.st.mu.Lock()
		for _, r := range batch {
			t := r.t
			// Write-write conflict: any committed version of a written key
			// newer than our snapshot means someone else committed first.
			conflict := false
			for k := range t.writes {
				if head := s.st.data[k]; head != nil && head.ts > t.snapshot {
					conflict = true
					break
				}
			}
			if conflict {
				r.result = resConflict
				s.st.endSnapshotLocked(t.snapshot)
				continue
			}
			// Assign commit timestamp and apply.
			s.st.commitTS++
			ts := s.st.commitTS
			rec := encodeRecord(ts, t.writes)
			s.bw.Write(rec)
			wrote = true
			horizon := s.st.gcHorizonLocked()
			for k, w := range t.writes {
				nv := &version{ts: ts, val: w.val, deleted: w.deleted, prev: s.st.data[k]}
				s.st.data[k] = nv
				pruneChainLocked(nv, horizon)
			}
			r.result = resOK
			s.st.endSnapshotLocked(t.snapshot)
		}
		s.st.mu.Unlock()

		if wrote {
			s.bw.Flush()
			// One fsync(2) per drained batch (group commit). We use the raw
			// fsync syscall rather than os.File.Sync (which is F_FULLFSYNC on
			// darwin) — fsync flushes to the OS/device and survives process
			// kill and OS crash, which is what the durability contract needs.
			syscall.Fsync(int(s.wal.Fd()))
		}
		for _, r := range batch {
			close(r.done)
		}
	}
}

// gcLoop periodically sweeps cold keys so memory stays bounded even when a
// key stops being written (per-write pruning already handles hot keys).
func (s *server) gcLoop() {
	t := time.NewTicker(500 * time.Millisecond)
	defer t.Stop()
	for range t.C {
		s.st.mu.Lock()
		horizon := s.st.gcHorizonLocked()
		for k, head := range s.st.data {
			pruneChainLocked(head, horizon)
			// Drop a key entirely once its surviving version is a tombstone
			// that every live snapshot already observes.
			if head.deleted && head.ts <= horizon {
				delete(s.st.data, k)
			}
		}
		s.st.mu.Unlock()
	}
}

// ---------------------------------------------------------------------------
// Connection handling
// ---------------------------------------------------------------------------

func (s *server) handleConn(conn net.Conn) {
	defer conn.Close()
	r := bufio.NewReader(conn)
	w := bufio.NewWriter(conn)
	var active *txn

	reply := func(msg string) bool {
		if _, err := w.WriteString(msg); err != nil {
			return false
		}
		return w.Flush() == nil
	}

	defer func() {
		if active != nil {
			s.st.endSnapshot(active.snapshot)
		}
	}()

	for {
		line, err := r.ReadString('\n')
		if err != nil {
			return
		}
		// strip trailing \r\n / \n
		for len(line) > 0 && (line[len(line)-1] == '\n' || line[len(line)-1] == '\r') {
			line = line[:len(line)-1]
		}
		if line == "" {
			continue
		}
		cmd, rest := splitFirst(line)

		switch cmd {
		case "BEGIN":
			if active != nil {
				if !reply("ERR txn-active\n") {
					return
				}
				continue
			}
			snap := s.st.beginSnapshot()
			active = &txn{id: s.allocTxID(), snapshot: snap, writes: make(map[string]writeOp)}
			if !reply("OK " + strconv.FormatUint(active.id, 10) + "\n") {
				return
			}

		case "SET":
			if active == nil {
				if !reply("ERR no-txn\n") {
					return
				}
				continue
			}
			k, v := splitFirst(rest)
			if k == "" {
				if !reply("ERR bad-args\n") {
					return
				}
				continue
			}
			active.writes[k] = writeOp{val: v}
			if !reply("OK\n") {
				return
			}

		case "DEL":
			if active == nil {
				if !reply("ERR no-txn\n") {
					return
				}
				continue
			}
			k, _ := splitFirst(rest)
			if k == "" {
				if !reply("ERR bad-args\n") {
					return
				}
				continue
			}
			active.writes[k] = writeOp{deleted: true}
			if !reply("OK\n") {
				return
			}

		case "GET":
			if active == nil {
				if !reply("ERR no-txn\n") {
					return
				}
				continue
			}
			k, _ := splitFirst(rest)
			if k == "" {
				if !reply("ERR bad-args\n") {
					return
				}
				continue
			}
			if w0, ok := active.writes[k]; ok {
				if w0.deleted {
					if !reply("NIL\n") {
						return
					}
				} else if !reply("VALUE " + w0.val + "\n") {
					return
				}
				continue
			}
			if val, ok := s.st.readVisible(k, active.snapshot); ok {
				if !reply("VALUE " + val + "\n") {
					return
				}
			} else if !reply("NIL\n") {
				return
			}

		case "COMMIT":
			if active == nil {
				if !reply("ERR no-txn\n") {
					return
				}
				continue
			}
			if len(active.writes) == 0 {
				// Read-only txn: nothing to persist, just release snapshot.
				s.st.endSnapshot(active.snapshot)
				active = nil
				if !reply("OK\n") {
					return
				}
				continue
			}
			req := &commitReq{t: active, done: make(chan struct{})}
			s.commitCh <- req
			<-req.done
			active = nil
			if req.result == resOK {
				if !reply("OK\n") {
					return
				}
			} else if !reply("CONFLICT\n") {
				return
			}

		case "ABORT":
			if active == nil {
				if !reply("ERR no-txn\n") {
					return
				}
				continue
			}
			s.st.endSnapshot(active.snapshot)
			active = nil
			if !reply("OK\n") {
				return
			}

		case "QUIT":
			return

		default:
			if !reply("ERR unknown-cmd\n") {
				return
			}
		}
	}
}

// splitFirst splits s into the first space-delimited token and the remainder.
func splitFirst(s string) (string, string) {
	for i := 0; i < len(s); i++ {
		if s[i] == ' ' {
			// skip a single space; value itself contains no spaces per spec
			return s[:i], s[i+1:]
		}
	}
	return s, ""
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "usage: run <port> <wal_path>")
		os.Exit(2)
	}
	port := os.Args[1]
	walPath := os.Args[2]

	st := newStore()

	// Recover committed state from the WAL before accepting connections.
	recs, maxTS, err := recoverWAL(walPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "recover error:", err)
		os.Exit(1)
	}
	for _, ct := range recs {
		for k, w := range ct.writes {
			st.data[k] = &version{ts: ct.ts, val: w.val, deleted: w.deleted, prev: st.data[k]}
		}
	}
	st.commitTS = maxTS
	// Collapse replayed history to a single live version per key (no readers yet).
	for k, head := range st.data {
		head.prev = nil
		if head.deleted {
			delete(st.data, k)
		}
	}

	wal, err := os.OpenFile(walPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		fmt.Fprintln(os.Stderr, "open wal error:", err)
		os.Exit(1)
	}

	srv := newServer(st, wal)
	go srv.committer()
	go srv.gcLoop()

	ln, err := net.Listen("tcp", "127.0.0.1:"+port)
	if err != nil {
		fmt.Fprintln(os.Stderr, "listen error:", err)
		os.Exit(1)
	}

	fmt.Fprintln(os.Stderr, "READY")

	for {
		conn, err := ln.Accept()
		if err != nil {
			continue
		}
		if tc, ok := conn.(*net.TCPConn); ok {
			tc.SetNoDelay(true)
		}
		go srv.handleConn(conn)
	}
}
