"""Sentence builder (docs/04 §2): gộp cue thành TranslationUnit đủ nghĩa, giữ time map.

Mốc thời gian do chương trình tính (nội suy theo vị trí ký tự trong cue); LLM không bao giờ sửa.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..hashing import sha256_hex
from .text import Cue

MAX_WORDS = 60
MAX_MS = 12_000
PAUSE_MS = 800
MIN_WORDS_FOR_PAUSE = 3

_ABBR = {"mr.", "mrs.", "ms.", "dr.", "prof.", "st.", "vs.", "etc.", "e.g.", "i.e.", "inc.", "ltd.", "jr.", "sr.",
         "no.", "fig.", "approx.", "u.s.", "u.k.", "a.m.", "p.m.", "ver.", "v."}
# Không tách sau các từ này (vế phụ còn tiếp): phủ định, điều kiện, liên từ, giới từ, mạo từ.
_NO_SPLIT_AFTER = {"not", "don't", "doesn't", "didn't", "unless", "if", "only", "and", "or", "but", "to", "the", "a",
                   "an", "of", "for", "with", "without", "than", "because", "so", "that", "which", "when", "while",
                   "before", "after", "until", "is", "are", "was", "were", "be", "can", "can't", "cannot", "will",
                   "won't", "should", "shouldn't", "must", "mustn't", "never", "no", "your", "my", "this", "these",
                   "in", "on", "at", "from", "into", "by", "as", "then", "also", "just", "very", "too"}
_CONJ = {"and", "but", "or", "so", "because", "which", "while", "although", "though", "whereas", "then"}
_SENT_END = re.compile(r"[.?!…。！？]+[\"'”’)\]]*$")
_DECIMAL = re.compile(r"\d[.,]\d")


@dataclass
class Tok:
    text: str
    start_ms: int
    end_ms: int
    cue_id: str


@dataclass
class TranslationUnit:
    unit_id: str
    source_id: str
    cue_ids: list[str]
    start_ms: int
    end_ms: int
    source_text: str
    source_hash: str
    boundary_reason: str
    final: bool
    revision: int = 1
    speaker: str | None = None
    cue_map: list[dict] = field(default_factory=list)

    def word_count(self) -> int:
        return len(self.source_text.split())


def _cue_tokens(c: Cue) -> list[Tok]:
    words = c.text.split()
    if not words:
        return []
    total = sum(len(w) + 1 for w in words)
    span = max(0, c.end_ms - c.start_ms)
    out, pos = [], 0
    for w in words:
        s = c.start_ms + round(span * pos / total)
        pos += len(w) + 1
        e = c.start_ms + round(span * pos / total)
        out.append(Tok(w, s, max(s, e), c.cue_id))
    return out


def _is_sentence_end(tok: str) -> bool:
    low = tok.lower()
    if low in _ABBR:
        return False
    if not _SENT_END.search(tok):
        return False
    if _DECIMAL.search(tok) and not tok.endswith((".", "?", "!")):
        return False
    return True


def _key(tok: str) -> str:
    return re.sub(r"^[^\w']+|[^\w']+$", "", tok.lower())


def _pick_cap_split(toks: list[Tok]) -> tuple[int, str]:
    """Chọn vị trí tách khi vượt 60 từ/12 s: ưu tiên dấu phẩy/chấm phẩy, rồi liên từ; không tách sau _NO_SPLIT_AFTER."""
    n = len(toks)
    lo = max(1, int(n * 0.35))
    for i in range(n - 1, lo - 1, -1):
        t = toks[i - 1].text
        if t.endswith((",", ";", ":", "—", "–")) and _key(t) not in _NO_SPLIT_AFTER:
            return i, "cap_comma"
    for i in range(n - 1, lo - 1, -1):
        if _key(toks[i].text) in _CONJ and _key(toks[i - 1].text) not in _NO_SPLIT_AFTER:
            return i, "cap_conjunction"
    for i in range(n - 1, lo - 1, -1):
        if _key(toks[i - 1].text) not in _NO_SPLIT_AFTER:
            return i, "cap_hard"
    return n - 1, "cap_hard"


def make_unit_id(source_id: str, start_ms: int, text: str) -> str:
    return "u_" + sha256_hex(f"{source_id}|{start_ms}|{text}")[:20]


def _build(source_id: str, toks: list[Tok], reason: str, final: bool, speakers: dict[str, str | None]) -> TranslationUnit:
    text = " ".join(t.text for t in toks)
    cue_ids: list[str] = []
    cue_map: list[dict] = []
    for i, t in enumerate(toks):
        if not cue_ids or cue_ids[-1] != t.cue_id:
            cue_ids.append(t.cue_id)
            cue_map.append({"cue_id": t.cue_id, "token_start": i, "token_end": i + 1})
        else:
            cue_map[-1]["token_end"] = i + 1
    start = toks[0].start_ms
    end = max(t.end_ms for t in toks)
    return TranslationUnit(make_unit_id(source_id, start, text), source_id, cue_ids, start, end, text,
                           sha256_hex(text), reason, final, speaker=speakers.get(toks[0].cue_id), cue_map=cue_map)


def build_units(source_id: str, cues: list[Cue], *, complete: bool, max_words: int = MAX_WORDS,
                max_ms: int = MAX_MS, pause_ms: int = PAUSE_MS) -> list[TranslationUnit]:
    """Chạy lại toàn bộ (deterministic). ``complete``=True khi nguồn đã đủ tới cuối (coverage full)
    thì unit cuối là final; ngược lại unit đuôi chưa có ranh giới là ``final=False`` (chưa được dịch)."""
    speakers = {c.cue_id: c.speaker for c in cues}
    units: list[TranslationUnit] = []
    acc: list[Tok] = []
    ordered = sorted(cues, key=lambda c: (c.start_ms, c.end_ms))
    all_toks: list[tuple[Tok, int | None]] = []  # (tok, gap_before_ms)
    prev_end: int | None = None
    for c in ordered:
        ct = _cue_tokens(c)
        for j, t in enumerate(ct):
            gap = (c.start_ms - prev_end) if (j == 0 and prev_end is not None) else None
            all_toks.append((t, gap))
        if ct:
            prev_end = c.end_ms

    def flush(reason: str, final: bool = True) -> None:
        nonlocal acc
        if acc:
            units.append(_build(source_id, acc, reason, final, speakers))
            acc = []

    for idx, (t, gap) in enumerate(all_toks):
        speaker_change = acc and speakers.get(t.cue_id) and speakers.get(acc[-1].cue_id) \
            and speakers.get(t.cue_id) != speakers.get(acc[-1].cue_id)
        if acc and gap is not None and gap > pause_ms and len(acc) >= MIN_WORDS_FOR_PAUSE \
                and _key(acc[-1].text) not in _NO_SPLIT_AFTER:
            flush("pause")
        elif speaker_change:
            flush("speaker")
        acc.append(t)
        if _is_sentence_end(t.text):
            flush("punctuation")
            continue
        while acc and (len(acc) > max_words or (acc[-1].end_ms - acc[0].start_ms) > max_ms) and len(acc) > 1:
            cut, why = _pick_cap_split(acc)
            head, tail = acc[:cut], acc[cut:]
            units.append(_build(source_id, head, why, True, speakers))
            acc = tail
    if acc:
        flush("end" if complete else "pending", final=complete)
    return units
