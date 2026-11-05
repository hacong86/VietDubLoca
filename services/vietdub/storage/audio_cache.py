"""Cache audio atomic + LRU/TTL + lease (docs/09 §Chính sách cache; FR-035, FR-037, NFR-11).

Tệp: ``<root>/<k[:2]>/<k>.pcm`` = PCM s16le mono 48 kHz thô. Ghi ``.tmp`` → fsync → os.replace.
Metadata ở bảng ``audio_assets`` (content DB). Private mode: RAM bounded, không ghi đĩa.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from ..hashing import sha256_hex
from .db import Database, new_id, now_iso

DEFAULT_LIMIT = 2 * 1024 ** 3
DEFAULT_TTL_DAYS = 14
MAX_FILE = 64 * 1024 ** 2
MIN_FREE_DISK = 1024 ** 3
TMP_ORPHAN_S = 3600


@dataclass
class AudioEntry:
    cache_key: str
    pcm: bytes
    sample_rate: int
    duration_ms: int


class AudioCache:
    def __init__(self, root: Path, db: Database, *, limit_bytes: int = DEFAULT_LIMIT,
                 ttl_days: int = DEFAULT_TTL_DAYS, ram_limit_bytes: int = 256 * 1024 ** 2) -> None:
        self.root = root
        self.db = db
        self.limit = limit_bytes
        self.ttl_s = ttl_days * 86400
        self._leases: dict[str, int] = {}
        self._pending_delete: set[str] = set()
        self._ram: "OrderedDict[str, AudioEntry]" = OrderedDict()
        self._ram_bytes = 0
        self._ram_limit = ram_limit_bytes
        self._lock = threading.RLock()
        self.disk_full = False
        root.mkdir(parents=True, exist_ok=True)

    # ---- đường dẫn an toàn ----
    def _rel(self, key: str) -> str:
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("bad cache key")
        return f"{key[:2]}/{key}.pcm"

    def _abs(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("path escapes cache root")
        return p

    # ---- RAM (private mode + đệm nóng) ----
    def _ram_put(self, e: AudioEntry) -> None:
        with self._lock:
            old = self._ram.pop(e.cache_key, None)
            if old:
                self._ram_bytes -= len(old.pcm)
            self._ram[e.cache_key] = e
            self._ram_bytes += len(e.pcm)
            while self._ram_bytes > self._ram_limit and self._ram:
                _, ev = self._ram.popitem(last=False)
                self._ram_bytes -= len(ev.pcm)

    def clear_ram(self) -> None:
        with self._lock:
            self._ram.clear()
            self._ram_bytes = 0

    # ---- API ----
    def get(self, key: str) -> AudioEntry | None:
        with self._lock:
            e = self._ram.get(key)
            if e:
                self._ram.move_to_end(key)
                return e
        if self.db.private:
            return None
        row = self.db.content.execute("SELECT * FROM audio_assets WHERE cache_key=? AND status='READY'", (key,)).fetchone()
        if not row:
            return None
        p = self._abs(row["relative_path"])
        self.acquire(key)
        try:
            data = p.read_bytes()
        except OSError:
            return None
        finally:
            self.release(key)
        if sha256_hex(data) != row["sha256"]:
            return None
        with self.db.tx(self.db.content) as c:
            c.execute("UPDATE audio_assets SET last_access_at=? WHERE cache_key=?", (now_iso(), key))
        e = AudioEntry(key, data, row["sample_rate"], row["duration_ms"])
        self._ram_put(e)
        return e

    def put(self, key: str, pcm: bytes, *, sample_rate: int, translation_id: str | None, voice_fingerprint: str,
            sdk_version: str) -> AudioEntry:
        if not pcm or len(pcm) % 2:
            raise ValueError("invalid pcm")
        duration_ms = round(len(pcm) / 2 / sample_rate * 1000)
        e = AudioEntry(key, pcm, sample_rate, duration_ms)
        self._ram_put(e)
        if self.db.private or translation_id is None or len(pcm) > MAX_FILE:
            return e
        if shutil.disk_usage(self.root).free < MIN_FREE_DISK:
            self.disk_full = True
            return e
        self.disk_full = False
        rel = self._rel(key)
        dst = self._abs(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(f".{os.getpid()}.{int(time.time()*1000)}.tmp")
        with open(tmp, "wb") as f:
            f.write(pcm)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dst)
        with self.db.tx(self.db.content) as c:
            c.execute("INSERT INTO audio_assets(audio_id,cache_key,translation_id,voice_fingerprint,sdk_version,codec,"
                      "sample_rate,channels,duration_ms,size_bytes,sha256,relative_path,status,last_access_at,created_at) "
                      "VALUES(?,?,?,?,?,'pcm_s16le',?,1,?,?,?,?,'READY',?,?) ON CONFLICT(cache_key) DO UPDATE SET "
                      "last_access_at=excluded.last_access_at, status='READY'",
                      (new_id(), key, translation_id, voice_fingerprint, sdk_version, sample_rate, max(1, duration_ms),
                       len(pcm), sha256_hex(pcm), rel, now_iso(), now_iso()))
        return e

    # ---- lease: không xóa file đang mở ----
    def acquire(self, key: str) -> None:
        with self._lock:
            self._leases[key] = self._leases.get(key, 0) + 1

    def release(self, key: str) -> None:
        with self._lock:
            n = self._leases.get(key, 0) - 1
            if n <= 0:
                self._leases.pop(key, None)
                if key in self._pending_delete:
                    self._pending_delete.discard(key)
                    self._delete_file(key)
            else:
                self._leases[key] = n

    def _delete_file(self, key: str) -> None:
        try:
            self._abs(self._rel(key)).unlink(missing_ok=True)
        except OSError:
            self._pending_delete.add(key)

    def delete_keys(self, keys: list[str]) -> None:
        with self._lock:
            for k in keys:
                self._ram.pop(k, None)
                if self._leases.get(k):
                    self._pending_delete.add(k)
                else:
                    self._delete_file(k)

    def delete_relpaths(self, rels: list[str]) -> None:
        self.delete_keys([Path(r).stem for r in rels])

    def usage_bytes(self) -> int:
        row = self.db.content.execute("SELECT COALESCE(SUM(size_bytes),0) FROM audio_assets").fetchone()
        return int(row[0])

    def enforce(self) -> dict[str, int]:
        """TTL + LRU tới giới hạn; dọn .tmp mồ côi. Trả thống kê."""
        removed_ttl = removed_lru = removed_tmp = 0
        if not self.db.private:
            cutoff = time.time() - self.ttl_s
            rows = self.db.content.execute("SELECT cache_key,last_access_at,size_bytes FROM audio_assets "
                                           "ORDER BY last_access_at ASC").fetchall()
            total = sum(r["size_bytes"] for r in rows)
            drop: list[str] = []
            for r in rows:
                ts = _parse_iso(r["last_access_at"])
                if ts < cutoff:
                    drop.append(r["cache_key"]); total -= r["size_bytes"]; removed_ttl += 1
                elif total > self.limit:
                    drop.append(r["cache_key"]); total -= r["size_bytes"]; removed_lru += 1
            if drop:
                with self.db.tx(self.db.content) as c:
                    c.executemany("DELETE FROM audio_assets WHERE cache_key=?", [(k,) for k in drop])
                self.delete_keys(drop)
        now = time.time()
        for tmp in self.root.glob("*/*.tmp"):
            try:
                if now - tmp.stat().st_mtime > TMP_ORPHAN_S:
                    tmp.unlink()
                    removed_tmp += 1
            except OSError:
                pass
        return {"ttl": removed_ttl, "lru": removed_lru, "tmp": removed_tmp}

    def clear_all(self) -> None:
        with self._lock:
            keys = [r[0] for r in self.db.content.execute("SELECT cache_key FROM audio_assets").fetchall()]
            with self.db.tx(self.db.content) as c:
                c.execute("DELETE FROM audio_assets")
            self.delete_keys(keys)
            self.clear_ram()


def _parse_iso(s: str) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return 0.0
