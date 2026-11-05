"""Framed stdio IPC broker↔worker (docs/08 §7). CHỈ thư viện chuẩn (chạy trong venv TTS/ASR).

Frame: uint32 LE độ dài header → JSON UTF-8 header → ``payload_bytes`` byte nhị phân (tùy chọn).
stdout của worker chỉ chứa frame; log đi stderr.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import threading
from typing import Any, BinaryIO

MAX_HEADER = 64 * 1024
MAX_PAYLOAD = 64 * 1024 * 1024
OPS = {"load", "list_voices", "infer", "infer_batch", "infer_stream", "cancel", "health", "unload", "shutdown",
       "feed", "flush", "reset"}


class FrameError(ValueError):
    pass


def encode(header: dict[str, Any], payload: bytes = b"") -> bytes:
    h = dict(header)
    h["payload_bytes"] = len(payload)
    raw = json.dumps(h, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > MAX_HEADER or len(payload) > MAX_PAYLOAD:
        raise FrameError("frame too large")
    return struct.pack("<I", len(raw)) + raw + payload


def _read_exact(f: BinaryIO, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return bytes(buf)


def read_frame(f: BinaryIO) -> tuple[dict[str, Any], bytes]:
    n = struct.unpack("<I", _read_exact(f, 4))[0]
    if not 1 <= n <= MAX_HEADER:
        raise FrameError("bad header length")
    h = json.loads(_read_exact(f, n).decode("utf-8"))
    if not isinstance(h, dict):
        raise FrameError("header not object")
    pb = h.get("payload_bytes", 0)
    if type(pb) is not int or not 0 <= pb <= MAX_PAYLOAD:
        raise FrameError("bad payload length")
    payload = _read_exact(f, pb) if pb else b""
    return h, payload


class WorkerIO:
    """Phía worker: đọc lệnh (thread riêng để cancel tới được giữa job), ghi frame có khóa."""

    def __init__(self) -> None:
        # Windows: một ReadFile đồng bộ đang chờ trên pipe stdin chặn mọi GetFileType/isatty khác trên CÙNG
        # file object (torch/numpy gọi khi import) → deadlock. Tách pipe IPC ra fd riêng, rồi trỏ fd 0 về NUL
        # và fd 1 về stderr để code thư viện không chạm pipe IPC và không làm bẩn frame stdout.
        sys.stdout.flush()
        in_fd, out_fd = os.dup(0), os.dup(1)
        null = os.open(os.devnull, os.O_RDONLY)
        os.dup2(null, 0)
        os.close(null)
        os.dup2(2, 1)
        self._in = os.fdopen(in_fd, "rb", buffering=0)
        self._out = os.fdopen(out_fd, "wb", buffering=0)
        self._wlock = threading.Lock()
        sys.stdin = open(os.devnull, "r")
        sys.stdout = sys.stderr

    def send(self, header: dict[str, Any], payload: bytes = b"") -> None:
        data = encode(header, payload)
        with self._wlock:
            self._out.write(data)
            self._out.flush()

    def recv(self) -> tuple[dict[str, Any], bytes]:
        return read_frame(self._in)


def log(msg: str) -> None:
    print(f"[worker] {msg}", file=sys.stderr, flush=True)
