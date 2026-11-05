"""Broker FastAPI (docs/08): REST + WebSocket loopback-only, Bearer + Origin/Host, giới hạn kích thước, lỗi có mã.

Không endpoint nào chạy lệnh/URL tùy ý. Đường dẫn tệp đều do server tạo.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from .. import APP_VERSION, PROTOCOL_VERSION
from ..audio_frame import TTS_RATE, pack_frame, split_pcm, unpack_frame
from ..contracts import strict_loads, validate, validate_caption_batch, validate_clock
from ..errors import AppError
from ..hashing import content_key
from ..paths import AppPaths, REPO_ROOT
from ..runtime import system
from ..storage.audio_cache import AudioCache
from ..storage.db import Database
from ..subtitles import write_srt, write_vtt
from ..translation.glossary import Glossary, merge_import
from .events import Conn, Hub
from .runtime import BrokerRuntime
from .security import Idempotency, RateLimiter, TokenStore, bearer, host_ok, redact
from .session import Session, Settings as SessionSettings
from .settings_store import merged, validate_patch
from .setup import FirstRunSetup

log = logging.getLogger("vietdub.broker")

BODY_LIMITS = {"/captions": 1024 * 1024, "/v1/glossary": 1024 * 1024}
DEFAULT_BODY_LIMIT = 64 * 1024
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


@dataclass
class Ctx:
    paths: AppPaths
    db: Database
    cache: AudioCache
    rt: BrokerRuntime
    hub: Hub
    tokens: TokenStore
    port: int
    idem: Idempotency = field(default_factory=Idempotency)
    rate: RateLimiter = field(default_factory=lambda: RateLimiter(per_sec=60, burst=240))
    session: Session | None = None
    started: float = field(default_factory=time.time)
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    startup_task: asyncio.Task | None = None
    setup: FirstRunSetup | None = None

    def settings(self) -> dict[str, Any]:
        return merged(self.db.get_setting("app_settings"))

    def glossary(self) -> Glossary:
        return Glossary.from_dict(self.db.load_glossary())

    def session_settings(self) -> SessionSettings:
        s = self.settings()
        return SessionSettings(topic=s["translation"]["topic"], voice=s["tts"]["voice_id"],
                               prefetch_target_ms=s["playback"]["prefetch_target_ms"],
                               low_water_ms=s["playback"]["low_water_ms"], high_water_ms=s["playback"]["high_water_ms"],
                               live_queue_cap_ms=s["playback"]["live_queue_hard_cap_ms"],
                               history_opt_in=s["storage"]["history_opt_in"], watermark=s["tts"]["watermark"],
                               alternate_speakers=s["tts"]["alternate_speakers"], voice_alt=s["tts"]["voice_alt_id"])


def err_response(e: AppError, request_id: str = "none", session_id: str | None = None) -> JSONResponse:
    return JSONResponse(e.to_dict(request_id, session_id), status_code=e.http_status)


def create_app(ctx: Ctx) -> FastAPI:
    app = FastAPI(title="VietDub Local broker", version=APP_VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    ctx.setup = FirstRunSetup(ctx)

    # ------------------------------------------------------------------ middleware
    @app.middleware("http")
    async def guard(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        path = request.url.path
        origin = request.headers.get("origin")
        if not host_ok(request.headers.get("host"), ctx.port):
            return err_response(AppError("ORIGIN_DENIED", {"reason": "host"}), rid)
        if "token" in request.query_params or "access_token" in request.query_params:
            return err_response(AppError("AUTH_REQUIRED", {"reason": "token_in_query"}), rid)
        if origin is not None and not ctx.tokens.origin_allowed(origin):
            return err_response(AppError("ORIGIN_DENIED"), rid)          # website thù địch / Origin null
        if request.method == "OPTIONS":
            return _cors(Response(status_code=204), origin, preflight=True)
        limit = next((v for k, v in BODY_LIMITS.items() if path.endswith(k)), DEFAULT_BODY_LIMIT)
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > limit:
            return err_response(AppError("PAYLOAD_TOO_LARGE", {"limit": limit}), rid)
        if path.startswith("/v1/"):
            try:
                info = ctx.tokens.check(bearer(request.headers.get("authorization")), origin)
            except AppError as e:
                return _cors(err_response(e, rid), origin)
            if not ctx.rate.allow(info.origin):
                return _cors(err_response(AppError("RATE_LIMITED"), rid), origin)
            body = await request.body()
            if len(body) > limit:
                return _cors(err_response(AppError("PAYLOAD_TOO_LARGE", {"limit": limit}), rid), origin)
            if ctx.setup.busy and request.method != "GET" and (path.startswith("/v1/models/") or path == "/v1/sessions"):
                return _cors(err_response(AppError("MODEL_NOT_READY", {"reason": "setup_in_progress"}), rid), origin)
        request.state.rid = rid
        try:
            resp = await call_next(request)
        except AppError as e:
            resp = err_response(e, rid, ctx.session.session_id if ctx.session else None)
        except Exception as e:  # noqa: BLE001
            log.error("unhandled %s: %s", path, redact(repr(e))[:300])
            resp = err_response(AppError("INTERNAL"), rid)
        return _cors(resp, origin)

    def _cors(resp: Response, origin: str | None, preflight: bool = False) -> Response:
        if origin and ctx.tokens.origin_allowed(origin):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            if preflight:
                resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE"
                resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, If-Match, X-Request-Id, Idempotency-Key"
                resp.headers["Access-Control-Max-Age"] = "600"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.exception_handler(AppError)
    async def app_error(request: Request, e: AppError):
        return err_response(e, getattr(request.state, "rid", "none"), ctx.session.session_id if ctx.session else None)

    async def body_json(request: Request) -> dict[str, Any]:
        raw = await request.body()
        try:
            obj = strict_loads(raw or b"{}")
        except ValueError:
            raise AppError("VALIDATION_FAILED", {"field": "json"}) from None
        if not isinstance(obj, dict):
            raise AppError("VALIDATION_FAILED", {"field": "json"})
        return obj

    def need_session(session_id: str) -> Session:
        s = ctx.session
        if s is None or s.session_id != session_id or s.closed:
            raise AppError("NOT_FOUND", {"reason": "session"})
        return s

    # ------------------------------------------------------------------ pairing (native host only)
    @app.post("/internal/pair")
    async def pair(request: Request):
        if request.headers.get("origin") is not None:
            raise AppError("ORIGIN_DENIED")
        b = await body_json(request)
        tok, exp = ctx.tokens.issue(request.headers.get("x-vietdub-pairing", ""), str(b.get("extension_origin", "")))
        return {"session_token": tok, "expires_at": int(exp), "protocol_version": PROTOCOL_VERSION,
                "broker_url": f"http://127.0.0.1:{ctx.port}"}

    @app.post("/internal/shutdown")
    async def internal_shutdown(request: Request):
        import hmac
        if request.headers.get("origin") is not None or not hmac.compare_digest(
                request.headers.get("x-vietdub-pairing", "").encode(), ctx.tokens.pairing_secret.encode()):
            raise AppError("AUTH_REQUIRED")
        asyncio.get_running_loop().call_later(0.2, _request_exit)
        return {"ok": True}

    # ------------------------------------------------------------------ health/status
    @app.get("/health")
    async def health():
        return {"protocol_version": PROTOCOL_VERSION, "state": "ok"}

    @app.get("/v1/status")
    async def status():
        s = ctx.session
        h = await ctx.rt.health()
        gpu = await asyncio.to_thread(system.gpu_info)
        return {"app_version": APP_VERSION, "protocol_version": PROTOCOL_VERSION, "uptime_s": round(time.time() - ctx.started),
                "runtime": h, "gpu": gpu, "private_mode": ctx.db.private, "cache_disk_full": ctx.cache.disk_full,
                "session": s.snapshot() if s and not s.closed else None}

    @app.get("/v1/env")
    async def env():
        return await asyncio.to_thread(system.env_report, ctx.paths.home, ctx.rt.rts, ctx.rt.model_states())

    @app.get("/v1/about")
    async def about():
        notices = (REPO_ROOT / "THIRD_PARTY_NOTICES.md")
        return {"app_version": APP_VERSION, "protocol_version": PROTOCOL_VERSION,
                "runtime_build": ctx.rt.rts.llama_build, "tts": ctx.rt.tts_info.get("sdk_version"),
                "models": [{"model_id": m["id"], "repo": m["repo"], "revision": m["revision"], "license": m.get("license")}
                           for m in ctx.rt.models.catalog.values()],
                "notices_md": notices.read_text(encoding="utf-8") if notices.exists() else None}

    @app.get("/v1/setup")
    async def setup_status():
        return ctx.setup.snapshot()

    @app.post("/v1/setup", status_code=202)
    async def setup_start(request: Request):
        return ctx.setup.start(await body_json(request))

    @app.post("/v1/setup/pause", status_code=202)
    async def setup_pause():
        return ctx.setup.pause()

    # ------------------------------------------------------------------ models
    @app.get("/v1/models")
    async def models():
        active = ctx.rt.llama.model_id
        out = []
        for mid in ctx.rt.models.catalog:
            st = ctx.rt.models.status(mid, verified_cache=ctx.rt.verified)
            st["active"] = mid == active
            out.append(st)
        return {"models": out, "active_translation": active, "translation_state": ctx.rt.translation_state}

    @app.post("/v1/models/{model_id}/download", status_code=202)
    async def model_download(model_id: str, request: Request):
        b = await body_json(request)
        job = ctx.rt.models.start_download(model_id, consent=b.get("consent") is True,
                                           accepted_size_bytes=b.get("accepted_size_bytes"))
        return {"job_id": job.job_id, "state": job.state}

    @app.post("/v1/models/{model_id}/pause", status_code=202)
    async def model_pause(model_id: str):
        for j in ctx.rt.models.jobs.values():
            if j.model_id == model_id:
                ctx.rt.models.pause(j.job_id)
        return {"ok": True}

    @app.post("/v1/models/{model_id}/verify", status_code=202)
    async def model_verify(model_id: str):
        if model_id not in ctx.rt.models.catalog:
            raise AppError("NOT_FOUND", {"model_id": model_id})
        ok = (await ctx.rt.verify_models([model_id]))[model_id]
        return {"model_id": model_id, "verified": ok}

    @app.post("/v1/models/{model_id}/activate", status_code=202)
    async def model_activate(model_id: str):
        m = ctx.rt.models.catalog.get(model_id)
        if not m or m["kind"] != "translation":
            raise AppError("NOT_FOUND", {"model_id": model_id})
        if not ctx.rt.verified.get(model_id):
            ok = (await ctx.rt.verify_models([model_id]))[model_id]
            if not ok:
                raise AppError("MODEL_NOT_READY", {"model_id": model_id})
        job_id = f"act-{model_id}-{int(time.time()*1000)}"

        async def run():
            try:
                await ctx.rt.activate_translation(model_id)
                s = ctx.db.get_setting("app_settings") or {}
                s.setdefault("translation", {})["model_id"] = model_id
                ctx.db.put_setting("app_settings", s)
                if ctx.session:
                    ctx.session.poke()
            except AppError:
                pass
        asyncio.create_task(run())
        return {"job_id": job_id}

    @app.post("/v1/models/{model_id}/import", status_code=202)
    async def model_import(model_id: str):
        """Mở hộp thoại chọn tệp trên máy (companion). Trình duyệt không cung cấp đường dẫn."""
        from ..companion.dialogs import pick_file
        path = await asyncio.to_thread(pick_file, "Chọn tệp mô hình .gguf", [("GGUF", "*.gguf")])
        if not path:
            return {"imported": False, "reason": "cancelled"}
        ok = await ctx.rt.models.import_file(model_id, path)
        ctx.rt.verified[model_id] = ok
        return {"imported": ok}

    @app.delete("/v1/models/{model_id}", status_code=204)
    async def model_delete(model_id: str):
        if model_id not in ctx.rt.models.catalog:
            raise AppError("NOT_FOUND", {"model_id": model_id})
        active = {ctx.rt.llama.model_id} if ctx.rt.llama.model_id else set()
        if ctx.rt.tts_ready():
            active |= {"vieneu_v3_turbo", "moss_audio_tokenizer_nano"}
        if ctx.rt.asr_state == "ready":
            active.add("whisper_small_en")
        ctx.rt.models.delete(model_id, active_ids=active)
        ctx.rt.verified.pop(model_id, None)
        return Response(status_code=204)

    # ------------------------------------------------------------------ voices
    @app.get("/v1/voices")
    async def voices():
        if not ctx.rt.tts_ready():
            raise AppError("MODEL_NOT_READY", {"reason": "tts"})
        return {"voices": ctx.rt.voices, "aliases": ctx.rt.voice_aliases,
                "selected": ctx.settings()["tts"]["voice_id"]}

    @app.post("/v1/voices/preview", status_code=202)
    async def voice_preview(request: Request):
        b = await body_json(request)
        voice = str(b.get("voice_id", ""))
        text = str(b.get("text") or "Xin chào, đây là giọng đọc thử cho VietDub Local. Mở Inspector rồi bấm Play.")[:300]
        if not ctx.rt.resolve_voice(voice):
            raise AppError("VOICE_NOT_FOUND", {"voice_id": voice[:60]})
        job_id = "pv-" + uuid.uuid4().hex[:12]

        async def run():
            try:
                pcm, _ = await ctx.rt.synth(text, voice)
            except AppError as e:
                await ctx.hub.send_event("error", e.to_dict(job_id), session_id=None, epoch=0)
                return
            parts = split_pcm(pcm)
            await ctx.hub.send_event("audio.begin", {"segment_id": job_id, "revision": 1, "preview": True,
                                                     "sample_rate": TTS_RATE, "duration_ms": round(len(pcm) / 96)},
                                     session_id=None, epoch=0)
            for i, part in enumerate(parts):
                hdr = {"protocol_version": 1, "kind": "tts_pcm", "session_id": "preview", "timeline_epoch": 0,
                       "segment_id": job_id, "revision": 1, "seq": i, "sample_rate": TTS_RATE, "channels": 1,
                       "codec": "pcm_s16le", "sample_count": len(part) // 2, "is_last": i == len(parts) - 1}
                for c in list(ctx.hub.conns):
                    if c.role == "audio":
                        try:
                            async with c.send_lock:
                                await c.ws.send_bytes(pack_frame(hdr, part))
                        except Exception:
                            ctx.hub.remove(c)
            await ctx.hub.send_event("audio.end", {"segment_id": job_id, "revision": 1, "preview": True,
                                                   "complete": True}, session_id=None, epoch=0)
        asyncio.create_task(run())
        return {"job_id": job_id}

    # ------------------------------------------------------------------ sessions
    @app.post("/v1/sessions", status_code=201)
    async def create_session(request: Request):
        b = await body_json(request)
        vid = str(b.get("video_id", ""))
        if not VIDEO_ID_RE.match(vid) or not isinstance(b.get("tab_id"), int):
            raise AppError("VALIDATION_FAILED", {"field": "video_id"})
        if b.get("source_language", "en") != "en" or b.get("target_language", "vi") != "vi":
            raise AppError("VALIDATION_FAILED", {"field": "language"})
        key = b.get("request_id")
        fp = content_key({k: b.get(k) for k in ("video_id", "tab_id", "mode")})
        hit = ctx.idem.check(key, fp)
        if hit:
            return hit
        if ctx.session and not ctx.session.closed:
            await ctx.session.close("replaced_by_new_session")    # hành động user → dừng phiên cũ trước
        title = b.get("title") if isinstance(b.get("title"), str) else None
        s = Session(video_id=vid, tab_id=b["tab_id"], mode=b.get("mode", "vod_sync"), runtime=ctx.rt, db=ctx.db,
                    cache=ctx.cache, hub=ctx.hub, settings=ctx.session_settings(), glossary=ctx.glossary(),
                    title=title[:300] if title else None)
        ctx.session = s
        ctx.rt.asr_consumer = _asr_event
        s.start()
        res = {"session_id": s.session_id, "timeline_epoch": s.epoch, "state": s.sm.state.value, "mode": s.mode}
        ctx.idem.remember(key, fp, res)
        return res

    async def _asr_event(ev: dict[str, Any]) -> None:
        s = ctx.session
        if not s or s.closed or ev.get("session_id") != s.session_id:
            return
        if ev["op"] == "asr.commit":
            await s.on_asr_commit(ev)
        elif ev["op"] == "asr.draft":
            await s.emit("asr.draft", {k: ev.get(k) for k in ("text", "start_media_ms", "end_media_ms", "reason")})
        elif ev["op"] == "asr.status":
            await s.emit("warning", {"code": "ASR_GAP", "seq": ev.get("seq")})

    @app.get("/v1/sessions/{session_id}")
    async def get_session(session_id: str):
        return need_session(session_id).snapshot()

    @app.get("/v1/sessions/{session_id}/segments")
    async def get_segments(session_id: str):
        s = need_session(session_id)
        return {"session_id": s.session_id, "timeline_epoch": s.epoch, "segments": s.transcript()}

    @app.delete("/v1/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str):
        s = ctx.session
        if s and s.session_id == session_id:
            await s.close("user_stop")
            if s.asr_active:
                s.asr_active = False
        return Response(status_code=204)

    @app.post("/v1/sessions/{session_id}/captions", status_code=202)
    async def post_captions(session_id: str, request: Request):
        s = need_session(session_id)
        b = await body_json(request)
        offset = b.pop("offset_ms", 0)
        if not isinstance(offset, int) or abs(offset) > 600_000:
            raise AppError("VALIDATION_FAILED", {"field": "offset_ms"})
        validate_caption_batch(b, session_id=s.session_id, epoch=s.epoch)
        n = await s.add_captions(b, offset)
        return {"job_id": "cap-" + uuid.uuid4().hex[:10], "state": s.sm.state.value, "accepted_count": n,
                "timeline_epoch": s.epoch}

    @app.post("/v1/sessions/{session_id}/clock", status_code=204)
    async def post_clock(session_id: str, request: Request):
        s = need_session(session_id)
        b = await body_json(request)
        validate_clock(b, session_id=s.session_id, epoch=s.epoch, video_id=s.video_id)
        await s.on_clock(b)
        return Response(status_code=204)

    @app.post("/v1/sessions/{session_id}/control", status_code=202)
    async def post_control(session_id: str, request: Request):
        s = need_session(session_id)
        b = await body_json(request)
        op = b.get("op")
        if op in ("asr_start", "asr_stop"):
            return await _asr_control(s, op)
        return await s.control(str(op), b)

    async def _asr_control(s: Session, op: str) -> dict[str, Any]:
        if op == "asr_start":
            await ctx.rt.start_asr()
            await ctx.rt.asr_reset(s.session_id, s.epoch)
            s.asr_active = True
            if s.mode == "vod_sync":
                s.mode = "live_delayed"
        else:
            if s.asr_active:
                try:
                    await ctx.rt.asr_flush(s.epoch)
                except AppError:
                    pass
            s.asr_active = False
        await s.emit_state()
        return {"session_id": s.session_id, "timeline_epoch": s.epoch, "state": s.sm.state.value, "mode": s.mode,
                "asr_active": s.asr_active}

    # ------------------------------------------------------------------ segments
    @app.patch("/v1/segments/{segment_id}")
    async def patch_segment(segment_id: str, request: Request):
        s = ctx.session
        if not s or s.closed:
            raise AppError("NOT_FOUND", {"reason": "session"})
        b = await body_json(request)
        im = request.headers.get("if-match")
        expected = int(im) if im and im.isdigit() else b.get("revision")
        us = await s.apply_override(segment_id, str(b.get("target_display", "")), b.get("target_spoken"), expected)
        return {"version": us.revision, "value": us.public()}

    @app.post("/v1/segments/{segment_id}/undo")
    async def undo_segment(segment_id: str):
        s = ctx.session
        if not s or s.closed or segment_id not in s.by_id:
            raise AppError("NOT_FOUND", {"segment_id": segment_id})
        us = await s.undo_override(segment_id)
        return {"version": us.revision, "value": us.public()}

    @app.post("/v1/segments/{segment_id}/retranslate", status_code=202)
    async def retranslate(segment_id: str):
        s = ctx.session
        if not s or s.closed:
            raise AppError("NOT_FOUND", {"reason": "session"})
        await s.retranslate(segment_id)
        return {"job_id": "rt-" + uuid.uuid4().hex[:10], "value": s.by_id[segment_id].public()}

    # ------------------------------------------------------------------ glossary/settings
    @app.get("/v1/glossary")
    async def get_glossary():
        g = ctx.db.load_glossary()
        return {"version": g["version"], "value": g}

    @app.put("/v1/glossary")
    async def put_glossary(request: Request):
        b = await body_json(request)
        im = request.headers.get("if-match")
        expected = int(im) if im and im.isdigit() else b.get("version")
        entries = b.get("entries")
        if not isinstance(entries, list) or len(entries) > 5000:
            raise AppError("VALIDATION_FAILED", {"field": "entries"})
        try:
            g = Glossary.from_dict({"version": 1, "entries": entries})
        except (ValueError, KeyError, TypeError) as e:
            raise AppError("VALIDATION_FAILED", {"field": str(e)[:80]}) from None
        try:
            v = ctx.db.replace_glossary([e.to_dict() for e in g.entries], expected)
        except ValueError:
            raise AppError("REVISION_CONFLICT") from None
        n = 0
        if ctx.session and not ctx.session.closed:
            n = ctx.session.invalidate_glossary(ctx.glossary())
        return {"version": v, "value": ctx.db.load_glossary(), "invalidated_future_units": n}

    @app.post("/v1/glossary/import")
    async def import_glossary(request: Request):
        b = await body_json(request)
        cur = ctx.glossary()
        try:
            newg, conflicts = merge_import(cur, b.get("entries", []))
        except (ValueError, KeyError, TypeError) as e:
            raise AppError("VALIDATION_FAILED", {"field": str(e)[:80]}) from None
        v = ctx.db.replace_glossary([e.to_dict() for e in newg.entries], cur.version)
        if ctx.session and not ctx.session.closed:
            ctx.session.invalidate_glossary(ctx.glossary())
        return {"version": v, "conflicts_overwritten": conflicts[:100]}

    @app.get("/v1/settings")
    async def get_settings():
        return {"version": int(ctx.db.get_setting("app_settings_version", 1)), "value": ctx.settings()}

    @app.put("/v1/settings")
    async def put_settings(request: Request):
        b = await body_json(request)
        im = request.headers.get("if-match")
        cur_v = int(ctx.db.get_setting("app_settings_version", 1))
        expected = int(im) if im and im.isdigit() else b.get("version")
        if expected is not None and expected != cur_v:
            raise AppError("REVISION_CONFLICT", {"expected": expected, "actual": cur_v})
        patch = validate_patch(b.get("value", {}))
        stored = ctx.db.get_setting("app_settings") or {}
        before = merged(stored)
        for sec, vals in patch.items():
            stored.setdefault(sec, {}).update(vals)
        ctx.db.put_setting("app_settings", stored)
        ctx.db.put_setting("app_settings_version", cur_v + 1)
        after = merged(stored)
        await _apply_settings(before, after)
        return {"version": cur_v + 1, "value": after}

    @app.post("/v1/settings/reset")
    async def reset_settings(request: Request):
        b = await body_json(request)
        if b.get("confirm") is not True:
            raise AppError("VALIDATION_FAILED", {"field": "confirm"})
        scope = b.get("scope", "settings")
        before = ctx.settings()
        ctx.db.delete_setting("app_settings")
        cur_v = int(ctx.db.get_setting("app_settings_version", 1))
        ctx.db.put_setting("app_settings_version", cur_v + 1)
        removed = []
        if scope == "settings+glossary":
            ctx.db.replace_glossary([], None)
            removed.append("glossary")
        await _apply_settings(before, ctx.settings())
        # KHÔNG xóa model / override trừ khi chọn rõ (FR-033)
        return {"version": cur_v + 1, "value": ctx.settings(), "removed": removed}

    async def _apply_settings(before: dict[str, Any], after: dict[str, Any]) -> None:
        if before["storage"]["private_mode"] != after["storage"]["private_mode"]:
            ctx.db.set_private(after["storage"]["private_mode"])
            if after["storage"]["private_mode"]:
                ctx.cache.clear_ram()
        ctx.cache.limit = after["storage"]["cache_limit_bytes"]
        ctx.cache.ttl_s = after["storage"]["cache_ttl_days"] * 86400
        s = ctx.session
        if s and not s.closed:
            voice_changed = any(before["tts"][k] != after["tts"][k] for k in ("voice_id", "alternate_speakers", "voice_alt_id"))
            s.settings = ctx.session_settings()
            if voice_changed:
                s.invalidate_voice()
            if before["translation"]["topic"] != after["translation"]["topic"]:
                s.invalidate_glossary(ctx.glossary())
        if before["privacy"]["start_with_windows"] != after["privacy"]["start_with_windows"]:
            from ..companion import startup
            await asyncio.to_thread(startup.set_enabled, after["privacy"]["start_with_windows"])

    # ------------------------------------------------------------------ cache/history/export
    @app.post("/v1/cache/clear", status_code=202)
    async def cache_clear(request: Request):
        b = await body_json(request)
        if b.get("confirm") is not True:
            raise AppError("VALIDATION_FAILED", {"field": "confirm"})
        scope = b.get("scope")
        if scope == "video":
            vid = str(b.get("video_id", ""))
            if not VIDEO_ID_RE.match(vid):
                raise AppError("VALIDATION_FAILED", {"field": "video_id"})
            rels = ctx.db.delete_video(vid)
            ctx.cache.delete_relpaths(rels)
        elif scope == "all":
            rels = ctx.db.delete_all_content(keep_overrides=bool(b.get("keep_overrides", True)))
            ctx.cache.delete_relpaths(rels)
            ctx.cache.clear_ram()
        else:
            raise AppError("VALIDATION_FAILED", {"field": "scope"})
        return {"job_id": "clr-" + uuid.uuid4().hex[:8], "usage_bytes": ctx.cache.usage_bytes()}

    @app.get("/v1/cache")
    async def cache_info():
        return {"usage_bytes": ctx.cache.usage_bytes(), "limit_bytes": ctx.cache.limit, "disk_full": ctx.cache.disk_full,
                "private_mode": ctx.db.private}

    @app.get("/v1/history")
    async def history():
        return {"enabled": ctx.settings()["storage"]["history_opt_in"], "items": ctx.db.history()}

    @app.post("/v1/export/subtitles", status_code=202)
    async def export_subtitles(request: Request):
        b = await body_json(request)
        if b.get("ack_rights") is not True:
            raise AppError("VALIDATION_FAILED", {"field": "ack_rights"})
        fmt = b.get("format", "srt")
        kind = b.get("kind", "vi")
        if fmt not in ("srt", "vtt") or kind not in ("vi", "bilingual"):
            raise AppError("VALIDATION_FAILED", {"field": "format"})
        s = ctx.session
        if not s or s.session_id != b.get("session_id"):
            raise AppError("NOT_FOUND", {"reason": "session"})
        cues = []
        for u in s.units:
            if u.status != "ready" or not u.display:
                continue
            text = u.display if kind == "vi" else f"{u.unit.source_text}\n{u.display}"
            # Mốc = timeline nguồn (đã áp offset người dùng xác nhận), KHÔNG phải lịch audio sau auto-hold.
            cues.append((u.unit.start_ms, u.unit.end_ms, text))
        content = write_srt(cues) if fmt == "srt" else write_vtt(cues)
        name = f"{s.video_id}-{kind}-{time.strftime('%Y%m%d-%H%M%S')}.{fmt}"
        if not ctx.db.private:
            (ctx.paths.exports / name).write_text(content, encoding="utf-8")
        return {"job_id": "exp-" + uuid.uuid4().hex[:8], "file_name": name, "cue_count": len(cues), "content": content,
                "saved_locally": not ctx.db.private}

    # ------------------------------------------------------------------ diagnostics
    def _diag_bundle(include_payload: bool) -> dict[str, Any]:
        s = ctx.session
        d: dict[str, Any] = {"app_version": APP_VERSION, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "env": system.env_report(ctx.paths.home, ctx.rt.rts, ctx.rt.model_states()),
                             "private_mode": ctx.db.private}
        if s:
            snap = s.snapshot()
            d["session"] = {k: snap[k] for k in ("mode", "state", "reason", "timeline_epoch", "units", "blocked",
                                                 "buffer_media_ms", "lag_ms", "last_error")}
            m = s.metrics
            d["metrics"] = {k: (v[-50:] if isinstance(v, list) else v) for k, v in m.items()}
            if include_payload and not ctx.db.private:
                d["transcript_sample"] = [{"src": u.unit.source_text, "vi": u.display, "flags": u.flags}
                                          for u in s.units[:20]]
        return json.loads(redact(json.dumps(d, ensure_ascii=False)))

    @app.get("/v1/diagnostics/preview")
    async def diag_preview(include_payload: bool = False):
        return await asyncio.to_thread(_diag_bundle, include_payload)

    @app.post("/v1/diagnostics/export")
    async def diag_export(request: Request):
        b = await body_json(request)
        bundle = await asyncio.to_thread(_diag_bundle, bool(b.get("include_payload")))
        bundle["runtime"] = await ctx.rt.health()
        name = f"vietdub-diagnostic-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("diagnostic.json", json.dumps(bundle, ensure_ascii=False, indent=2))
        (ctx.paths.diagnostics / name).write_bytes(buf.getvalue())
        return {"file_name": name, "folder": "diagnostics", "bytes": len(buf.getvalue())}

    # ------------------------------------------------------------------ benchmark (FR-039)
    @app.post("/v1/benchmark", status_code=202)
    async def benchmark(request: Request):
        from .bench import run_benchmark
        b = await body_json(request)
        job_id = "bench-" + uuid.uuid4().hex[:8]
        ctx.jobs[job_id] = {"state": "running", "progress": 0}
        asyncio.create_task(run_benchmark(ctx, job_id, limit=int(b.get("limit", 20)), split=str(b.get("split", "dev")),
                                          with_tts=bool(b.get("with_tts", True))))
        return {"job_id": job_id}

    @app.get("/v1/jobs/{job_id}")
    async def job(job_id: str):
        j = ctx.jobs.get(job_id)
        if not j:
            raise AppError("NOT_FOUND", {"reason": "job"})
        return j

    # ------------------------------------------------------------------ websocket
    @app.websocket("/v1/events")
    async def events(ws: WebSocket):
        origin = ws.headers.get("origin")
        if not host_ok(ws.headers.get("host"), ctx.port) or not ctx.tokens.origin_allowed(origin) \
                or "token" in ws.query_params:
            await ws.close(code=4403)
            return
        await ws.accept()
        try:
            first = await asyncio.wait_for(ws.receive(), 3.0)
        except (asyncio.TimeoutError, WebSocketDisconnect):
            await ws.close(code=4401)
            return
        text = first.get("text")
        if not text or len(text) > 4096:
            await ws.close(code=4401)
            return
        try:
            msg = strict_loads(text)
            if msg.get("type") != "auth":
                raise AppError("AUTH_REQUIRED")
            if msg.get("protocol_version") != PROTOCOL_VERSION:
                raise AppError("PROTOCOL_MISMATCH")
            ctx.tokens.check(msg.get("token"), origin)
        except (AppError, ValueError) as e:
            code = e.code if isinstance(e, AppError) else "AUTH_REQUIRED"
            await ws.send_json({"protocol_version": PROTOCOL_VERSION, "event": "auth.error", "request_id": "auth",
                                "session_id": None, "timeline_epoch": 0, "seq": 0, "sent_monotonic_ms": 0,
                                "payload": {"code": code}})
            await ws.close(code=4401)
            return
        conn = Conn(ws, origin or "", role=str(msg.get("role", "audio")) if msg.get("role") in ("audio", "status") else "audio")
        ctx.hub.add(conn)
        await ctx.hub.send_event("auth.ok", {"server_version": APP_VERSION}, session_id=None, epoch=0, conn=conn)
        try:
            while True:
                m = await ws.receive()
                if m.get("type") == "websocket.disconnect":
                    break
                if m.get("bytes") is not None:
                    await _ws_binary(conn, m["bytes"])
                elif m.get("text") is not None:
                    await _ws_text(conn, m["text"])
        except WebSocketDisconnect:
            pass
        finally:
            ctx.hub.remove(conn)

    async def _ws_text(conn: Conn, text: str) -> None:
        if len(text) > 64 * 1024:
            return
        try:
            msg = strict_loads(text)
        except ValueError:
            return
        t = msg.get("type")
        s = ctx.session
        if t == "ping":
            await ctx.hub.send_event("pong", {"t": msg.get("t")}, session_id=conn.session_id, epoch=s.epoch if s else 0,
                                     conn=conn)
        elif t == "subscribe":
            sid = msg.get("session_id")
            if s and s.session_id == sid and not s.closed:
                conn.session_id = sid
                await ctx.hub.send_event("session.state", s.snapshot(), session_id=sid, epoch=s.epoch, conn=conn)
                for us in s.units:
                    us.delivered = None if us.delivered and us.delivered[0] == s.epoch else us.delivered
                s.poke()
            else:
                e = AppError("NOT_FOUND", {"reason": "session"})
                await ctx.hub.send_event("error", e.to_dict("sub"), session_id=None, epoch=0, conn=conn)
        elif t == "clock" and s and conn.session_id == s.session_id:
            try:
                clock = msg.get("clock") or {}
                validate_clock(clock, session_id=s.session_id, epoch=s.epoch, video_id=s.video_id)
                await s.on_clock(clock)
            except AppError as e:
                await ctx.hub.send_event("error", e.to_dict("clock", s.session_id), session_id=s.session_id,
                                         epoch=s.epoch, conn=conn)
        elif t == "audio.stopped" and s:
            s.stop_acks = (s.stop_acks + [{"epoch": msg.get("epoch"), "reason": msg.get("reason"),
                                           "t": time.monotonic()}])[-50:]
        elif t == "queue.status" and s:
            q = msg.get("queued_ms")
            if isinstance(q, (int, float)) and 0 <= q < 3_600_000:
                s.consumer_queue_ms = int(q)
        elif t == "control" and s and conn.session_id == s.session_id:
            try:
                await s.control(str(msg.get("op")), msg)
            except AppError as e:
                await ctx.hub.send_event("error", e.to_dict("ctl", s.session_id), session_id=s.session_id,
                                         epoch=s.epoch, conn=conn)

    async def _ws_binary(conn: Conn, data: bytes) -> None:
        s = ctx.session
        try:
            h, pcm = unpack_frame(data)
        except ValueError:
            await ctx.hub.send_event("warning", {"code": "BAD_FRAME"}, session_id=conn.session_id, epoch=0, conn=conn)
            return
        if h["kind"] != "asr_pcm" or not s or h["session_id"] != s.session_id or conn.session_id != s.session_id:
            return
        if h["timeline_epoch"] != s.epoch or not s.asr_active:
            s.metrics["stale_dropped"] += 1
            return
        await ctx.rt.asr_feed(h, pcm)

    return app


_exit_event: asyncio.Event | None = None


def _request_exit() -> None:
    if _exit_event:
        _exit_event.set()


def set_exit_event(ev: asyncio.Event) -> None:
    global _exit_event
    _exit_event = ev


# Tham chiếu để linter không báo import không dùng (validate dùng trong contracts API tương lai)
_ = (validate, Database, AudioCache)
