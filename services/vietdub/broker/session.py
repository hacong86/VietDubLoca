"""Phiên phát + pipeline caption→dịch→VieNeu→audio (docs/03 §3, docs/04 §10, docs/06, docs/12).

Bất biến: mọi audio gửi đi mang (session_id, timeline_epoch, segment_id, revision). Epoch tăng khi seek/đổi nguồn.
Dịch và audio là nội dung (content-addressed) nên không phụ thuộc epoch; chỉ việc GIAO audio gắn epoch.
Ưu tiên: TTS gần playhead > dịch gần playhead > prefetch xa > preview/benchmark (docs/12).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..audio_frame import TTS_RATE, pack_frame, split_pcm
from ..errors import AppError
from ..hashing import content_key, sha256_hex
from ..storage.audio_cache import AudioCache
from ..storage.db import Database
from ..translation.glossary import Glossary
from ..translation.prompt import PROMPT_VERSION
from ..translation.segmenter import TranslationUnit, build_units
from ..translation.service import (ModelFingerprint, UnitRequest, UnitResult, audio_cache_key, plan_batches,
                                   translate_batch)
from ..translation.spoken import to_spoken
from ..translation.text import Cue, assign_turn_speakers, dedupe_rolling, normalize_text, split_turn
from .events import Hub
from .state import S, StateMachine
from .voices import pick_alt_voice

log = logging.getLogger("vietdub.session")

MODES = ("vod_sync", "live_delayed", "study")


class Runtime(Protocol):
    """Bề mặt runtime mà phiên cần (triển khai ở broker/runtime.py; test dùng fake)."""
    def translation_ready(self) -> bool: ...
    def fingerprint(self) -> ModelFingerprint | None: ...
    async def chat(self, payload: dict[str, Any]) -> Any: ...
    def tts_ready(self) -> bool: ...
    async def synth(self, text: str, voice: str) -> tuple[bytes, dict[str, Any]]: ...
    def synth_stream(self, text: str, voice: str) -> Any: ...
    def voice_fingerprint(self, voice: str) -> str: ...
    def tts_versions(self) -> tuple[str, str]: ...
    async def asr_reset(self, session_id: str, epoch: int) -> None: ...
    async def asr_feed(self, header: dict[str, Any], pcm: bytes) -> None: ...
    async def asr_flush(self, epoch: int) -> None: ...
    async def tts_cancel_all(self) -> None: ...
    def on_tts_failure(self, code: str) -> str: ...


@dataclass
class UnitState:
    unit: TranslationUnit
    status: str = "pending"            # pending | translating | ready | blocked
    display: str = ""
    spoken: str = ""
    revision: int = 1
    override: bool = False
    flags: list[str] = field(default_factory=list)
    error: str | None = None
    translation_id: str | None = None
    cache_key: str | None = None
    audio_key: str | None = None
    audio_ms: int | None = None
    tts_status: str = "none"           # none | running | ready | failed
    tts_error: str | None = None
    delivered: tuple[int, int] | None = None   # (epoch, revision)
    from_cache: bool = False
    voice: str | None = None                   # giọng đã dùng cho audio hiện tại

    def public(self) -> dict[str, Any]:
        u = self.unit
        return {"segment_id": u.unit_id, "revision": self.revision, "start_ms": u.start_ms, "end_ms": u.end_ms,
                "source_text": u.source_text, "status": self.status, "target_display": self.display,
                "target_spoken": self.spoken, "override": self.override, "flags": self.flags, "error": self.error,
                "audio": self.tts_status, "audio_ms": self.audio_ms, "final": u.final, "speaker": u.speaker,
                "voice": self.voice}


@dataclass
class Clock:
    media_ms: int = 0
    rate: float = 1.0
    paused: bool = True
    seeking: bool = False
    stalled: bool = False
    ad_state: str = "content"
    visibility: str = "visible"
    received: float = field(default_factory=time.monotonic)

    def now_ms(self) -> int:
        if self.paused or self.seeking or self.stalled or self.ad_state != "content":
            return self.media_ms
        return int(self.media_ms + (time.monotonic() - self.received) * 1000 * self.rate)


@dataclass
class Settings:
    topic: str = "general"
    voice: str = "Minh Quân Pro"
    prefetch_target_ms: int = 30_000
    low_water_ms: int = 8_000
    high_water_ms: int = 45_000
    live_queue_cap_ms: int = 30_000
    history_opt_in: bool = False
    watermark: bool = True
    alternate_speakers: bool = True
    voice_alt: str = ""                  # "" = tự chọn giọng khác giới


class Session:
    def __init__(self, *, video_id: str, tab_id: int, mode: str, runtime: Runtime, db: Database, cache: AudioCache,
                 hub: Hub, settings: Settings, glossary: Glossary, title: str | None = None) -> None:
        if mode not in MODES:
            raise AppError("VALIDATION_FAILED", {"field": "mode"})
        self.session_id = "s_" + uuid.uuid4().hex[:20]
        self.video_id = video_id
        self.tab_id = tab_id
        self.mode = mode
        self.title = title
        self.epoch = 0
        self.sm = StateMachine(S.IDLE)
        self.sm.to(S.DISCOVERING, "session_created")
        self.rt = runtime
        self.db = db
        self.cache = cache
        self.hub = hub
        self.settings = settings
        self.glossary = glossary
        self.clock = Clock()
        self.source: dict[str, Any] | None = None
        self.cues: dict[str, Cue] = {}
        self.units: list[UnitState] = []
        self.by_id: dict[str, UnitState] = {}
        self.wake_tr = asyncio.Event()
        self.wake_tts = asyncio.Event()
        self.tasks: list[asyncio.Task] = []
        self.closed = False
        self.last_error: str | None = None
        self.speaker_rank: dict[str, int] = {}
        self.metrics: dict[str, Any] = {"translate_ms": [], "tts_ms": [], "blocked": 0, "cache_hits": 0,
                                        "oom": 0, "epoch_bumps": 0, "stale_dropped": 0}
        self.live_final_until_ms = -1
        self.live_queue_ms = 0
        self.live_overflow = False
        self.consumer_queue_ms = 0
        self.stop_acks: list[dict[str, Any]] = []
        self.asr_active = False
        self._tts_consec_fail = 0

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self.db.upsert_video(self.video_id, self.title, self.settings.history_opt_in)
        self.tasks = [asyncio.create_task(self._translate_loop(), name="translate"),
                      asyncio.create_task(self._tts_loop(), name="tts")]

    async def close(self, reason: str = "stopped") -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.sm.to(S.STOPPED, reason)
        except Exception:
            self.sm.state = S.STOPPED
        await self.emit("audio.stop", {"reason": reason, "stop_epoch": self.epoch})
        await self.emit_state()
        for t in self.tasks:
            t.cancel()
        if self.asr_active:
            self.asr_active = False
            try:
                await self.rt.asr_reset("", -1)
            except Exception:
                pass

    def poke(self) -> None:
        self.wake_tr.set()
        self.wake_tts.set()

    # ------------------------------------------------------------------ events
    async def emit(self, event: str, payload: dict[str, Any], request_id: str | None = None) -> None:
        await self.hub.send_event(event, payload, session_id=self.session_id, epoch=self.epoch, request_id=request_id)

    def buffer_ahead_ms(self) -> int:
        """Media có audio sẵn sàng liên tục tính từ playhead."""
        now = self.clock.now_ms()
        covered = now
        for us in self.units:
            u = us.unit
            if u.end_ms <= now:
                continue
            if us.tts_status != "ready":
                break
            covered = u.end_ms
        return max(0, covered - now)

    def snapshot(self) -> dict[str, Any]:
        now = self.clock.now_ms()
        pending = sum(1 for u in self.units if u.unit.end_ms > now and u.status in ("pending", "translating"))
        return {"session_id": self.session_id, "video_id": self.video_id, "tab_id": self.tab_id, "mode": self.mode,
                "timeline_epoch": self.epoch, "state": self.sm.state.value, "reason": self.sm.reason,
                "source": self.source_public(), "media_ms": now, "buffer_media_ms": self.buffer_ahead_ms(),
                "pending_translation": pending, "units": len(self.units),
                "blocked": sum(1 for u in self.units if u.status == "blocked"),
                "lag_ms": self.live_lag_ms(), "live_queue_ms": self.live_queue_ms, "asr_active": self.asr_active,
                "last_error": self.last_error, "audio_consumer": self.hub.has_audio_consumer(self.session_id)}

    def source_public(self) -> dict[str, Any] | None:
        if not self.source:
            return None
        s = self.source
        return {k: s[k] for k in ("source_id", "source_kind", "language", "coverage", "available_until_ms",
                                  "source_revision", "offset_ms")}

    async def emit_state(self) -> None:
        await self.emit("session.state", self.snapshot())

    def set_state(self, st: S, reason: str | None = None) -> bool:
        try:
            return self.sm.to(st, reason)
        except Exception:
            log.info("reject transition %s -> %s (%s)", self.sm.state, st, reason)
            return False

    # ------------------------------------------------------------------ captions
    async def add_captions(self, batch: dict[str, Any], offset_ms: int = 0) -> int:
        """Nhận CaptionBatch đã validate schema. Đổi source_id/revision → epoch mới (timeline đổi)."""
        src_changed = (self.source is None or batch["source_id"] != self.source["source_id"]
                       or batch["source_revision"] != self.source["source_revision"] or offset_ms != self.source["offset_ms"]
                       or batch["language"] != self.source["language"])
        if src_changed and self.source is not None:
            await self.bump_epoch("source_changed")
            self.cues.clear()
            self.units.clear()
            self.by_id.clear()
        self.source = {"source_id": batch["source_id"], "source_kind": batch["source_kind"], "language": batch["language"],
                       "coverage": batch["coverage"], "available_until_ms": batch["available_until_ms"] + offset_ms,
                       "source_revision": batch["source_revision"], "offset_ms": offset_ms}
        added = 0
        for c in batch["cues"]:
            text, speaker = normalize_text(c["text"])
            text, turn = split_turn(text)
            if not text:
                continue
            start, end = c["start_ms"] + offset_ms, c["end_ms"] + offset_ms
            if start < 0 or end < start:
                continue
            self.cues[c["cue_id"]] = Cue(c["cue_id"], start, end, text, c["text"], bool(c["committed"]), speaker,
                                         {"turn": turn, "tag_speaker": speaker is not None})
            added += 1
        self.db.upsert_source(source_id=batch["source_id"], video_id=self.video_id,
                              revision=batch["source_revision"], language=batch["language"],
                              kind=batch["source_kind"], coverage=batch["coverage"],
                              content_hash=content_key([batch["source_id"], batch["source_revision"]]),
                              available_until_ms=batch["available_until_ms"], offset_ms=offset_ms)
        self.rebuild_units()
        if self.sm.state == S.DISCOVERING:
            self.set_state(S.WARMING if not self.rt.translation_ready() else S.BUFFERING, "captions_received")
        await self.emit("source.changed", {"source": self.source_public(), "cues_added": added,
                                           "units": len(self.units)})
        await self.emit_state()
        self.poke()
        return added

    def rebuild_units(self) -> None:
        committed = [c for c in self.cues.values() if c.committed]
        assign_turn_speakers(committed)
        if self.source and self.source["source_kind"] == "auto":
            committed = dedupe_rolling(committed)
        complete = bool(self.source and self.source["coverage"] == "full")
        units = build_units(self.source["source_id"] if self.source else "src", committed, complete=complete)
        if self.mode == "live_delayed" or (self.source and self.source["source_kind"] == "asr"):
            if units and not units[-1].final and units[-1].end_ms <= self.live_final_until_ms:
                units[-1].final = True
                units[-1].boundary_reason = "endpoint"
        new_list: list[UnitState] = []
        new_by: dict[str, UnitState] = {}
        for u in units:
            old = self.by_id.get(u.unit_id)
            if old:
                old.unit = u
                us = old
            else:
                us = UnitState(u)
                self._apply_override(us)
            new_list.append(us)
            new_by[u.unit_id] = us
        self.units, self.by_id = new_list, new_by
        self.speaker_rank = {}
        for us in self.units:
            if us.unit.speaker and us.unit.speaker not in self.speaker_rank:
                self.speaker_rank[us.unit.speaker] = len(self.speaker_rank)
        for us in self.units:                              # người nói đổi (phụ đề được sửa) → giọng đổi → audio mới
            if us.voice and us.tts_status in ("ready", "running") and us.voice != self.voice_for(us):
                us.revision += 1
                us.audio_key, us.audio_ms, us.tts_status, us.delivered, us.voice = None, None, "none", None, None
        for us in self.units:
            if us.unit.final:
                self.db.put_segment({"segment_id": us.unit.unit_id, "source_id": us.unit.source_id, "revision": 1,
                                     "source_hash": us.unit.source_hash, "source_text": us.unit.source_text,
                                     "start_ms": us.unit.start_ms, "end_ms": us.unit.end_ms,
                                     "cue_map_json": json.dumps(us.unit.cue_map), "boundary_reason": us.unit.boundary_reason,
                                     "speaker": us.unit.speaker})

    def _apply_override(self, us: UnitState) -> None:
        ov = self.db.latest_override(us.unit.unit_id)
        if ov:
            us.display, us.spoken = ov["target_display"], ov["target_spoken"]
            us.revision = 1 + int(ov["revision"])
            us.override = True
            us.status = "ready"
            us.flags = ["USER_OVERRIDE"]

    # ------------------------------------------------------------------ live ASR
    async def on_asr_commit(self, ev: dict[str, Any]) -> None:
        if ev.get("epoch") != self.epoch or self.closed:
            self.metrics["stale_dropped"] += 1
            return
        if not self.source or self.source["source_kind"] != "asr":
            self.source = {"source_id": f"asr-{self.session_id}", "source_kind": "asr", "language": "en",
                           "coverage": "current_only", "available_until_ms": 0, "source_revision": 1, "offset_ms": 0}
            self.db.upsert_source(source_id=self.source["source_id"], video_id=self.video_id, revision=1, language="en",
                                  kind="asr", coverage="current_only", content_hash=content_key([self.session_id, "asr"]),
                                  available_until_ms=0)
        cid = ev["cue_id"]
        self.cues[cid] = Cue(cid, int(ev["start_media_ms"]), int(ev["end_media_ms"]), normalize_text(ev["text"])[0],
                             ev["text"], True)
        self.source["available_until_ms"] = max(self.source["available_until_ms"], int(ev["end_media_ms"]))
        if ev.get("endpoint"):
            self.live_final_until_ms = int(ev["end_media_ms"])
        self.rebuild_units()
        if self.sm.state in (S.DISCOVERING, S.WARMING):
            self.set_state(S.BUFFERING, "asr_text")
        await self.emit("source.changed", {"source": self.source_public(), "cues_added": 1, "units": len(self.units),
                                           "committed_text": ev["text"][:500]})
        self.poke()

    def live_lag_ms(self) -> int | None:
        if self.mode != "live_delayed" or not self.units:
            return None
        pending = [u for u in self.units if u.delivered is None]
        if not pending:
            return 0
        return max(0, self.clock.now_ms() - pending[0].unit.start_ms)

    def live_backlog_ms(self) -> int:
        return self.consumer_queue_ms + sum(u.unit.end_ms - u.unit.start_ms for u in self.units
                                            if u.unit.final and u.delivered is None and u.status != "blocked")

    async def check_live_overflow(self) -> None:
        if self.mode != "live_delayed" or self.live_overflow:
            return
        backlog = self.live_backlog_ms()
        self.live_queue_ms = backlog
        cap = self.settings.live_queue_cap_ms
        if backlog >= cap:
            self.live_overflow = True
            self.last_error = "LIVE_QUEUE_OVERFLOW"
            self.set_state(S.ERROR, "LIVE_QUEUE_OVERFLOW")
            await self.emit("audio.stop", {"reason": "LIVE_QUEUE_OVERFLOW", "stop_epoch": self.epoch})
            await self.emit("error", AppError("LIVE_QUEUE_OVERFLOW").to_dict(uuid.uuid4().hex[:12], self.session_id))
            await self.emit_state()
        elif backlog >= 20_000:
            await self.emit("warning", {"code": "LIVE_LAG_HIGH", "backlog_ms": backlog, "level": 2})
        elif backlog >= 12_000:
            await self.emit("warning", {"code": "LIVE_LAG", "backlog_ms": backlog, "level": 1})

    # ------------------------------------------------------------------ clock / control
    async def on_clock(self, c: dict[str, Any]) -> None:
        prev = self.clock
        self.clock = Clock(c["media_ms"], float(c["playback_rate"]), bool(c["paused"]), bool(c["seeking"]),
                           bool(c["stalled"]), c["ad_state"], c["visibility"])
        st = self.sm.state
        if c["ad_state"] != "content" and st != S.AD_HOLD:
            self.set_state(S.AD_HOLD, "ad" if c["ad_state"] == "ad" else "unknown_source")
            await self.emit_state()
        elif c["ad_state"] == "content" and st == S.AD_HOLD:
            self.set_state(S.BUFFERING, "ad_ended")
            await self.emit_state()
        elif c["stalled"] and st in (S.PLAYING, S.BUFFERING):
            self.set_state(S.STALLED, "video_stalled")
            await self.emit_state()
        elif not c["paused"] and not c["stalled"] and st in (S.STALLED, S.PAUSED_USER, S.PAUSED_AUTO, S.SEEKING):
            self.set_state(S.BUFFERING, "resumed")
            await self.emit_state()
        if abs(prev.rate - self.clock.rate) > 1e-6:
            await self.emit("warning", {"code": "RATE_CHANGED", "rate": self.clock.rate})
        self.poke()

    async def bump_epoch(self, reason: str) -> int:
        old = self.epoch
        self.epoch += 1
        self.metrics["epoch_bumps"] += 1
        for us in self.units:
            us.delivered = None
        # consumer dừng ngay theo epoch cũ; broker không chờ kernel hủy
        await self.hub.send_event("audio.stop", {"reason": reason, "stop_epoch": old}, session_id=self.session_id,
                                  epoch=self.epoch)
        if self.asr_active:
            await self.rt.asr_reset(self.session_id, self.epoch)
        return self.epoch

    async def control(self, op: str, body: dict[str, Any]) -> dict[str, Any]:
        if op == "seek":
            self.set_state(S.SEEKING, "user_seek")
            await self.bump_epoch("seek")
            self.clock = Clock(int(body.get("media_ms", self.clock.media_ms)), self.clock.rate, True, True)
            self.live_overflow = False if self.mode != "live_delayed" else self.live_overflow
        elif op == "pause":
            reason = body.get("reason", "USER")
            self.set_state(S.PAUSED_USER if reason == "USER" else S.PAUSED_AUTO, f"pause_{reason.lower()}")
        elif op == "play":
            self.set_state(S.BUFFERING, "play")
        elif op == "mode":
            m = body.get("mode")
            if m not in MODES:
                raise AppError("VALIDATION_FAILED", {"field": "mode"})
            self.mode = m
            await self.bump_epoch("mode_changed")
        elif op == "resume_live":
            # người dùng chấp nhận bỏ đoạn giữa: chuyển epoch rõ ràng, không lặng lẽ
            self.live_overflow = False
            for us in self.units:
                if us.delivered is None and us.unit.end_ms < self.clock.now_ms():
                    us.status = "skipped_by_user" if us.status != "ready" else us.status
                    us.delivered = (-1, us.revision)
            await self.bump_epoch("resume_here")
            self.set_state(S.BUFFERING, "resume_here")
        elif op == "replay":
            sid = body.get("segment_id")
            if sid not in self.by_id:
                raise AppError("NOT_FOUND", {"segment_id": str(sid)})
            await self.bump_epoch("replay")
        elif op == "stop":
            await self.close("user_stop")
        else:
            raise AppError("VALIDATION_FAILED", {"field": "op"})
        await self.emit_state()
        self.poke()
        return {"session_id": self.session_id, "timeline_epoch": self.epoch, "state": self.sm.state.value,
                "mode": self.mode}

    # ------------------------------------------------------------------ scheduling helpers
    def ahead(self, window_ms: int) -> list[UnitState]:
        now = self.clock.now_ms()
        if self.mode == "live_delayed":
            return [u for u in self.units if u.unit.final and u.delivered is None and u.status != "skipped_by_user"]
        horizon = now + int(window_ms * max(1.0, self.clock.rate))
        return [u for u in self.units if u.unit.end_ms > now - 500 and u.unit.start_ms <= horizon]

    def context_for(self, us: UnitState) -> tuple[list[str], list[str]]:
        i = self.units.index(us)
        before = [u.unit.source_text for u in self.units[max(0, i - 2):i]]
        after = [u.unit.source_text for u in self.units[i + 1:i + 2] if u.unit.final]
        return before, after

    # ------------------------------------------------------------------ translation loop
    async def _translate_loop(self) -> None:
        while not self.closed:
            try:
                await asyncio.wait_for(self.wake_tr.wait(), 0.5)
            except asyncio.TimeoutError:
                pass
            self.wake_tr.clear()
            try:
                await self._translate_step()
            except asyncio.CancelledError:
                raise
            except AppError as e:
                self.last_error = e.code
                if e.code == "MODEL_NOT_READY":
                    self.set_state(S.WARMING, "model_not_ready")
                await self.emit("error", e.to_dict(uuid.uuid4().hex[:12], self.session_id))
                await asyncio.sleep(2)
            except Exception:
                log.exception("translate loop")
                await asyncio.sleep(1)

    async def _translate_step(self) -> None:
        if self.sm.state in (S.STOPPED, S.ERROR) or not self.rt.translation_ready():
            return
        fp = self.rt.fingerprint()
        if fp is None:
            return
        cands = [u for u in self.ahead(self.settings.high_water_ms) if u.status == "pending" and u.unit.final]
        if not cands:
            return
        batch = plan_batches([UnitRequest(u.unit.unit_id, u.unit.source_text, u.unit.source_hash, *self.context_for(u))
                              for u in cands])[0]
        states = [self.by_id[r.segment_id] for r in batch]
        for s in states:
            s.status = "translating"
        t0 = time.perf_counter()
        source_epoch = self.epoch
        try:
            results = await translate_batch(self.rt, batch, topic=self.settings.topic, glossary=self.glossary, fp=fp,
                                            cache=_DbCache(self.db), source_language=self.source["language"] if self.source else "und")
        except BaseException:
            for s in states:
                if s.status == "translating":
                    s.status = "pending"
            raise
        self.metrics["translate_ms"].append(round((time.perf_counter() - t0) * 1000, 1))
        if self.closed or self.epoch != source_epoch:
            return
        for r in results:
            us = self.by_id.get(r.segment_id)
            if us is None or us.override:
                continue
            self._store_result(us, r, fp)
            if r.status == "READY":
                await self.emit("translation.ready", {"segment_id": us.unit.unit_id, "revision": us.revision,
                                                      "target_display": us.display, "target_spoken": us.spoken,
                                                      "source_text": us.unit.source_text, "flags": us.flags,
                                                      "start_ms": us.unit.start_ms, "end_ms": us.unit.end_ms})
            else:
                self.metrics["blocked"] += 1
                await self.emit("translation.blocked", {"segment_id": us.unit.unit_id, "revision": us.revision,
                                                        "code": r.error_code, "flags": r.flags,
                                                        "source_text": us.unit.source_text,
                                                        "start_ms": us.unit.start_ms, "end_ms": us.unit.end_ms})
        self.poke()

    def _store_result(self, us: UnitState, r: UnitResult, fp: ModelFingerprint) -> None:
        us.cache_key = r.cache_key
        us.flags = r.flags
        us.from_cache = r.from_cache
        if r.from_cache:
            self.metrics["cache_hits"] += 1
        if r.status == "READY":
            us.status, us.display, us.spoken, us.error = "ready", r.target_display, r.target_spoken, None
        else:
            us.status, us.error = "blocked", r.error_code
        us.translation_id = self.db.put_translation({
            "segment_id": us.unit.unit_id, "revision": us.revision, "cache_key": r.cache_key,
            "model_fingerprint": fp.value(), "prompt_version": PROMPT_VERSION, "glossary_version": self.glossary.version,
            "context_hash": r.context_hash, "target_display": r.target_display or "", "target_spoken": r.target_spoken or "",
            "flags": r.flags, "status": "READY" if r.status == "READY" else "BLOCKED"})

    # ------------------------------------------------------------------ TTS loop
    async def _tts_loop(self) -> None:
        while not self.closed:
            try:
                await asyncio.wait_for(self.wake_tts.wait(), 0.5)
            except asyncio.TimeoutError:
                pass
            self.wake_tts.clear()
            try:
                progressed = await self._tts_step()
                await self.deliver()
                await self.update_buffer_state()
                if self.mode == "live_delayed":
                    await self.check_live_overflow()
                if progressed:
                    self.wake_tts.set()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("tts loop")
                await asyncio.sleep(1)

    async def _tts_step(self) -> bool:
        if self.sm.state in (S.STOPPED, S.ERROR) or not self.rt.tts_ready():
            return False
        if self.mode == "live_delayed" and self.live_overflow:
            return False
        cands = [u for u in self.ahead(self.settings.prefetch_target_ms) if u.status == "ready" and u.tts_status == "none"]
        if not cands:
            return False
        us = cands[0]
        voice = self.voice_for(us)
        sdk, model_rev = self.rt.tts_versions()
        key = audio_cache_key(display=us.display, spoken=us.spoken, voice_id=voice,
                              voice_fingerprint=self.rt.voice_fingerprint(voice), sdk_version=sdk,
                              tts_model_revision=model_rev, controls={"watermark": self.settings.watermark})
        rev = us.revision
        hit = self.cache.get(key)
        if hit:
            us.audio_key, us.audio_ms, us.tts_status, us.voice = key, hit.duration_ms, "ready", voice
            return True
        us.tts_status = "running"
        t0 = time.perf_counter()
        try:
            pcm, _info = await self.rt.synth(us.spoken, voice)
        except AppError as e:
            action = self.rt.on_tts_failure(e.code)
            us.tts_status = "none" if action == "retry" else "failed"
            us.tts_error = e.code
            self.last_error = e.code
            if e.code == "GPU_OOM":
                self.metrics["oom"] += 1
            await self.emit("error", e.to_dict(uuid.uuid4().hex[:12], self.session_id) | {"segment_id": us.unit.unit_id})
            if action == "stop":
                self.set_state(S.ERROR, e.code)
                await self.emit("audio.stop", {"reason": e.code, "stop_epoch": self.epoch})
                await self.emit_state()
            else:
                await asyncio.sleep(1.0)
            return False
        self.metrics["tts_ms"].append(round((time.perf_counter() - t0) * 1000, 1))
        if us.revision != rev or self.closed:          # override trong lúc tạo tiếng → bỏ kết quả cũ
            us.tts_status = "none"
            self.metrics["stale_dropped"] += 1
            return True
        entry = self.cache.put(key, pcm, sample_rate=TTS_RATE, translation_id=us.translation_id,
                               voice_fingerprint=self.rt.voice_fingerprint(voice), sdk_version=sdk)
        us.audio_key, us.audio_ms, us.tts_status, us.voice = key, entry.duration_ms, "ready", voice
        return True

    # ------------------------------------------------------------------ delivery
    async def deliver(self) -> None:
        if self.closed or not self.hub.has_audio_consumer(self.session_id):
            return
        if self.sm.state in (S.AD_HOLD, S.STOPPED, S.ERROR, S.SOURCE_LOST):
            return
        window = self.settings.high_water_ms
        for us in self.ahead(window):
            if us.tts_status != "ready" or us.delivered == (self.epoch, us.revision):
                continue
            entry = self.cache.get(us.audio_key or "")
            if entry is None:
                us.tts_status = "none"
                continue
            await self.send_audio(us, entry.pcm)

    async def send_audio(self, us: UnitState, pcm: bytes) -> None:
        epoch, rev = self.epoch, us.revision
        u = us.unit
        nxt = next((x.unit.start_ms for x in self.units if x.unit.start_ms > u.start_ms), None)
        await self.emit("audio.begin", {"segment_id": u.unit_id, "revision": rev, "start_ms": u.start_ms,
                                        "end_ms": u.end_ms, "next_start_ms": nxt, "sample_rate": TTS_RATE,
                                        "channels": 1, "codec": "pcm_s16le", "duration_ms": us.audio_ms,
                                        "target_display": us.display, "source_text": u.source_text,
                                        "voice_id": us.voice, "speaker": u.speaker})
        parts = split_pcm(pcm)
        for i, part in enumerate(parts):
            if self.epoch != epoch or us.revision != rev or self.closed:
                return                                   # seek/override giữa chừng: dừng giao
            hdr = {"protocol_version": 1, "kind": "tts_pcm", "session_id": self.session_id, "timeline_epoch": epoch,
                   "segment_id": u.unit_id, "revision": rev, "seq": i, "sample_rate": TTS_RATE, "channels": 1,
                   "codec": "pcm_s16le", "sample_count": len(part) // 2, "is_last": i == len(parts) - 1}
            await self.hub.send_binary(self.session_id, pack_frame(hdr, part))
        await self.emit("audio.end", {"segment_id": u.unit_id, "revision": rev, "duration_ms": us.audio_ms,
                                      "complete": True, "digest": sha256_hex(pcm)[:16], "frames": len(parts)})
        us.delivered = (epoch, rev)

    async def update_buffer_state(self) -> None:
        st = self.sm.state
        if st in (S.BUFFERING, S.WARMING) and self.rt.translation_ready() and self.rt.tts_ready():
            if not self.clock.paused and (self.buffer_ahead_ms() >= min(3000, self.settings.low_water_ms)
                                          or self.mode == "live_delayed"):
                if self.set_state(S.PLAYING, "buffer_ready"):
                    await self.emit_state()
        elif st == S.PLAYING and self.mode != "live_delayed":
            ahead = [u for u in self.ahead(self.settings.low_water_ms) if u.unit.start_ms > self.clock.now_ms()]
            if ahead and ahead[0].tts_status != "ready" and self.buffer_ahead_ms() < 500:
                if self.set_state(S.BUFFERING, "low_water"):
                    await self.emit_state()

    # ------------------------------------------------------------------ editing
    async def apply_override(self, segment_id: str, display: str, spoken: str | None, expected_revision: int | None) -> UnitState:
        us = self.by_id.get(segment_id)
        if us is None:
            raise AppError("NOT_FOUND", {"segment_id": segment_id})
        if expected_revision is not None and expected_revision != us.revision:
            raise AppError("REVISION_CONFLICT", {"expected": expected_revision, "actual": us.revision})
        display = display.strip()
        if not display or len(display) > 8000:
            raise AppError("VALIDATION_FAILED", {"field": "target_display"})
        spoken_final = (spoken or "").strip() or to_spoken(display)
        _oid, orev = self.db.put_override(segment_id, display, spoken_final)
        us.display, us.spoken, us.override, us.status = display, spoken_final, True, "ready"
        us.revision = max(us.revision + 1, 1 + orev)          # revision trong phiên chỉ tăng
        us.flags = ["USER_OVERRIDE"]
        us.audio_key, us.audio_ms, us.tts_status, us.delivered = None, None, "none", None
        await self.emit("audio.stop", {"reason": "revision_changed", "segment_id": segment_id,
                                       "stop_revision_below": us.revision})
        await self.emit("translation.ready", {"segment_id": segment_id, "revision": us.revision,
                                              "target_display": us.display, "target_spoken": us.spoken,
                                              "source_text": us.unit.source_text, "flags": us.flags,
                                              "start_ms": us.unit.start_ms, "end_ms": us.unit.end_ms})
        self.poke()
        return us

    async def undo_override(self, segment_id: str) -> UnitState:
        """Hoàn tác bản sửa gần nhất: về bản sửa trước đó, hoặc về bản MÁY DỊCH đã lưu (kể cả câu đã qua playhead)."""
        us = self.by_id.get(segment_id)
        if us is None:
            raise AppError("NOT_FOUND", {"segment_id": segment_id})
        hist = self.db.override_history(segment_id)
        if not hist:
            raise AppError("NOT_FOUND", {"reason": "no_override"})
        self.db.delete_override_revision(segment_id, hist[-1]["revision"])
        prev = hist[-2] if len(hist) > 1 else None
        us.revision += 1                                   # không chèn lại lịch sử: revision chỉ tăng
        us.audio_key, us.audio_ms, us.tts_status, us.delivered, us.voice = None, None, "none", None, None
        if prev:                                           # về bản sửa trước đó (không ghi lại vào DB)
            us.override, us.status, us.flags, us.error = True, "ready", ["USER_OVERRIDE"], None
            us.display, us.spoken = prev["target_display"], prev["target_spoken"]
        else:
            us.override = False
            machine = self.db.get_translation_by_key(us.cache_key) if us.cache_key else None
            machine = machine or self.db.latest_machine_translation(segment_id, PROMPT_VERSION)  # tránh dùng bản dịch cũ sai ngôn ngữ
            if machine and machine["status"] == "READY":
                us.status, us.display, us.spoken, us.flags, us.error = \
                    "ready", machine["target_display"], machine["target_spoken"], list(machine["flags"]), None
            else:
                us.status, us.display, us.spoken, us.flags = "pending", "", "", []     # chưa có bản máy → dịch lại khi tới
        await self.emit("audio.stop", {"reason": "revision_changed", "segment_id": segment_id,
                                       "stop_revision_below": us.revision})
        if us.status == "ready":
            await self.emit("translation.ready", {"segment_id": segment_id, "revision": us.revision,
                                                  "target_display": us.display, "target_spoken": us.spoken,
                                                  "source_text": us.unit.source_text, "flags": us.flags,
                                                  "start_ms": us.unit.start_ms, "end_ms": us.unit.end_ms})
        self.poke()
        return us

    async def retranslate(self, segment_id: str) -> None:
        us = self.by_id.get(segment_id)
        if us is None:
            raise AppError("NOT_FOUND", {"segment_id": segment_id})
        fp = self.rt.fingerprint()
        if fp is None or not self.rt.translation_ready():
            raise AppError("MODEL_NOT_READY")
        before, after = self.context_for(us)
        req = UnitRequest(us.unit.unit_id, us.unit.source_text, us.unit.source_hash, before, after)
        # bỏ qua cache để dịch lại thật; sampling khác seed để có phương án mới
        fp2 = ModelFingerprint(fp.model_id, fp.alias, fp.artifact_sha256, fp.runtime_build,
                               {**fp.sampling, "seed": int(time.time()) % 100000})
        source_epoch = self.epoch
        [r] = await translate_batch(self.rt, [req], topic=self.settings.topic, glossary=self.glossary, fp=fp2, cache=None,
                                    source_language=self.source["language"] if self.source else "und")
        if self.closed or self.epoch != source_epoch:
            return
        us.override = False
        us.revision += 1
        self._store_result(us, r, fp2)
        us.audio_key, us.audio_ms, us.tts_status, us.delivered = None, None, "none", None
        await self.emit("audio.stop", {"reason": "revision_changed", "segment_id": segment_id,
                                       "stop_revision_below": us.revision})
        ev = "translation.ready" if r.status == "READY" else "translation.blocked"
        await self.emit(ev, {"segment_id": segment_id, "revision": us.revision, "target_display": us.display,
                             "target_spoken": us.spoken, "source_text": us.unit.source_text, "flags": us.flags,
                             "code": r.error_code, "start_ms": us.unit.start_ms, "end_ms": us.unit.end_ms})
        self.poke()

    def invalidate_glossary(self, glossary: Glossary) -> int:
        """Glossary mới → chỉ unit TƯƠNG LAI chưa override bị dịch lại; câu đã nghe không đổi âm thầm."""
        self.glossary = glossary
        now = self.clock.now_ms()
        n = 0
        for us in self.units:
            if us.unit.start_ms > now and not us.override and us.status in ("ready", "blocked"):
                us.status, us.tts_status, us.audio_key, us.delivered = "pending", "none", None, None
                n += 1
        self.poke()
        return n

    def invalidate_voice(self) -> int:
        n = 0
        now = self.clock.now_ms()
        for us in self.units:
            if us.unit.end_ms > now and us.tts_status in ("ready", "failed"):
                us.tts_status, us.audio_key, us.delivered = "none", None, None
                n += 1
        self.poke()
        return n

    def voice_for(self, us: UnitState) -> str:
        """Người nói thứ 2, 4… (theo thứ tự xuất hiện) đọc bằng giọng thứ hai khi bật đổi giọng."""
        main = self.settings.voice
        sp = us.unit.speaker
        if not self.settings.alternate_speakers or not sp or self.speaker_rank.get(sp, 0) % 2 == 0:
            return main
        alt = self.settings.voice_alt if self.settings.voice_alt and self.settings.voice_alt != main else None
        return alt or pick_alt_voice(main, list(getattr(self.rt, "voices", []) or [])) or main

    def transcript(self) -> list[dict[str, Any]]:
        return [u.public() for u in self.units]


class _DbCache:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str) -> dict[str, Any] | None:
        return self.db.get_translation_by_key(key)
