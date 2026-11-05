"""target_spoken từ target_display (docs/04 §7; FR-014). Quy tắc có version; không đổi phụ đề."""
from __future__ import annotations

import re

PHONETIC_RULES_VERSION = "spoken-1"

_URL = re.compile(r"https?://\S+")
_BACKTICK = re.compile(r"`([^`]*)`")
_BRACKET = re.compile(r"\[([^\]]{0,80})\]")
_ANGLE = re.compile(r"[<>]")
_WS = re.compile(r"\s+")


def to_spoken(display: str, pronunciations: dict[str, str] | None = None) -> str:
    """``pronunciations``: literal (phân biệt hoa thường) -> cách đọc. Áp dụng theo từ nguyên vẹn."""
    s = display
    for lit, say in sorted((pronunciations or {}).items(), key=lambda kv: -len(kv[0])):
        if lit and say:
            s = re.sub(r"(?<![\w])" + re.escape(lit) + r"(?![\w])", say, s)
    s = _URL.sub("đường dẫn", s)
    s = _BACKTICK.sub(r"\1", s)
    # Không cho văn bản nguồn tạo control tag cảm xúc của TTS: [cười] -> (cười)
    s = _BRACKET.sub(r"(\1)", s)
    s = _ANGLE.sub(" ", s)
    s = s.replace("VDTERM_", "")
    return _WS.sub(" ", s).strip()
