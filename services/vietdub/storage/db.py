"""SQLite (docs/09): WAL, foreign_keys, migration đơn điệu có backup, private mode dùng DB bộ nhớ.

Hai kết nối:
- ``config``: luôn trên đĩa — settings, glossary, model artifacts.
- ``content``: video/cue/segment/translation/audio/override — trên đĩa, hoặc ``:memory:`` khi private mode.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ..paths import REPO_ROOT

SCHEMA_V1 = (REPO_ROOT / "data" / "schema.sql").read_text(encoding="utf-8")

MIGRATIONS: list[tuple[int, str]] = [
    (1, SCHEMA_V1),
    (2, """
ALTER TABLE glossary_entries ADD COLUMN whole_phrase INTEGER NOT NULL DEFAULT 1 CHECK(whole_phrase IN (0,1));
ALTER TABLE segments ADD COLUMN speaker TEXT;
ALTER TABLE translations ADD COLUMN source_revision INTEGER NOT NULL DEFAULT 1;
CREATE TABLE IF NOT EXISTS segment_state (
 segment_id TEXT PRIMARY KEY REFERENCES segments(segment_id) ON DELETE CASCADE,
 current_translation_id TEXT, current_override_id TEXT, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_videos_opened ON videos(last_opened_at);
PRAGMA user_version = 2;
"""),
]
LATEST = MIGRATIONS[-1][0]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id() -> str:
    return uuid.uuid4().hex


def _connect(target: str) -> sqlite3.Connection:
    con = sqlite3.connect(target, isolation_level=None, check_same_thread=False, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    if target != ":memory:":
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")
    return con


def user_version(con: sqlite3.Connection) -> int:
    return int(con.execute("PRAGMA user_version").fetchone()[0])


def migrate(con: sqlite3.Connection, db_path: Path | None, backup_dir: Path | None) -> list[int]:
    applied = []
    cur = user_version(con)
    if cur > LATEST:
        raise RuntimeError(f"DB version {cur} mới hơn ứng dụng ({LATEST}); không mở bằng bản cũ")
    if cur and cur < LATEST and db_path and backup_dir and db_path.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        dst = backup_dir / f"vietdub-v{cur}-{int(time.time())}.sqlite3"
        bcon = sqlite3.connect(dst)
        con.backup(bcon)
        bcon.close()
    for ver, sql in MIGRATIONS:
        if ver <= cur:
            continue
        body = sql.replace("PRAGMA journal_mode = WAL;", "")
        if ver == 1:
            con.executescript(body)          # schema.sql tự BEGIN/COMMIT
        else:
            con.executescript("BEGIN;\n" + body + "\nCOMMIT;")
        applied.append(ver)
    return applied


class Database:
    def __init__(self, db_file: Path | None, backup_dir: Path | None = None, *, private: bool = False) -> None:
        self._lock = threading.RLock()
        self.db_file = db_file
        target = str(db_file) if db_file else ":memory:"
        if db_file:
            db_file.parent.mkdir(parents=True, exist_ok=True)
        self.config = _connect(target)
        migrate(self.config, db_file, backup_dir)
        self.private = private
        if private or not db_file:
            self.content = _connect(":memory:")
            migrate(self.content, None, None)
        else:
            self.content = self.config

    def close(self) -> None:
        with self._lock:
            if self.content is not self.config:
                self.content.close()
            self.config.close()

    @contextmanager
    def tx(self, con: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
        with self._lock:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise

    def set_private(self, private: bool) -> None:
        with self._lock:
            if private == self.private:
                return
            if private:
                self.content = _connect(":memory:")
                migrate(self.content, None, None)
            else:
                if self.content is not self.config:
                    self.content.close()
                self.content = self.config
            self.private = private

    # ---------- settings (config) ----------
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.config.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put_setting(self, key: str, value: Any) -> None:
        with self.tx(self.config) as c:
            c.execute("INSERT INTO settings(key,value_json,updated_at) VALUES(?,?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                      (key, json.dumps(value, ensure_ascii=False), now_iso()))

    def delete_setting(self, key: str) -> None:
        with self.tx(self.config) as c:
            c.execute("DELETE FROM settings WHERE key=?", (key,))

    # ---------- glossary (config) ----------
    def load_glossary(self) -> dict[str, Any]:
        rows = self.config.execute("SELECT * FROM glossary_entries ORDER BY domain, source_term").fetchall()
        version = int(self.get_setting("glossary_version", 1))
        entries = [{"entry_id": r["entry_id"], "source": r["source_term"], "domain": r["domain"], "policy": r["mode"],
                    "case_sensitive": bool(r["case_sensitive"]), "whole_phrase": bool(r["whole_phrase"]),
                    "target_display": r["target_term"] or None, "target_spoken": r["pronunciation"],
                    "enabled": bool(r["enabled"])} for r in rows]
        return {"version": version, "entries": entries}

    def replace_glossary(self, entries: list[dict[str, Any]], expected_version: int | None) -> int:
        with self.tx(self.config) as c:
            row = c.execute("SELECT value_json FROM settings WHERE key='glossary_version'").fetchone()
            cur = int(json.loads(row[0])) if row else 1
            if expected_version is not None and expected_version != cur:
                raise ValueError("REVISION_CONFLICT")
            new = cur + 1
            c.execute("DELETE FROM glossary_entries")
            for e in entries:
                c.execute("INSERT INTO glossary_entries(entry_id,version,domain,source_term,target_term,mode,"
                          "case_sensitive,pronunciation,enabled,whole_phrase) VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (e.get("entry_id") or new_id(), new, e["domain"], e["source"],
                           e.get("target_display") or e["source"], e["policy"], int(e["case_sensitive"]),
                           e.get("target_spoken"), int(e.get("enabled", True)), int(e.get("whole_phrase", True))))
            c.execute("INSERT INTO settings(key,value_json,updated_at) VALUES('glossary_version',?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                      (json.dumps(new), now_iso()))
        return new

    # ---------- model artifacts (config) ----------
    def upsert_artifact(self, a: dict[str, Any]) -> None:
        with self.tx(self.config) as c:
            c.execute("INSERT INTO model_artifacts(artifact_id,source_repo,revision,filename,sha256,size_bytes,local_path,verified) "
                      "VALUES(:artifact_id,:source_repo,:revision,:filename,:sha256,:size_bytes,:local_path,:verified) "
                      "ON CONFLICT(artifact_id) DO UPDATE SET source_repo=excluded.source_repo, revision=excluded.revision, "
                      "filename=excluded.filename, sha256=excluded.sha256, size_bytes=excluded.size_bytes, "
                      "local_path=excluded.local_path, verified=excluded.verified", a)

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        r = self.config.execute("SELECT * FROM model_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        return dict(r) if r else None

    def delete_artifact(self, artifact_id: str) -> None:
        with self.tx(self.config) as c:
            c.execute("DELETE FROM model_artifacts WHERE artifact_id=?", (artifact_id,))

    # ---------- content ----------
    def upsert_video(self, video_id: str, title: str | None, history_opt_in: bool) -> None:
        with self.tx(self.content) as c:
            c.execute("INSERT INTO videos(video_id,provider,title,history_opt_in,created_at,last_opened_at) "
                      "VALUES(?, 'youtube', ?, ?, ?, ?) ON CONFLICT(video_id) DO UPDATE SET "
                      "title=COALESCE(excluded.title, videos.title), history_opt_in=MAX(videos.history_opt_in, excluded.history_opt_in), "
                      "last_opened_at=excluded.last_opened_at",
                      (video_id, title if history_opt_in else None, int(history_opt_in), now_iso(), now_iso()))

    def upsert_source(self, *, source_id: str, video_id: str, revision: int, language: str, kind: str, coverage: str,
                      content_hash: str, available_until_ms: int, offset_ms: int = 0) -> None:
        with self.tx(self.content) as c:
            c.execute("INSERT INTO source_tracks(source_id,video_id,revision,language,kind,coverage,content_hash,"
                      "available_until_ms,offset_ms) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET "
                      "revision=excluded.revision, coverage=excluded.coverage, content_hash=excluded.content_hash, "
                      "available_until_ms=excluded.available_until_ms, offset_ms=excluded.offset_ms",
                      (source_id, video_id, revision, language, kind, coverage, content_hash, available_until_ms, offset_ms))

    def put_cues(self, source_id: str, cues: list[dict[str, Any]]) -> None:
        with self.tx(self.content) as c:
            c.executemany("INSERT INTO cues(cue_id,source_id,start_ms,end_ms,raw_text,committed) VALUES(?,?,?,?,?,?) "
                          "ON CONFLICT(source_id,cue_id) DO UPDATE SET start_ms=excluded.start_ms, end_ms=excluded.end_ms, "
                          "raw_text=excluded.raw_text, committed=excluded.committed",
                          [(q["cue_id"], source_id, q["start_ms"], q["end_ms"], q["text"], int(q.get("committed", True)))
                           for q in cues])

    def put_segment(self, s: dict[str, Any]) -> None:
        with self.tx(self.content) as c:
            c.execute("INSERT INTO segments(segment_id,source_id,revision,source_hash,source_text,start_ms,end_ms,cue_map_json,"
                      "boundary_reason,speaker) VALUES(:segment_id,:source_id,:revision,:source_hash,:source_text,:start_ms,:end_ms,"
                      ":cue_map_json,:boundary_reason,:speaker) ON CONFLICT(segment_id) DO NOTHING", s)

    def get_translation_by_key(self, cache_key: str) -> dict[str, Any] | None:
        r = self.content.execute("SELECT * FROM translations WHERE cache_key=?", (cache_key,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["flags"] = json.loads(d.pop("flags_json"))
        return d

    def put_translation(self, t: dict[str, Any]) -> str:
        tid = t.get("translation_id") or new_id()
        with self.tx(self.content) as c:
            c.execute("INSERT INTO translations(translation_id,segment_id,revision,cache_key,model_fingerprint,prompt_version,"
                      "glossary_version,context_hash,target_display,target_spoken,flags_json,status,created_at,source_revision) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET "
                      "target_display=excluded.target_display, target_spoken=excluded.target_spoken, "
                      "flags_json=excluded.flags_json, status=excluded.status",
                      (tid, t["segment_id"], t["revision"], t["cache_key"], t["model_fingerprint"], t["prompt_version"],
                       t["glossary_version"], t["context_hash"], t["target_display"], t["target_spoken"],
                       json.dumps(t.get("flags", []), ensure_ascii=False), t["status"], now_iso(), t.get("source_revision", 1)))
            row = c.execute("SELECT translation_id FROM translations WHERE cache_key=?", (t["cache_key"],)).fetchone()
        return row[0]

    def put_override(self, segment_id: str, display: str, spoken: str) -> tuple[str, int]:
        with self.tx(self.content) as c:
            row = c.execute("SELECT COALESCE(MAX(revision),0) FROM overrides WHERE segment_id=?", (segment_id,)).fetchone()
            rev = int(row[0]) + 1
            oid = new_id()
            c.execute("INSERT INTO overrides(override_id,segment_id,revision,target_display,target_spoken,created_at) "
                      "VALUES(?,?,?,?,?,?)", (oid, segment_id, rev, display, spoken, now_iso()))
        return oid, rev

    def latest_override(self, segment_id: str) -> dict[str, Any] | None:
        r = self.content.execute("SELECT * FROM overrides WHERE segment_id=? ORDER BY revision DESC LIMIT 1",
                                 (segment_id,)).fetchone()
        return dict(r) if r else None

    def latest_machine_translation(self, segment_id: str) -> dict[str, Any] | None:
        """Bản máy dịch READY mới nhất của câu (dùng khi hoàn tác bản sửa nạp lại từ DB, chưa có cache_key)."""
        r = self.content.execute("SELECT * FROM translations WHERE segment_id=? AND status='READY' "
                                 "ORDER BY created_at DESC LIMIT 1", (segment_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["flags"] = json.loads(d.pop("flags_json"))
        return d

    def override_history(self, segment_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.content.execute(
            "SELECT * FROM overrides WHERE segment_id=? ORDER BY revision", (segment_id,)).fetchall()]

    def delete_override_revision(self, segment_id: str, revision: int) -> None:
        with self.tx(self.content) as c:
            c.execute("DELETE FROM overrides WHERE segment_id=? AND revision=?", (segment_id, revision))

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(r) for r in self.content.execute(
            "SELECT video_id,title,last_opened_at FROM videos WHERE history_opt_in=1 ORDER BY last_opened_at DESC LIMIT ?",
            (limit,)).fetchall()]

    def delete_video(self, video_id: str) -> list[str]:
        """Xóa nội dung một video; trả relative_path audio cần xóa file (xóa file do cache layer)."""
        with self.tx(self.content) as c:
            paths = [r[0] for r in c.execute(
                "SELECT a.relative_path FROM audio_assets a JOIN translations t ON a.translation_id=t.translation_id "
                "JOIN segments s ON t.segment_id=s.segment_id JOIN source_tracks st ON s.source_id=st.source_id "
                "WHERE st.video_id=?", (video_id,)).fetchall()]
            c.execute("DELETE FROM videos WHERE video_id=?", (video_id,))
        return paths

    def delete_all_content(self, keep_overrides: bool) -> list[str]:
        with self.tx(self.content) as c:
            paths = [r[0] for r in c.execute("SELECT relative_path FROM audio_assets").fetchall()]
            c.execute("DELETE FROM audio_assets")
            if not keep_overrides:
                c.execute("DELETE FROM videos")
            else:
                c.execute("DELETE FROM translations")
        return paths

    def checkpoint(self) -> None:
        if self.db_file:
            self.config.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def backup_to(self, dst: Path) -> None:
        self.checkpoint()
        bcon = sqlite3.connect(dst)
        self.config.backup(bcon)
        bcon.close()


def restore_backup(src: Path, db_file: Path) -> None:
    shutil.copy2(src, db_file)
