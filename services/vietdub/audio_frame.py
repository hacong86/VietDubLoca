"""Audio protocol v1 (docs/08 §5): 4 byte BE header length + JSON UTF-8 + PCM s16le mono.

Dựa trên codec tham chiếu ``tools/audio_framing.py``; epoch/revision ownership kiểm ở consumer.
"""
from __future__ import annotations

import json
import math
import struct
from typing import Any

import numpy as np

from .contracts import no_duplicate_keys

MAX_HEADER = 4096
MAX_FRAME = 256 * 1024
REQUIRED = {"protocol_version", "kind", "session_id", "timeline_epoch", "segment_id", "revision",
            "seq", "sample_rate", "channels", "codec", "sample_count", "is_last"}
ALLOWED = REQUIRED | {"capture_monotonic_ms", "source_media_ms"}
TTS_RATE = 48000
ASR_RATE = 16000


def validate_header(h: dict[str, Any], pcm_length: int) -> None:
    if not isinstance(h, dict) or not REQUIRED <= h.keys() or h.keys() - ALLOWED:
        raise ValueError("bad audio header keys")
    if type(h["protocol_version"]) is not int or h["protocol_version"] != 1:
        raise ValueError("bad protocol version")
    if type(h["channels"]) is not int or h["channels"] != 1 or h["codec"] != "pcm_s16le":
        raise ValueError("only pcm_s16le mono")
    for k in ("timeline_epoch", "revision", "seq", "sample_count"):
        if type(h[k]) is not int or h[k] < 0:
            raise ValueError("non-negative int required: " + k)
    if type(h["is_last"]) is not bool:
        raise ValueError("is_last must be bool")
    if not isinstance(h["session_id"], str) or not 1 <= len(h["session_id"]) <= 128:
        raise ValueError("bad session_id")
    if h["segment_id"] is not None and (not isinstance(h["segment_id"], str) or not 1 <= len(h["segment_id"]) <= 128):
        raise ValueError("bad segment_id")
    if h["kind"] == "asr_pcm":
        if h["sample_rate"] != ASR_RATE or h["segment_id"] is not None:
            raise ValueError("ASR needs 16k and segment_id=null")
        for k in ("capture_monotonic_ms", "source_media_ms"):
            v = h.get(k)
            if type(v) not in (int, float) or not math.isfinite(v) or v < 0:
                raise ValueError("ASR missing source clock: " + k)
        if type(h["source_media_ms"]) is not int:
            raise ValueError("source_media_ms must be int")
    elif h["kind"] == "tts_pcm":
        if h["sample_rate"] != TTS_RATE or not h["segment_id"]:
            raise ValueError("TTS needs 48k and segment_id")
    else:
        raise ValueError("unsupported kind")
    if pcm_length != h["sample_count"] * 2:
        raise ValueError("PCM length != sample_count*2")


def pack_frame(header: dict[str, Any], pcm: bytes) -> bytes:
    validate_header(header, len(pcm))
    raw = json.dumps(header, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > MAX_HEADER or 4 + len(raw) + len(pcm) > MAX_FRAME:
        raise ValueError("frame too large")
    return struct.pack(">I", len(raw)) + raw + pcm


def unpack_frame(frame: bytes) -> tuple[dict[str, Any], bytes]:
    if len(frame) < 4 or len(frame) > MAX_FRAME:
        raise ValueError("bad frame length")
    n = struct.unpack(">I", frame[:4])[0]
    if not 1 <= n <= MAX_HEADER or 4 + n > len(frame):
        raise ValueError("bad header length")
    h = json.loads(frame[4:4 + n].decode("utf-8"), object_pairs_hook=no_duplicate_keys)
    pcm = frame[4 + n:]
    validate_header(h, len(pcm))
    return h, pcm


def float_to_s16le(audio: np.ndarray) -> bytes:
    a = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not np.all(np.isfinite(a)):
        raise ValueError("audio contains NaN/Inf")
    a = np.clip(a, -1.0, 1.0)
    return (np.round(a * 32767.0)).astype("<i2").tobytes()


def s16le_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def split_pcm(pcm: bytes, samples_per_frame: int = 24000) -> list[bytes]:
    """Chia PCM để mỗi frame ≤ 256 KiB. 24000 mẫu = 48 000 byte = 0,5 s ở 48 kHz."""
    step = samples_per_frame * 2
    return [pcm[i:i + step] for i in range(0, len(pcm), step)] or [b""]
