"""Chuẩn hóa cue (docs/04 §1) và loại trùng rolling caption bằng token + time overlap."""
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field

# Chỉ các thẻ WebVTT/SRT phổ biến; mọi thẻ khác cũng bị gỡ (không bao giờ render HTML).
_VOICE = re.compile(r"<v(?:\.[\w.-]+)?\s+([^>]{1,64})>", re.I)
_TAG = re.compile(r"</?[a-zA-Z][^<>]{0,64}>|<\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}>")
_WS = re.compile(r"\s+")


@dataclass
class Cue:
    cue_id: str
    start_ms: int
    end_ms: int
    text: str                     # đã normalize
    raw_text: str = ""
    committed: bool = True
    speaker: str | None = None
    meta: dict = field(default_factory=dict)


def normalize_text(raw: str) -> tuple[str, str | None]:
    """Trả (text, speaker). Giữ số/ký hiệu/code; bỏ markup; NFC; gộp khoảng trắng."""
    speaker = None
    m = _VOICE.search(raw)
    if m:
        speaker = m.group(1).strip()
    t = _TAG.sub("", raw)
    t = html.unescape(t)
    t = t.replace(chr(0x200B), "").replace(chr(0xFEFF), "")
    t = unicodedata.normalize("NFC", t)
    t = _WS.sub(" ", t).strip()
    return t, speaker


TURN_SPEAKERS = ("Người nói 1", "Người nói 2")
_TURN = re.compile(r"^>>\s*")


def split_turn(text: str) -> tuple[str, bool]:
    """YouTube đánh dấu đổi người nói bằng '>>' ở ĐẦU cue. Chỉ xét đầu cue: 'x >> 2' giữa câu là code thật."""
    if _TURN.match(text):
        return _TURN.sub("", text, count=1).strip(), True
    return text, False


def assign_turn_speakers(cues: list[Cue]) -> None:
    """Gán luân phiên 2 người nói theo dấu '>>' (deterministic, chạy lại mỗi lần dựng unit).
    Bỏ qua nếu nguồn đã có tên người nói thật (thẻ <v Tên> WebVTT) hoặc không có dấu nào."""
    ordered = sorted(cues, key=lambda c: (c.start_ms, c.end_ms))
    for c in ordered:                       # chỉ phụ thuộc cue hiện tại, không lịch sử cập nhật
        if c.meta.pop("turn_assigned", False):
            c.speaker = None
    if any(c.meta.get("tag_speaker") for c in ordered) or not any(c.meta.get("turn") for c in ordered):
        return
    idx = 0
    for i, c in enumerate(ordered):
        if c.meta.get("turn") and i > 0:
            idx ^= 1
        c.speaker = TURN_SPEAKERS[idx]
        c.meta["turn_assigned"] = True


def tokens(text: str) -> list[str]:
    return text.split()


def _tok_key(tok: str) -> str:
    return re.sub(r"^[^\w]+|[^\w]+$", "", tok.lower())


def dedupe_rolling(cues: list[Cue]) -> list[Cue]:
    """Loại phần lặp của caption cuộn.

    Chỉ cắt khi cue sau CHỒNG THỜI GIAN với cue trước và bắt đầu bằng hậu tố token của cue trước.
    Cue không chồng thời gian giữ nguyên (người nói thật sự nhắc lại "No, no, no").
    """
    out: list[Cue] = []
    prev_raw_tokens: list[str] = []
    prev_end = -1
    for c in sorted(cues, key=lambda x: (x.start_ms, x.end_ms)):
        toks = tokens(c.text)
        if prev_raw_tokens and c.start_ms < prev_end and not c.meta.get("turn"):   # đổi người nói: không cắt chồng lấp
            a = [_tok_key(t) for t in prev_raw_tokens]
            b = [_tok_key(t) for t in toks]
            k_best = 0
            for k in range(min(len(a), len(b)), 0, -1):
                if a[-k:] == b[:k]:
                    k_best = k
                    break
            if k_best:
                rest = toks[k_best:]
                prev_raw_tokens = toks
                prev_end = max(prev_end, c.end_ms)
                if not rest:
                    continue  # cue chỉ lặp lại, không có chữ mới
                out.append(Cue(c.cue_id, c.start_ms, c.end_ms, " ".join(rest), c.raw_text, c.committed, c.speaker,
                               {**c.meta, "rolling_trimmed": k_best}))
                continue
        out.append(c)
        prev_raw_tokens = toks
        prev_end = c.end_ms
    return out
