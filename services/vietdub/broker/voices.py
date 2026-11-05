"""Chọn giọng thứ hai cho người nói khác (đổi giọng theo lượt nói)."""
from __future__ import annotations

from typing import Any


def _gender(label: str) -> str | None:
    # nhãn VieNeu: "⭐ Trúc Ly — Nữ · Bắc · Phong cách tự nhiên"
    part = label.split("—", 1)[-1].strip()
    if part.startswith("Nữ"):
        return "f"
    if part.startswith("Nam"):
        return "m"
    return None


def pick_alt_voice(main: str, voices: list[dict[str, Any]]) -> str | None:
    """Giọng khác giới với giọng chính (ưu tiên giọng gắn ⭐ theo thứ tự SDK); không có → giọng khác bất kỳ."""
    others = [v for v in voices if v.get("voice_id") and v["voice_id"] != main]
    if not others:
        return None
    main_v = next((v for v in voices if v.get("voice_id") == main), None)
    g = _gender(str(main_v.get("label", ""))) if main_v else None
    if g:
        opposite = [v for v in others if _gender(str(v.get("label", ""))) not in (g, None)]
        if opposite:
            starred = [v for v in opposite if str(v.get("label", "")).startswith("⭐")]
            return (starred or opposite)[0]["voice_id"]
    return others[0]["voice_id"]
