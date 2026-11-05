"""Canonical JSON + SHA-256 cho cache key (docs/09 §Khóa)."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

NORMALIZER_VERSION = "norm-1"


def _nfc(obj: Any) -> Any:
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, dict):
        return {_nfc(k): _nfc(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_nfc(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> str:
    return json.dumps(_nfc(obj), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def content_key(obj: Any) -> str:
    return sha256_hex(canonical_json(obj))


def file_sha256(path, chunk: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()
