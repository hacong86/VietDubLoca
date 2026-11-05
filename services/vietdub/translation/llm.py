"""Client llama-server (OpenAI-compatible) chỉ loopback, không proxy/redirect (docs/08, S14)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..errors import AppError


@dataclass
class LlmResult:
    content: Any
    finish_reason: str | None
    reasoning_present: bool
    usage: dict[str, Any] | None
    latency_ms: float


class LlamaClient:
    def __init__(self, port: int, api_key: str, timeout_s: float = 60.0) -> None:
        self._base = f"http://127.0.0.1:{port}"
        self._key = api_key
        self._client = httpx.AsyncClient(timeout=timeout_s, follow_redirects=False, trust_env=False)

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> bool:
        try:
            r = await self._client.get(self._base + "/health", timeout=3)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def chat(self, payload: dict[str, Any]) -> LlmResult:
        t0 = time.perf_counter()
        try:
            r = await self._client.post(self._base + "/v1/chat/completions", json=payload,
                                        headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as e:
            raise AppError("MODEL_NOT_READY", {"reason": type(e).__name__}) from None
        if r.status_code == 503:
            raise AppError("MODEL_NOT_READY", {"reason": "loading"})
        if r.status_code != 200:
            # Không log body: có thể chứa payload người dùng.
            raise AppError("TRANSLATION_INVALID", {"reason": f"http_{r.status_code}"})
        d = r.json()
        ch = (d.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        return LlmResult(msg.get("content"), ch.get("finish_reason"),
                         bool(msg.get("reasoning_content") or msg.get("reasoning") or msg.get("tool_calls")),
                         d.get("usage"), (time.perf_counter() - t0) * 1000)
