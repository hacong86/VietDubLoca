"""Runtime của broker: llama-server + TTS worker + ASR worker + model manager (FR-017, FR-018, FR-038; docs/12)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Callable

from ..errors import AppError
from ..hashing import content_key
from ..models.manager import ModelManager
from ..paths import SERVICES_DIR, AppPaths, worker_env
from ..runtime import locate
from ..runtime.llama_proc import LlamaServer
from ..runtime.worker_proc import WorkerProcess
from ..translation.llm import LlamaClient, LlmResult
from ..translation.service import ModelFingerprint

log = logging.getLogger("vietdub.runtime")

PROFILES = json.loads((SERVICES_DIR.parent / "config" / "generation-profiles.json").read_text(encoding="utf-8"))["profiles"]


class BrokerRuntime:
    def __init__(self, paths: AppPaths, *, llama_port: int = 8766,
                 emit: Callable[[str, dict[str, Any]], Any] | None = None) -> None:
        self.paths = paths
        self.rts = locate.load(paths)
        self.models = ModelManager(paths, on_progress=lambda e: self._emit("model.progress", e))
        self.llama = LlamaServer(paths, self.rts.llama_server, llama_port)
        self.llm: LlamaClient | None = None
        self.tts: WorkerProcess | None = None
        self.asr: WorkerProcess | None = None
        self.tts_info: dict[str, Any] = {}
        self.asr_info: dict[str, Any] = {}
        self.voices: list[dict[str, Any]] = []
        self.voice_aliases: dict[str, str] = {}
        self.tts_state = "stopped"          # stopped | loading | ready | failed
        self.asr_state = "stopped"
        self.translation_state = "stopped"
        self.translation_error: str | None = None
        self.tts_error: str | None = None
        self.tts_batch = 2
        self.tts_device = "auto"
        self.consec_oom = 0
        self.verified: dict[str, bool] = {}
        self._emit_cb = emit
        self._tts_lock = asyncio.Lock()
        self._activation: asyncio.Task | None = None
        self.asr_consumer: Callable[[dict[str, Any]], Any] | None = None
        self._asr_pump: asyncio.Task | None = None
        self.timings: dict[str, Any] = {}

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self._emit_cb:
            try:
                r = self._emit_cb(event, payload)
                if asyncio.iscoroutine(r):
                    asyncio.create_task(r)
            except Exception:
                pass

    # ------------------------------------------------------------ verify
    async def verify_models(self, ids: list[str] | None = None) -> dict[str, bool]:
        for mid in ids or list(self.models.catalog):
            self.verified[mid] = await asyncio.to_thread(self.models.verify_full, mid)
        return self.verified

    def model_states(self) -> dict[str, str]:
        return {mid: self.models.status(mid, verified_cache=self.verified)["state"] for mid in self.models.catalog}

    # ------------------------------------------------------------ translation
    async def activate_translation(self, model_id: str) -> None:
        m = self.models.catalog.get(model_id)
        if not m or m["kind"] != "translation":
            raise AppError("NOT_FOUND", {"model_id": model_id})
        if not self.verified.get(model_id):
            ok = await asyncio.to_thread(self.models.verify_full, model_id)
            self.verified[model_id] = ok
            if not ok:
                raise AppError("MODEL_CHECKSUM_MISMATCH" if self.models.translation_file(model_id).exists()
                               else "MODEL_NOT_READY", {"model_id": model_id})
        self.translation_state = "loading"
        self._emit("model.progress", {"model_id": model_id, "state": "loading"})
        if self.llm:
            await self.llm.close()
            self.llm = None
        try:
            await self.llama.start(model_id, self.models.translation_file(model_id))
        except AppError as e:
            self.translation_state, self.translation_error = "failed", e.code
            self._emit("model.progress", {"model_id": model_id, "state": "failed", "error": e.code})
            raise
        self.llm = LlamaClient(self.llama.port, self.llama.api_key())
        self.translation_state, self.translation_error = "ready", None
        self.timings["llama_load_ms"] = round(self.llama.load_ms or 0)
        self._emit("model.progress", {"model_id": model_id, "state": "ready", "load_ms": self.timings["llama_load_ms"]})

    def translation_ready(self) -> bool:
        return self.translation_state == "ready" and self.llama.alive and self.llm is not None

    def fingerprint(self) -> ModelFingerprint | None:
        mid = self.llama.model_id
        if not mid:
            return None
        m = self.models.catalog[mid]
        prof = PROFILES[m.get("profile", "qwen_non_thinking")]
        sampling = {k: prof[k] for k in ("temperature", "top_p", "top_k", "seed", "chat_template_kwargs") if k in prof}
        return ModelFingerprint(mid, mid, m["files"][0]["sha256"], self.rts.llama_build or "unknown", sampling)

    async def chat(self, payload: dict[str, Any]) -> LlmResult:
        if not self.llm:
            raise AppError("MODEL_NOT_READY")
        try:
            return await self.llm.chat(payload)
        except AppError:
            if not self.llama.alive:
                self.translation_state = "failed"
                self.translation_error = "GPU_OOM" if self.llama.log_tail_has_oom() else "WORKER_CRASHED"
            raise

    # ------------------------------------------------------------ TTS
    async def start_tts(self, device: str = "auto") -> None:
        if not self.rts.tts_python:
            raise AppError("MODEL_NOT_READY", {"reason": "tts_runtime_missing"})
        for dep in ("vieneu_v3_turbo", "moss_audio_tokenizer_nano"):
            if not self.verified.get(dep):
                self.verified[dep] = await asyncio.to_thread(self.models.verify_full, dep)
                if not self.verified[dep]:
                    raise AppError("MODEL_NOT_READY", {"model_id": dep})
        self.tts_state = "loading"
        self.tts_device = device
        self._emit("model.progress", {"model_id": "vieneu_v3_turbo", "state": "loading"})
        if self.tts is None:
            self.tts = WorkerProcess("tts", self.rts.tts_python, SERVICES_DIR / "vietdub/workers/tts_worker.py",
                                     worker_env(self.paths), self.paths.home)
        try:
            await self.tts.start()
            h, _ = await self.tts.request("load", timeout=600, device=device, max_batch_size=self.tts_batch,
                                          max_streams=1, warmup=True)
            if not h.get("ok"):
                raise AppError(h.get("error") if h.get("error") in ("GPU_OOM", "MODEL_NOT_READY") else "WORKER_CRASHED")
            self.tts_info = h
            v, _ = await self.tts.request("list_voices", timeout=30)
            self.voices = v.get("voices", [])
            self.voice_aliases = v.get("aliases", {})
        except AppError as e:
            self.tts_state, self.tts_error = "failed", e.code
            self._emit("model.progress", {"model_id": "vieneu_v3_turbo", "state": "failed", "error": e.code})
            raise
        self.tts_state, self.tts_error = "ready", None
        self.timings["tts_load_ms"], self.timings["tts_warmup_ms"] = h.get("load_ms"), h.get("warmup_ms")
        self._emit("model.progress", {"model_id": "vieneu_v3_turbo", "state": "ready", "backend": h.get("backend")})

    def tts_ready(self) -> bool:
        return self.tts_state == "ready" and self.tts is not None and self.tts.alive

    def resolve_voice(self, name: str) -> str | None:
        ids = {v["voice_id"] for v in self.voices}
        if name in ids:
            return name
        tgt = self.voice_aliases.get(name)
        return tgt if tgt in ids else None

    def voice_fingerprint(self, voice: str) -> str:
        return content_key({"voice": self.resolve_voice(voice) or voice, "rev": self.tts_info.get("model_revision"),
                            "backend": self.tts_info.get("backend")})

    def tts_versions(self) -> tuple[str, str]:
        return str(self.tts_info.get("sdk_version")), str(self.tts_info.get("model_revision"))

    async def synth(self, text: str, voice: str, *, watermark: bool = True) -> tuple[bytes, dict[str, Any]]:
        if not self.tts_ready():
            raise AppError("MODEL_NOT_READY", {"reason": "tts"})
        vid = self.resolve_voice(voice)
        if not vid:
            raise AppError("VOICE_NOT_FOUND", {"voice_id": voice[:60]})
        async with self._tts_lock:
            try:
                h, pcms = await self.tts.request("infer", timeout=120, want_pcm=1, text=text, voice=vid,  # type: ignore[union-attr]
                                                 batch_size=1, watermark=watermark)
            except AppError:
                await self._tts_crashed()
                raise
        if not h.get("ok"):
            code = h.get("error", "WORKER_CRASHED")
            raise AppError(code if code in ("GPU_OOM", "VOICE_NOT_FOUND", "TTS_INVALID_AUDIO", "MODEL_NOT_READY")
                           else "WORKER_CRASHED")
        self.consec_oom = 0
        pcm = pcms[0]
        if h.get("sample_rate") != 48000 or len(pcm) != h.get("samples", -1) * 2:
            raise AppError("TTS_INVALID_AUDIO", {"reason": "format"})
        return pcm, h

    async def synth_stream(self, text: str, voice: str) -> AsyncIterator[tuple[dict[str, Any], bytes]]:
        vid = self.resolve_voice(voice)
        if not vid or not self.tts_ready():
            raise AppError("VOICE_NOT_FOUND" if not vid else "MODEL_NOT_READY")
        async with self._tts_lock:
            async for item in self.tts.stream("infer_stream", text=text, voice=vid):  # type: ignore[union-attr]
                yield item

    async def _tts_crashed(self) -> None:
        if self.tts and not self.tts.alive:
            self.tts_state = "failed"
            self.tts_error = "WORKER_CRASHED"
            if self.tts.can_restart():
                asyncio.create_task(self._restart_tts())

    async def _restart_tts(self) -> None:
        try:
            assert self.tts
            await self.tts.restart()
            await self.start_tts(self.tts_device)
        except AppError:
            self.tts_state = "failed"

    def on_tts_failure(self, code: str) -> str:
        """OOM ladder (docs/12): giảm batch → dừng prefetch; 2 OOM liên tiếp → dừng an toàn, báo người dùng."""
        if code == "GPU_OOM":
            self.consec_oom += 1
            self.tts_batch = 1
            if self.consec_oom >= 2:
                self.tts_state = "failed"
                self.tts_error = "GPU_OOM"
                return "stop"
            return "retry"
        if code == "WORKER_CRASHED":
            return "retry" if (self.tts and self.tts.can_restart()) else "stop"
        return "skip"

    async def tts_cancel_all(self) -> None:
        if self.tts:
            await self.tts.cancel(list(self.tts._pending.keys()))

    # ------------------------------------------------------------ ASR
    async def start_asr(self) -> None:
        if not self.rts.asr_python:
            raise AppError("MODEL_NOT_READY", {"reason": "asr_runtime_missing"})
        if not self.verified.get("whisper_small_en"):
            self.verified["whisper_small_en"] = await asyncio.to_thread(self.models.verify_full, "whisper_small_en")
            if not self.verified["whisper_small_en"]:
                raise AppError("MODEL_NOT_READY", {"model_id": "whisper_small_en"})
        if self.asr is None:
            self.asr = WorkerProcess("asr", self.rts.asr_python, SERVICES_DIR / "vietdub/workers/asr_worker.py",
                                     worker_env(self.paths), self.paths.home)
        if self.asr_state == "ready" and self.asr.alive:
            return
        self.asr_state = "loading"
        await self.asr.start()
        h, _ = await self.asr.request("load", timeout=180, model_dir=str(self.paths.asr_models / "whisper_small_en"),
                                      device="cpu", compute_type="int8", cpu_threads=6)
        if not h.get("ok"):
            self.asr_state = "failed"
            raise AppError("WORKER_CRASHED", {"reason": "asr_load"})
        self.asr_info = h
        self.asr_state = "ready"
        self._asr_pump = asyncio.create_task(self._pump_asr())

    async def _pump_asr(self) -> None:
        assert self.asr
        while self.asr.alive:
            ev, _ = await self.asr.events.get()
            if self.asr_consumer:
                try:
                    r = self.asr_consumer(ev)
                    if asyncio.iscoroutine(r):
                        await r
                except Exception:
                    log.exception("asr consumer")

    async def asr_reset(self, session_id: str, epoch: int) -> None:
        if self.asr and self.asr.alive:
            await self.asr.request("reset", timeout=10, session_id=session_id, epoch=epoch)

    async def asr_feed(self, header: dict[str, Any], pcm: bytes) -> None:
        if self.asr and self.asr.alive and self.asr_state == "ready":
            await self.asr.push("feed", pcm, seq=header["seq"], epoch=header["timeline_epoch"],
                                session_id=header["session_id"], source_media_ms=header["source_media_ms"],
                                capture_monotonic_ms=header["capture_monotonic_ms"])

    async def asr_flush(self, epoch: int) -> None:
        if self.asr and self.asr.alive:
            await self.asr.request("flush", timeout=30, epoch=epoch)

    async def stop_asr(self) -> None:
        if self.asr:
            await self.asr.stop()
        self.asr_state = "stopped"
        if self._asr_pump:
            self._asr_pump.cancel()

    # ------------------------------------------------------------ status/shutdown
    async def health(self) -> dict[str, Any]:
        tts_h: dict[str, Any] = {}
        if self.tts_ready():
            try:
                tts_h, _ = await self.tts.request("health", timeout=5)  # type: ignore[union-attr]
            except AppError:
                tts_h = {"ok": False}
        return {"translation": {"state": self.translation_state, "model_id": self.llama.model_id,
                                "error": self.translation_error, "ctx": self.llama.ctx,
                                "runtime_build": self.rts.llama_build, "load_ms": self.timings.get("llama_load_ms")},
                "tts": {"state": self.tts_state, "error": self.tts_error, "backend": self.tts_info.get("backend"),
                        "sdk_version": self.tts_info.get("sdk_version"), "model_revision": self.tts_info.get("model_revision"),
                        "voices": len(self.voices), "batch": self.tts_batch, "consec_oom": self.consec_oom,
                        "vram_reserved_mb": tts_h.get("vram_reserved_mb"),
                        "load_ms": self.timings.get("tts_load_ms"), "warmup_ms": self.timings.get("tts_warmup_ms")},
                "asr": {"state": self.asr_state, "device": self.asr_info.get("device"),
                        "compute_type": self.asr_info.get("compute_type")}}

    async def shutdown(self) -> None:
        for w in (self.tts, self.asr):
            if w:
                await w.stop()
        if self.llm:
            await self.llm.close()
        await self.llama.stop()
        self.tts_state = self.asr_state = self.translation_state = "stopped"
