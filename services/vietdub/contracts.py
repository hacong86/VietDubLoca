"""Validate wire data bằng JSON Schema trong ``contracts/`` + business invariants (docs/08 §9)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .errors import AppError
from .paths import REPO_ROOT

CONTRACTS_DIR = REPO_ROOT / "contracts"
SCHEMAS = {
    "audio_chunk": "audio-chunk.schema.json",
    "caption_batch": "caption-batch.schema.json",
    "error": "error.schema.json",
    "event": "event.schema.json",
    "playback_clock": "playback-clock.schema.json",
    "translation_output": "translation-output.schema.json",
}


@lru_cache(maxsize=None)
def schema(name: str) -> dict[str, Any]:
    return json.loads((CONTRACTS_DIR / SCHEMAS[name]).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(schema(name))


def schema_errors(name: str, obj: Any) -> list[str]:
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.validator}" for e in _validator(name).iter_errors(obj)]


def validate(name: str, obj: Any) -> None:
    errs = schema_errors(name, obj)
    if errs:
        raise AppError("VALIDATION_FAILED", {"field": errs[0][:120]})


def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("duplicate JSON key")
        out[k] = v
    return out


def strict_loads(raw: bytes | str) -> Any:
    return json.loads(raw, object_pairs_hook=no_duplicate_keys)


def validate_caption_batch(batch: dict[str, Any], *, session_id: str, epoch: int) -> None:
    validate("caption_batch", batch)
    if batch["session_id"] != session_id:
        raise AppError("VALIDATION_FAILED", {"field": "session_id"})
    if batch["timeline_epoch"] != epoch:
        raise AppError("STALE_EPOCH", {"expected": epoch, "actual": batch["timeline_epoch"]})
    seen: set[str] = set()
    for c in batch["cues"]:
        if c["end_ms"] < c["start_ms"]:
            raise AppError("VALIDATION_FAILED", {"field": "end_ms", "segment_id": c["cue_id"]})
        if c["cue_id"] in seen:
            raise AppError("VALIDATION_FAILED", {"field": "cue_id"})
        seen.add(c["cue_id"])


def validate_clock(clock: dict[str, Any], *, session_id: str, epoch: int, video_id: str) -> None:
    validate("playback_clock", clock)
    if clock["session_id"] != session_id or clock["video_id"] != video_id:
        raise AppError("VALIDATION_FAILED", {"field": "session_id"})
    if clock["timeline_epoch"] != epoch:
        raise AppError("STALE_EPOCH", {"expected": epoch, "actual": clock["timeline_epoch"]})


def load_example(name: str) -> Any:
    return json.loads((REPO_ROOT / "examples" / name).read_text(encoding="utf-8"))


def repo_file(rel: str) -> Path:
    return REPO_ROOT / rel
