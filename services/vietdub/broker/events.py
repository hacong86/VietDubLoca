"""WebSocket hub (docs/08 §4): envelope có seq/epoch; một socket audio (offscreen) cho mỗi phiên."""
from __future__ import annotations

import asyncio
import itertools
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from .. import PROTOCOL_VERSION

_T0 = time.monotonic()


def monotonic_ms() -> float:
    return round((time.monotonic() - _T0) * 1000, 3)


@dataclass
class Conn:
    ws: WebSocket
    origin: str
    role: str = "audio"                 # audio (offscreen) | status
    session_id: str | None = None
    seq: itertools.count = field(default_factory=lambda: itertools.count(1))
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    alive: bool = True


class Hub:
    def __init__(self) -> None:
        self.conns: list[Conn] = []

    def add(self, c: Conn) -> None:
        self.conns.append(c)

    def remove(self, c: Conn) -> None:
        c.alive = False
        if c in self.conns:
            self.conns.remove(c)

    def envelope(self, c: Conn, event: str, payload: dict[str, Any], *, session_id: str | None, epoch: int,
                 request_id: str | None = None) -> dict[str, Any]:
        return {"protocol_version": PROTOCOL_VERSION, "event": event, "request_id": request_id or uuid.uuid4().hex[:16],
                "session_id": session_id, "timeline_epoch": epoch, "seq": next(c.seq),
                "sent_monotonic_ms": monotonic_ms(), "payload": payload}

    async def send_event(self, event: str, payload: dict[str, Any], *, session_id: str | None, epoch: int,
                         request_id: str | None = None, conn: Conn | None = None) -> None:
        targets = [conn] if conn else [c for c in self.conns if c.session_id in (session_id, None) or session_id is None]
        for c in targets:
            if not c.alive:
                continue
            try:
                async with c.send_lock:
                    await c.ws.send_json(self.envelope(c, event, payload, session_id=session_id, epoch=epoch,
                                                       request_id=request_id))
            except Exception:
                self.remove(c)

    async def send_binary(self, session_id: str, data: bytes) -> bool:
        sent = False
        for c in [c for c in self.conns if c.session_id == session_id and c.role == "audio"]:
            try:
                async with c.send_lock:
                    await c.ws.send_bytes(data)
                sent = True
            except Exception:
                self.remove(c)
        return sent

    def has_audio_consumer(self, session_id: str) -> bool:
        return any(c.session_id == session_id and c.role == "audio" and c.alive for c in self.conns)
