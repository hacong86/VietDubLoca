"""First-run setup: exact download consent, resumable model manager, then load both engines.

Owned by the broker, so closing the panel does not interrupt preparation. No private
paths, tokens or raw exception messages are exposed to the browser.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ..errors import AppError

BASE_MODELS = ("qwen35_4b_q5", "vieneu_v3_turbo", "moss_audio_tokenizer_nano")


class FirstRunSetup:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.state = "idle"
        self.current: str | None = None
        self.error: str | None = None
        self.task: asyncio.Task | None = None
        self.pause_requested = False
        self.include_asr = False

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    def snapshot(self) -> dict[str, Any]:
        rt = self.ctx.rt
        ready = rt.translation_ready() and rt.tts_ready()
        rows = [rt.models.status(mid, verified_cache=rt.verified) for mid in (*BASE_MODELS, "whisper_small_en")]
        return {"state": self.state, "busy": self.busy, "ready": ready, "current_model": self.current,
                "error": self.error, "include_asr": self.include_asr, "models": rows,
                "asr_runtime_available": bool(rt.rts.asr_python)}

    def start(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.busy:
            return self.snapshot()  # repeated click attaches to the same operation
        if self.ctx.session and not self.ctx.session.closed:
            raise AppError("SESSION_CONFLICT")
        include_asr = body.get("include_asr") is True
        if include_asr and not self.ctx.rt.rts.asr_python:
            raise AppError("MODEL_NOT_READY", {"reason": "asr_runtime_missing"})
        ids = (*BASE_MODELS, "whisper_small_en") if include_asr else BASE_MODELS
        expected = {mid: self.ctx.rt.models.catalog[mid]["size_bytes"] for mid in ids}
        if body.get("consent") is not True or body.get("accepted_sizes") != expected:
            raise AppError("CONSENT_REQUIRED")
        self.include_asr = include_asr
        self.pause_requested = False
        self.error = None
        self.state = "checking"
        self.task = asyncio.create_task(self._run(ids), name="first-run-setup")
        return self.snapshot()

    async def _run(self, ids: tuple[str, ...]) -> None:
        rt = self.ctx.rt
        try:
            if self.ctx.startup_task:
                await asyncio.shield(self.ctx.startup_task)
            if not rt.rts.tts_python or not rt.rts.llama_server:
                raise AppError("MODEL_NOT_READY", {"reason": "runtime_missing"})
            for mid in ids:
                if self.pause_requested:
                    self.state = "paused"
                    return
                self.current = mid
                self.state = "checking"
                valid = (await rt.verify_models([mid]))[mid]
                if not valid:
                    self.state = "downloading"
                    job = rt.models.start_download(mid, consent=True, accepted_size_bytes=rt.models.catalog[mid]["size_bytes"])
                    await job.task
                    if self.pause_requested or job.state == "paused":
                        self.state = "paused"
                        return
                    if job.state != "done":
                        raise AppError(job.error or "MODEL_NOT_READY")
                    # _run already hashed every file before marking the download done.
                    rt.verified[mid] = True
            if self.pause_requested:
                self.state = "paused"
                return
            self.current = None
            self.state = "activating"
            if not rt.translation_ready():
                await rt.activate_translation(BASE_MODELS[0])
            if not rt.tts_ready():
                await rt.start_tts(self.ctx.settings()["tts"]["device"])
            if not (rt.translation_ready() and rt.tts_ready()):
                raise AppError("MODEL_NOT_READY")
            self.state = "ready"
        except asyncio.CancelledError:
            self.state = "paused"
            raise
        except AppError as e:
            self.error, self.state = e.code, "failed"
        except Exception:
            self.error, self.state = "INTERNAL", "failed"

    def pause(self) -> dict[str, Any]:
        self.pause_requested = True
        for job in self.ctx.rt.models.jobs.values():
            if job.model_id == self.current:
                self.ctx.rt.models.pause(job.job_id)
        return self.snapshot()

    async def close(self) -> None:
        if self.busy:
            self.pause()
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
