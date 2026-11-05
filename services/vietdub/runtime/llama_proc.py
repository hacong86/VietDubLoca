"""Quản lý llama-server (docs/16 §Ví dụ llama-server; FR-017). Chỉ 127.0.0.1, api-key-file, một model resident."""
from __future__ import annotations

import asyncio
import logging
import secrets
import subprocess
import time
from pathlib import Path

import httpx

from ..errors import AppError
from ..paths import AppPaths
from . import jobobject

log = logging.getLogger("vietdub.llama")


class LlamaServer:
    def __init__(self, paths: AppPaths, binary: Path | None, port: int = 8766) -> None:
        self.paths = paths
        self.binary = binary
        self.port = port
        self.proc: subprocess.Popen | None = None
        self.model_id: str | None = None
        self.alias: str | None = None
        self.state = "stopped"            # stopped | loading | ready | failed
        self.load_ms: float | None = None
        self.ctx = 4096
        self.ngl = 99
        self._log_fh = None

    def api_key(self) -> str:
        kf = self.paths.llama_key
        if not kf.exists():
            kf.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        return kf.read_text(encoding="utf-8").strip()

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    async def start(self, model_id: str, model_path: Path, *, ctx: int = 4096, ngl: int = 99) -> None:
        if not self.binary or not self.binary.is_file():
            raise AppError("MODEL_NOT_READY", {"reason": "llama_binary_missing"})
        if not model_path.is_file() or model_path.suffix == ".part":
            raise AppError("MODEL_NOT_READY", {"model_id": model_id})
        await self.stop()                     # một model dịch resident
        self.api_key()
        self.state = "loading"
        self.model_id, self.alias, self.ctx, self.ngl = model_id, model_id, ctx, ngl
        args = [str(self.binary), "--model", str(model_path), "--alias", model_id, "--host", "127.0.0.1",
                "--port", str(self.port), "--ctx-size", str(ctx), "--parallel", "1", "--n-gpu-layers", str(ngl),
                "--jinja", "--reasoning", "off", "--api-key-file", str(self.paths.llama_key), "--no-webui",
                "--offline", "--seed", "42"]
        self._log_fh = open(self.paths.logs / "llama-server.log", "ab")
        env = {"CUDA_CACHE_PATH": str(self.paths.cache / "cuda"), "TMP": str(self.paths.tmp), "TEMP": str(self.paths.tmp)}
        import os
        full_env = dict(os.environ, **env)
        t0 = time.perf_counter()
        self.proc = subprocess.Popen(args, stdout=self._log_fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     cwd=str(self.binary.parent), env=full_env, creationflags=0x08000000)
        jobobject.assign(self.proc.pid)
        async with httpx.AsyncClient(trust_env=False) as cli:
            for _ in range(600):
                if not self.alive:
                    self.state = "failed"
                    raise AppError("MODEL_NOT_READY", {"reason": "llama_exited"})
                try:
                    r = await cli.get(f"http://127.0.0.1:{self.port}/health", timeout=2)
                    if r.status_code == 200:
                        self.state = "ready"
                        self.load_ms = (time.perf_counter() - t0) * 1000
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.25)
        self.state = "failed"
        await self.stop()
        raise AppError("MODEL_NOT_READY", {"reason": "llama_timeout"})

    async def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(asyncio.to_thread(self.proc.wait), 10)
            except asyncio.TimeoutError:
                self.proc.kill()
        self.proc = None
        self.state = "stopped"
        self.model_id = None
        if self._log_fh:
            self._log_fh.close()
            self._log_fh = None

    def log_tail_has_oom(self) -> bool:
        try:
            tail = (self.paths.logs / "llama-server.log").read_bytes()[-8000:].decode("utf-8", "replace").lower()
        except OSError:
            return False
        return "out of memory" in tail or "cudamalloc failed" in tail
