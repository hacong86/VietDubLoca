"""NFR-11, FR-002, FR-035, FR-037, SYS-18: migration/backup, cache atomic+LRU+TTL+lease, model checksum/.part/path."""
import asyncio
import hashlib
import json
import sqlite3

import httpx
import pytest

from vietdub.audio_frame import float_to_s16le, pack_frame, unpack_frame
from vietdub.broker.state import InvalidTransition, S, StateMachine
from vietdub.contracts import load_example, schema_errors
from vietdub.errors import AppError
from vietdub.models.manager import ModelManager, git_blob_sha1, host_allowed
from vietdub.paths import AppPaths
from vietdub.storage.audio_cache import AudioCache
from vietdub.storage.db import LATEST, SCHEMA_V1, Database, user_version


def test_contract_examples_valid_and_negative():
    for name, ex in [("audio_chunk", "audio-chunk-header.json"), ("caption_batch", "caption-batch.json"),
                     ("error", "error.json"), ("event", "event.json"), ("playback_clock", "playback-clock.json"),
                     ("translation_output", "translation-output.json")]:
        assert schema_errors(name, load_example(ex)) == [], name
    bad = load_example("caption-batch.json")
    bad["cues"][0]["extra"] = 1
    assert schema_errors("caption_batch", bad)
    bad2 = load_example("playback-clock.json")
    bad2["media_ms"] = -1
    assert schema_errors("playback_clock", bad2)
    bad3 = load_example("event.json")
    bad3["event"] = "shell.exec"
    assert schema_errors("event", bad3)


def test_audio_frame_roundtrip_and_rejects():
    import numpy as np
    pcm = float_to_s16le(np.sin(np.linspace(0, 100, 4800)).astype("float32"))
    h = load_example("audio-chunk-header.json")
    f = pack_frame(h, pcm)
    h2, p2 = unpack_frame(f)
    assert h2 == h and p2 == pcm
    with pytest.raises(ValueError):
        pack_frame({**h, "sample_count": 10}, pcm)
    with pytest.raises(ValueError):
        pack_frame({**h, "sample_rate": 16000}, pcm)
    with pytest.raises(ValueError):
        unpack_frame(b"\x00\x00\x00\x05{}")
    with pytest.raises(ValueError):
        float_to_s16le(np.array([np.nan], dtype="float32"))


def test_state_machine_guards():
    sm = StateMachine(S.IDLE)
    sm.to(S.DISCOVERING)
    sm.to(S.BUFFERING)
    sm.to(S.PLAYING)
    with pytest.raises(InvalidTransition):
        sm.to(S.IDLE)
    sm.to(S.STOPPED)
    with pytest.raises(InvalidTransition):
        sm.to(S.PLAYING)


def test_migration_from_v1_with_backup(tmp_path):
    db_file = tmp_path / "db" / "v.sqlite3"
    db_file.parent.mkdir()
    con = sqlite3.connect(db_file)
    con.executescript(SCHEMA_V1)
    con.execute("INSERT INTO settings VALUES('k','1','t')")
    con.commit()
    con.close()
    db = Database(db_file, tmp_path / "backups")
    assert user_version(db.config) == LATEST
    assert db.get_setting("k") == 1
    assert list((tmp_path / "backups").glob("*.sqlite3"))
    db.close()


def test_newer_db_refused(tmp_path):
    f = tmp_path / "x.sqlite3"
    con = sqlite3.connect(f)
    con.execute("PRAGMA user_version = 99")
    con.close()
    with pytest.raises(RuntimeError):
        Database(f, tmp_path)


def test_fk_and_check_constraints(tmp_path):
    db = Database(tmp_path / "d.sqlite3", tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        with db.tx(db.content) as c:
            c.execute("INSERT INTO cues VALUES('c','nosrc',0,1,'x',1)")
    db.close()


def _mk_translation(db):
    db.upsert_video("vid12345678", None, False)
    db.upsert_source(source_id="s", video_id="vid12345678", revision=1, language="en", kind="manual", coverage="full",
                     content_hash="h", available_until_ms=1)
    db.put_segment({"segment_id": "u1", "source_id": "s", "revision": 1, "source_hash": "h", "source_text": "x",
                    "start_ms": 0, "end_ms": 1, "cue_map_json": "[]", "boundary_reason": "end", "speaker": None})
    return db.put_translation({"segment_id": "u1", "revision": 1, "cache_key": "k" * 64, "model_fingerprint": "m",
                               "prompt_version": "p", "glossary_version": 1, "context_hash": "c", "target_display": "d",
                               "target_spoken": "d", "flags": [], "status": "READY"})


def test_audio_cache_atomic_lru_ttl_lease(tmp_path):
    db = Database(tmp_path / "d.sqlite3", tmp_path)
    tid = _mk_translation(db)
    cache = AudioCache(tmp_path / "audio", db, limit_bytes=3000)
    keys = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(3)]
    for k in keys:
        cache.put(k, b"\x01\x00" * 1000, sample_rate=48000, translation_id=tid, voice_fingerprint="v", sdk_version="s")
    assert not list((tmp_path / "audio").rglob("*.tmp"))
    cache.clear_ram()
    assert cache.get(keys[0]).pcm == b"\x01\x00" * 1000
    # hỏng nội dung → không trả dữ liệu sai
    p = next((tmp_path / "audio").rglob(keys[1] + ".pcm"))
    p.write_bytes(b"\x00\x00" * 1000)
    cache.clear_ram()
    assert cache.get(keys[1]) is None
    cache.acquire(keys[2])
    stats = cache.enforce()
    assert stats["lru"] >= 1
    cache.release(keys[2])
    with pytest.raises(ValueError):
        cache._rel("../../etc/passwd")
    db.close()


def test_private_mode_cache_ram_only(tmp_path):
    db = Database(tmp_path / "d.sqlite3", tmp_path, private=True)
    cache = AudioCache(tmp_path / "audio", db)
    k = "a" * 64
    cache.put(k, b"\x01\x00" * 100, sample_rate=48000, translation_id="t", voice_fingerprint="v", sdk_version="s")
    assert cache.get(k) is not None
    assert not list((tmp_path / "audio").rglob("*"))
    db.close()


def test_host_allowlist():
    assert host_allowed("huggingface.co") and host_allowed("us.aws.cdn.hf.co") and host_allowed("cas-bridge.xethub.hf.co")
    assert not host_allowed("evil.co") and not host_allowed("huggingface.co.evil.com") and not host_allowed("xhf.co")


def _manager(tmp_path, handler):
    mm = ModelManager(AppPaths(tmp_path).ensure(), transport=httpx.MockTransport(handler))
    content = b"GGUF" + b"x" * 1000
    mm.catalog = {"t": {"id": "t", "kind": "translation", "repo": "o/r", "revision": "r1", "size_bytes": len(content),
                        "files": [{"path": "m.gguf", "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
                                   "git_sha1": None}]}}
    return mm, content


def test_download_consent_resume_and_checksum(tmp_path):
    served = {"ranges": []}

    def good(req):
        rng = req.headers.get("range")
        served["ranges"].append(rng)
        start = int(rng.split("=")[1].split("-")[0]) if rng else 0
        return httpx.Response(206 if rng else 200, content=content[start:])

    mm, content = _manager(tmp_path, good)
    with pytest.raises(AppError):
        mm.start_download("t", consent=False, accepted_size_bytes=len(content))
    part = mm.translation_file("t").with_name("m.gguf.part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(content[:300])                         # .part tải dở

    async def go():
        j = mm.start_download("t", consent=True, accepted_size_bytes=len(content))
        await j.task
        return j
    j = asyncio.run(go())
    assert j.state == "done" and served["ranges"][0] == "bytes=300-"
    assert mm.translation_file("t").read_bytes() == content and not part.exists()


def test_download_checksum_mismatch_blocked(tmp_path):
    def evil(req):
        return httpx.Response(200, content=b"GGUF" + b"y" * 1000)
    mm, content = _manager(tmp_path, evil)

    async def go():
        j = mm.start_download("t", consent=True, accepted_size_bytes=len(content))
        await j.task
        return j
    j = asyncio.run(go())
    assert j.state == "failed" and j.error == "MODEL_CHECKSUM_MISMATCH"
    assert not mm.translation_file("t").exists()
    assert mm.status("t")["state"] != "verified"


def test_redirect_to_foreign_host_blocked(tmp_path):
    def redir(req):
        return httpx.Response(302, headers={"location": "https://evil.example/x"})
    mm, content = _manager(tmp_path, redir)

    async def go():
        j = mm.start_download("t", consent=True, accepted_size_bytes=len(content))
        await j.task
        return j
    assert asyncio.run(go()).error == "CONNECT_FAILED"


def test_catalog_path_traversal_rejected(tmp_path):
    mm, _ = _manager(tmp_path, lambda r: httpx.Response(404))
    with pytest.raises(ValueError):
        mm.file_path(mm.catalog["t"], "../../evil.dll")


def test_git_blob_sha1(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"hello\n")
    assert git_blob_sha1(p) == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_real_catalog_pinned():
    cat = json.loads(open("config/model-catalog.json", encoding="utf-8").read())
    for m in cat["models"]:
        assert len(m["revision"]) == 40
        for f in m["files"]:
            assert (f["sha256"] and len(f["sha256"]) == 64) or (f["git_sha1"] and len(f["git_sha1"]) == 40)
        assert not any("mmproj" in f["path"] for f in m["files"])
