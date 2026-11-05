"""Quản lý tiến trình worker có framed stdio IPC, timeout, restart giới hạn (FR-038, docs/07 §8)."""
from __future__ import annotations

import asyncio
import itertools
import logging
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import AppError
from ..workers.ipc import MAX_HEADER, MAX_PAYLOAD, encode
from . import jobobject

log = logging.getLogger("vietdub.worker")

RESTART_COOLDOWN_S = 5.0
MAX_CONSECUTIVE_FAILURES = 2


@dataclass
class _Pending:
    fut: asyncio.Future
    pcm: list[tuple[dict[str, Any], bytes]] = field(default_factory=list)
    stream_q: asyncio.Queue | None = None
    want_pcm: int = 0


class WorkerProcess:
    """Một worker (TTS hoặc ASR). Lệnh được serialize bởi worker; broker có thể gửi cancel bất kỳ lúc."""

    def __init__(self, name: str, python: Path, script: Path, env: dict[str, str], cwd: Path) -> None:
        self.name = name
        self.python = python
        self.script = script
        self.env = env
        self.cwd = cwd
        self.proc: asyncio.subprocess.Process | None = None
        self._ids = itertools.count(1)
        self._pending: dict[str, _Pending] = {}
        self._reader: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._wlock = asyncio.Lock()
        self.failures = 0
        self.last_restart = 0.0
        self.state = "stopped"          # stopped | starting | ready | crashed | failed
        self.info: dict[str, Any] = {}
        self.events: asyncio.Queue = asyncio.Queue(maxsize=1000)   # push messages (ASR results)
        self.stderr_tail: list[str] = []

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self) -> None:
        if self.alive:
            return
        self.state = "starting"
        self.proc = await asyncio.create_subprocess_exec(
            str(self.python), "-B", str(self.script), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=self.env, cwd=str(self.cwd),
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            limit=MAX_PAYLOAD + MAX_HEADER + 16)
        jobobject.assign(self.proc.pid)
        hello = asyncio.get_running_loop().create_future()
        self._pending["__hello__"] = _Pending(hello)
        self._reader = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())
        try:
            await asyncio.wait_for(hello, 60)
        except asyncio.TimeoutError:
            await self.kill()
            raise AppError("WORKER_CRASHED", {"reason": "hello_timeout"})
        self.state = "ready"

    async def _stderr_loop(self) -> None:
        assert self.proc and self.proc.stderr
        while True:
            line = await self.proc.stderr.readline()
            if not line:
                return
            s = line.decode("utf-8", "replace").rstrip()
            self.stderr_tail = (self.stderr_tail + [s])[-50:]

    async def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        out = self.proc.stdout
        try:
            while True:
                n = struct.unpack("<I", await out.readexactly(4))[0]
                if not 1 <= n <= MAX_HEADER:
                    raise ValueError("bad header")
                import json
                h = json.loads((await out.readexactly(n)).decode("utf-8"))
                pb = int(h.get("payload_bytes", 0))
                if not 0 <= pb <= MAX_PAYLOAD:
                    raise ValueError("bad payload")
                payload = await out.readexactly(pb) if pb else b""
                self._dispatch(h, payload)
        except (asyncio.IncompleteReadError, ConnectionError, ValueError) as e:
            log.warning("%s reader stopped: %s", self.name, type(e).__name__)
        finally:
            self.state = "crashed" if self.state != "stopped" else "stopped"
            for p in list(self._pending.values()):
                if not p.fut.done():
                    p.fut.set_exception(AppError("WORKER_CRASHED", {"reason": "exited"}))
                if p.stream_q:
                    p.stream_q.put_nowait(None)
            self._pending.clear()

    def _dispatch(self, h: dict[str, Any], payload: bytes) -> None:
        op = h.get("op")
        if op == "hello":
            p = self._pending.pop("__hello__", None)
            self.info["pid"] = h.get("pid")
            if p and not p.fut.done():
                p.fut.set_result(h)
            return
        jid = h.get("job_id")
        p = self._pending.get(jid) if jid else None
        if op == "pcm":
            if p is None:
                return                          # job đã bị hủy/đã xong: bỏ
            if p.stream_q is not None:
                p.stream_q.put_nowait((h, payload))
                if h.get("is_last"):
                    p.stream_q.put_nowait(None)
            else:
                p.pcm.append((h, payload))
                if len(p.pcm) >= p.want_pcm and p.fut.done():
                    self._pending.pop(jid, None)
            self._maybe_finish(jid)
            return
        if jid is None or p is None:
            if op in ("asr.draft", "asr.commit", "asr.status"):
                if not self.events.full():
                    self.events.put_nowait((h, payload))
            return
        if not p.fut.done():
            p.fut.set_result(h)
        self._maybe_finish(jid)

    def _maybe_finish(self, jid: str) -> None:
        p = self._pending.get(jid)
        if not p or not p.fut.done():
            return
        h = p.fut.result()
        if not h.get("ok") or p.stream_q is not None or len(p.pcm) >= p.want_pcm:
            self._pending.pop(jid, None)

    async def request(self, op: str, timeout: float = 60.0, want_pcm: int = 0,
                      payload: bytes = b"", **kw: Any) -> tuple[dict[str, Any], list[bytes]]:
        if not self.alive:
            raise AppError("WORKER_CRASHED", {"reason": "not_running"})
        jid = kw.pop("job_id", None) or f"{self.name}-{next(self._ids)}"
        fut = asyncio.get_running_loop().create_future()
        pend = _Pending(fut, want_pcm=want_pcm)
        self._pending[jid] = pend
        await self._send({"op": op, "job_id": jid, **kw}, payload)
        try:
            h = await asyncio.wait_for(asyncio.shield(fut), timeout)
            if h.get("ok") and want_pcm:
                t0 = time.monotonic()
                while len(pend.pcm) < want_pcm:
                    if time.monotonic() - t0 > timeout or not self.alive:
                        raise AppError("WORKER_CRASHED", {"reason": "pcm_timeout"})
                    await asyncio.sleep(0.005)
            return h, [p for _, p in sorted(pend.pcm, key=lambda x: x[0].get("seq", 0))]
        except asyncio.TimeoutError:
            self._pending.pop(jid, None)
            raise AppError("WORKER_CRASHED", {"reason": f"{op}_timeout"}) from None
        finally:
            if fut.done():
                self._pending.pop(jid, None)

    async def stream(self, op: str, **kw: Any):
        """Async generator các frame pcm (header, bytes) cho infer_stream."""
        jid = kw.pop("job_id", None) or f"{self.name}-{next(self._ids)}"
        fut = asyncio.get_running_loop().create_future()
        q: asyncio.Queue = asyncio.Queue()
        self._pending[jid] = _Pending(fut, stream_q=q)
        await self._send({"op": op, "job_id": jid, **kw})
        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                yield item
            if fut.done() and not fut.result().get("ok", True):
                raise AppError(fut.result().get("error", "WORKER_CRASHED") if fut.result().get("error") in
                               ("GPU_OOM", "VOICE_NOT_FOUND", "TTS_INVALID_AUDIO", "MODEL_NOT_READY") else "WORKER_CRASHED")
        finally:
            self._pending.pop(jid, None)

    async def push(self, op: str, payload: bytes = b"", **kw: Any) -> None:
        """Gửi không chờ trả lời (ASR feed)."""
        await self._send({"op": op, **kw}, payload)

    async def cancel(self, job_ids: list[str]) -> None:
        if self.alive and job_ids:
            try:
                await self._send({"op": "cancel", "job_id": f"c-{next(self._ids)}", "job_ids": job_ids})
            except Exception:
                pass

    async def _send(self, header: dict[str, Any], payload: bytes = b"") -> None:
        assert self.proc and self.proc.stdin
        async with self._wlock:
            self.proc.stdin.write(encode(header, payload))
            await self.proc.stdin.drain()

    async def stop(self, timeout: float = 5.0) -> None:
        self.state = "stopped"
        if not self.alive:
            return
        try:
            await asyncio.wait_for(self.request("shutdown", timeout=timeout), timeout)
        except Exception:
            pass
        await self.kill()

    async def kill(self) -> None:
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.kill()
                await asyncio.wait_for(self.proc.wait(), 5)
            except Exception:
                pass
        for t in (self._reader, self._stderr_task):
            if t:
                t.cancel()

    def can_restart(self) -> bool:
        return self.failures < MAX_CONSECUTIVE_FAILURES and time.monotonic() - self.last_restart >= RESTART_COOLDOWN_S

    async def restart(self) -> None:
        if not self.can_restart():
            self.state = "failed"
            raise AppError("WORKER_CRASHED", {"reason": "restart_limit"})
        self.failures += 1
        self.last_restart = time.monotonic()
        await self.kill()
        await self.start()
