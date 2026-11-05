"""Xác thực loopback (FR-041, docs/11): token phiên ≥256 bit TTL, gắn origin extension; Origin/Host allowlist;
rate limit; idempotency. Token KHÔNG bao giờ nằm trong URL/log."""
from __future__ import annotations

import hmac
import re
import secrets
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from ..errors import AppError

TOKEN_TTL_S = 12 * 3600
EXT_ORIGIN_RE = re.compile(r"^chrome-extension://([a-p]{32})$")
IDEMPOTENCY_TTL_S = 600


@dataclass
class TokenInfo:
    origin: str
    expires_at: float


class TokenStore:
    def __init__(self, allowed_extension_ids: set[str]) -> None:
        self.allowed = set(allowed_extension_ids)
        self._tokens: dict[str, TokenInfo] = {}
        self.pairing_secret = secrets.token_urlsafe(32)

    def origin_allowed(self, origin: str | None) -> bool:
        if not origin:
            return False
        m = EXT_ORIGIN_RE.match(origin)
        return bool(m and m.group(1) in self.allowed)

    def issue(self, pairing_secret: str, origin: str) -> tuple[str, float]:
        if not hmac.compare_digest(pairing_secret.encode(), self.pairing_secret.encode()):
            raise AppError("AUTH_REQUIRED")
        if not self.origin_allowed(origin):
            raise AppError("ORIGIN_DENIED")
        self._gc()
        tok = secrets.token_urlsafe(32)          # 256 bit
        exp = time.time() + TOKEN_TTL_S
        self._tokens[tok] = TokenInfo(origin, exp)
        return tok, exp

    def check(self, token: str | None, origin: str | None) -> TokenInfo:
        if not token:
            raise AppError("AUTH_REQUIRED")
        info = None
        for t, i in self._tokens.items():         # so sánh hằng thời gian
            if hmac.compare_digest(t.encode(), token.encode()):
                info = i
                break
        if info is None:
            raise AppError("AUTH_REQUIRED")
        if info.expires_at < time.time():
            self._tokens.pop(token, None)
            raise AppError("AUTH_EXPIRED")
        if origin is not None and origin != info.origin:
            raise AppError("ORIGIN_DENIED")
        return info

    def revoke_all(self) -> None:
        self._tokens.clear()

    def _gc(self) -> None:
        now = time.time()
        for t in [t for t, i in self._tokens.items() if i.expires_at < now]:
            self._tokens.pop(t, None)


def host_ok(host_header: str | None, port: int) -> bool:
    return host_header in (f"127.0.0.1:{port}", f"localhost:{port}")


def bearer(auth_header: str | None) -> str | None:
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    return auth_header[7:].strip() or None


class RateLimiter:
    def __init__(self, per_sec: float = 30, burst: int = 60) -> None:
        self.per_sec = per_sec
        self.burst = burst
        self._hits: dict[str, deque] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] > self.burst / self.per_sec:
            q.popleft()
        if len(q) >= self.burst:
            return False
        q.append(now)
        return True


class Idempotency:
    """request_id/idempotency_key: cùng key + cùng payload → trả kết quả cũ; khác payload → 409."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, str, Any]] = {}

    def check(self, key: str | None, fingerprint: str) -> Any | None:
        if not key:
            return None
        now = time.time()
        for k in [k for k, v in self._store.items() if now - v[0] > IDEMPOTENCY_TTL_S]:
            self._store.pop(k, None)
        hit = self._store.get(key)
        if not hit:
            return None
        if hit[1] != fingerprint:
            raise AppError("IDEMPOTENCY_CONFLICT")
        return hit[2]

    def remember(self, key: str | None, fingerprint: str, result: Any) -> None:
        if key:
            self._store[key] = (time.time(), fingerprint, result)


def redact(s: str) -> str:
    """Xóa chuỗi giống token/đường dẫn người dùng khỏi log."""
    s = re.sub(r"Bearer\s+[\w.-]+", "Bearer ***", s)
    s = re.sub(r"[A-Za-z0-9_-]{40,}", "***", s)
    s = re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", r"C:\\Users\\***", s)
    return s
