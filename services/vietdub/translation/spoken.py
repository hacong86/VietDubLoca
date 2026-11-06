"""target_spoken từ target_display (docs/04 §7; FR-014). Quy tắc có version; không đổi phụ đề."""
from __future__ import annotations

import re

PHONETIC_RULES_VERSION = "spoken-2-no-sound-labels"

_URL = re.compile(r"https?://\S+")
_BACKTICK = re.compile(r"`([^`]*)`")
_BRACKET = re.compile(r"\[([^\]]{0,80})\]")
_ANGLE = re.compile(r"[<>]")
_WS = re.compile(r"\s+")
_SOUND_LABEL = re.compile(
    r"^(?:nhạc(?:\s+(?:nền|dạo|nổi lên|tiếp tục|lớn dần|nhỏ dần))?|âm nhạc|tiếng nhạc|"
    r"vỗ tay|tiếng vỗ tay|tiếng cười|cười|tiếng hoan hô|hoan hô|"
    r"music|background music|instrumental music|applause|clapping|laughter|laughing|cheering|"
    r"ดนตรี|เสียงเพลง|เพลง|เสียงปรบมือ|ปรบมือ|เสียงหัวเราะ|音乐|音樂|掌声|掌聲|音楽|拍手|음악|박수)$", re.I)
_ANNOTATION = re.compile(r"\[([^\[\]]{1,100})\]|\(([^()]{1,100})\)|【([^【】]{1,100})】")


def is_sound_only(text: str) -> bool:
    """Recognise complete sound labels, never arbitrary text containing a keyword."""
    if any(c in text for c in "♪♫♬") and not any(c.isalnum() for c in text):
        return True
    remaining = _ANNOTATION.sub(lambda m: " " if is_sound_only(next(g for g in m.groups() if g is not None)) else m.group(0), text)
    if remaining != text and not any(c.isalnum() for c in remaining):
        return True
    text = text.strip().strip("[]()【】 ")
    parts = [p.strip() for p in re.split(r"[,;…:./!！?？♪♫♬\-–—]+", text) if p.strip()]
    return bool(parts) and all(_SOUND_LABEL.fullmatch(p) for p in parts)


def sound_description(text: str) -> str | None:
    """A subtitle made solely of known sound labels needs no AI or speech."""
    if not is_sound_only(text):
        return None
    lower = text.casefold()
    labels = []
    if any(c in text for c in "♪♫♬") or re.search(r"nhạc|music|instrumental|ดนตรี|เสียงเพลง|เพลง|音乐|音樂|音楽|음악", lower):
        labels.append("nhạc")
    if re.search(r"vỗ tay|applause|clapping|ปรบมือ|掌声|掌聲|拍手|박수", lower):
        labels.append("vỗ tay")
    if re.search(r"cười|laugh|หัวเราะ", lower):
        labels.append("tiếng cười")
    if re.search(r"hoan hô|cheering", lower):
        labels.append("hoan hô")
    return "[" + ", ".join(labels or ["âm thanh"]) + "]"


def strip_sound_annotations(text: str) -> str:
    """Remove only explicit sound labels, keeping surrounding dialogue."""
    text = _ANNOTATION.sub(lambda m: " " if is_sound_only(next(g for g in m.groups() if g is not None)) else m.group(0), text)
    return _WS.sub(" ", text.replace("♪", " ").replace("♫", " ").replace("♬", " ")).strip()


def to_spoken(display: str, pronunciations: dict[str, str] | None = None) -> str:
    """``pronunciations``: literal (phân biệt hoa thường) -> cách đọc. Áp dụng theo từ nguyên vẹn."""
    s = display
    if is_sound_only(s):
        return ""
    s = strip_sound_annotations(s)
    for lit, say in sorted((pronunciations or {}).items(), key=lambda kv: -len(kv[0])):
        if lit and say:
            s = re.sub(r"(?<![\w])" + re.escape(lit) + r"(?![\w])", say, s)
    s = _URL.sub("đường dẫn", s)
    s = _BACKTICK.sub(r"\1", s)
    # Không cho văn bản nguồn tạo control tag cảm xúc của TTS: [cười] -> (cười)
    s = _BRACKET.sub(r"(\1)", s)
    s = _ANGLE.sub(" ", s)
    s = s.replace("VDTERM_", "")
    s = _WS.sub(" ", s).strip()
    return s if any(c.isalnum() for c in s) else ""
