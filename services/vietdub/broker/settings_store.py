"""Settings allowlist + version (FR-033). Chỉ khóa trong allowlist; kiểu/khoảng được kiểm."""
from __future__ import annotations

import copy
from typing import Any

from ..errors import AppError

DEFAULTS: dict[str, Any] = {
    "translation": {"model_id": "qwen35_4b_q5", "topic": "general"},
    "tts": {"voice_id": "Minh Quân Pro", "device": "auto", "watermark": True, "alternate_speakers": True, "voice_alt_id": ""},
    "playback": {"mode": "vod_sync", "original_gain": 0.15, "vietnamese_gain": 1.0, "auto_hold_vod": True,
                 "prefetch_target_ms": 30000, "low_water_ms": 8000, "high_water_ms": 45000,
                 "residual_stretch_max": 1.25, "seek_mid_sentence": "replay_prompt", "subtitle_mode": "bilingual",
                 "subtitle_size": 22, "subtitle_position": "bottom", "live_queue_hard_cap_ms": 30000, "preload_enabled": True, "preload_target_s": 30},
    "storage": {"history_opt_in": False, "private_mode": False, "cache_limit_bytes": 2 * 1024 ** 3, "cache_ttl_days": 14},
    "privacy": {"payload_logs": False, "start_with_windows": False},
    "shortcuts": {"toggle": "Alt+Shift+V", "replay": "Alt+Shift+R", "next": "Alt+Shift+N"},
}

TOPICS = ("general", "unity", "ai_coding", "business", "numbers", "conversational")
MODES = ("vod_sync", "live_delayed", "study")

# path -> (type, validator)
RULES: dict[str, tuple[type | tuple[type, ...], Any]] = {
    "translation.model_id": (str, lambda v: len(v) <= 64),
    "translation.topic": (str, lambda v: v in TOPICS),
    "tts.voice_id": (str, lambda v: 0 < len(v) <= 80),
    "tts.device": (str, lambda v: v in ("auto", "cpu")),
    "tts.watermark": (bool, None),
    "tts.alternate_speakers": (bool, None),
    "tts.voice_alt_id": (str, lambda v: len(v) <= 80),
    "playback.mode": (str, lambda v: v in MODES),
    "playback.original_gain": ((int, float), lambda v: 0 <= v <= 1),
    "playback.vietnamese_gain": ((int, float), lambda v: 0 <= v <= 2),
    "playback.auto_hold_vod": (bool, None),
    "playback.prefetch_target_ms": (int, lambda v: 5000 <= v <= 120000),
    "playback.low_water_ms": (int, lambda v: 1000 <= v <= 60000),
    "playback.high_water_ms": (int, lambda v: 10000 <= v <= 180000),
    "playback.residual_stretch_max": ((int, float), lambda v: 1.0 <= v <= 1.25),   # ADR-022 (user chốt 2026-09-24)
    "playback.preload_enabled": (bool, None),
    "playback.preload_target_s": (int, lambda v: v in (10, 20, 30)),
    "playback.seek_mid_sentence": (str, lambda v: v in ("replay_prompt", "skip_current")),
    "playback.subtitle_mode": (str, lambda v: v in ("off", "vi", "bilingual")),
    "playback.subtitle_size": (int, lambda v: 14 <= v <= 48),
    "playback.subtitle_position": (str, lambda v: v in ("bottom", "top")),
    "playback.live_queue_hard_cap_ms": (int, lambda v: 10000 <= v <= 30000),
    "storage.history_opt_in": (bool, None),
    "storage.private_mode": (bool, None),
    "storage.cache_limit_bytes": (int, lambda v: 256 * 1024 ** 2 <= v <= 50 * 1024 ** 3),
    "storage.cache_ttl_days": (int, lambda v: 1 <= v <= 365),
    "privacy.payload_logs": (bool, None),
    "privacy.start_with_windows": (bool, None),
    "shortcuts.toggle": (str, lambda v: len(v) <= 32),
    "shortcuts.replay": (str, lambda v: len(v) <= 32),
    "shortcuts.next": (str, lambda v: len(v) <= 32),
}


def merged(stored: dict[str, Any] | None) -> dict[str, Any]:
    out = copy.deepcopy(DEFAULTS)
    for sec, vals in (stored or {}).items():
        if sec in out and isinstance(vals, dict):
            for k, v in vals.items():
                if f"{sec}.{k}" in RULES:
                    out[sec][k] = v
    return out


def validate_patch(patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise AppError("VALIDATION_FAILED", {"field": "settings"})
    clean: dict[str, Any] = {}
    for sec, vals in patch.items():
        if not isinstance(vals, dict):
            raise AppError("VALIDATION_FAILED", {"field": str(sec)[:40]})
        for k, v in vals.items():
            path = f"{sec}.{k}"
            rule = RULES.get(path)
            if rule is None:
                raise AppError("VALIDATION_FAILED", {"field": path[:60]})
            typ, check = rule
            if isinstance(v, bool) and typ is not bool and typ != (int, float):
                raise AppError("VALIDATION_FAILED", {"field": path})
            if not isinstance(v, typ) or (typ is int and isinstance(v, bool)):
                raise AppError("VALIDATION_FAILED", {"field": path})
            if check and not check(v):
                raise AppError("VALIDATION_FAILED", {"field": path})
            clean.setdefault(sec, {})[k] = v
    return clean
