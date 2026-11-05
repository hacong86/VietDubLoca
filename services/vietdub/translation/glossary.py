"""Glossary + protected literals (docs/04 §3, §5; FR-013).

- policy ``preserve``: literal thay bằng placeholder ``VDTERM_0001`` trước khi gửi model, khôi phục sau.
- policy ``translate``: chỉ là gợi ý thuật ngữ trong prompt (không thay chuỗi mù quáng).
- Tự động bảo vệ literal kỹ thuật: `code`, URL, đường dẫn, cờ CLI, lệnh git/npm..., identifier có _ hoặc ().
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

PLACEHOLDER_RE = re.compile(r"VDTERM_\d{4}")
RESERVED = "VDTERM_"

_AUTO_PATTERNS = [
    re.compile(r"`[^`\n]{1,80}`"),
    re.compile(r"https?://[^\s<>\"']{3,200}"),
    re.compile(r"\b[A-Za-z]:\\[^\s<>\"'|?*]{1,200}"),                       # C:\path\file
    re.compile(r"(?<![\w/])(?:~|\.{1,2})?/(?:[\w.-]+/)+[\w.-]+"),             # /usr/bin/x, ./a/b
    re.compile(r"\b(?:git|npm|pnpm|yarn|pip|python|py|node|npx|dotnet|adb|flutter|docker|cargo|uv)\s+"
               r"[\w.:@/-]+(?:\s+--?[\w-]+(?:=[\w.-]+)?)*"),
    re.compile(r"(?<![\w-])--[a-z][\w-]{1,40}(?:=[\w.-]+)?"),
    re.compile(r"\b[a-z][\w]*(?:\.[a-z][\w]*){2,}\b"),                        # com.appmaven.demo
    re.compile(r"\b[A-Za-z_][\w]*\(\)"),                                      # foo()
    re.compile(r"\b[a-z]+_[a-z0-9_]+\b"),                                     # snake_case
    re.compile(r"\b\.[a-z]{2,5}\b(?= file| extension|\b)"),                    # .env, .json
]


@dataclass
class GlossaryEntry:
    source: str
    domain: str = "general"
    policy: str = "preserve"            # preserve | translate
    case_sensitive: bool = False
    whole_phrase: bool = True
    target_display: str | None = None
    target_spoken: str | None = None    # cách đọc; None = đọc như hiển thị
    enabled: bool = True
    entry_id: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "GlossaryEntry":
        src = str(d["source"]).strip()
        if not src or len(src) > 200 or RESERVED in src:
            raise ValueError("glossary source invalid")
        pol = d.get("policy", "preserve")
        if pol not in ("preserve", "translate"):
            raise ValueError("glossary policy invalid")
        tgt = d.get("target_display")
        if pol == "translate" and not tgt:
            raise ValueError("translate entry needs target_display")
        return GlossaryEntry(src, str(d.get("domain") or "general")[:40], pol, bool(d.get("case_sensitive", False)),
                             bool(d.get("whole_phrase", True)), tgt, d.get("target_spoken") or None,
                             bool(d.get("enabled", True)), d.get("entry_id"))

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "domain": self.domain, "policy": self.policy,
                "case_sensitive": self.case_sensitive, "whole_phrase": self.whole_phrase,
                "target_display": self.target_display, "target_spoken": self.target_spoken,
                "enabled": self.enabled, "entry_id": self.entry_id}

    def pattern(self) -> re.Pattern[str]:
        esc = re.escape(self.source)
        if self.whole_phrase:
            esc = r"(?<![\w])" + esc + r"(?![\w])"
        return re.compile(esc, 0 if self.case_sensitive else re.IGNORECASE)


@dataclass
class Glossary:
    version: int = 1
    entries: list[GlossaryEntry] = field(default_factory=list)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Glossary":
        entries = [GlossaryEntry.from_dict(e) for e in d.get("entries", [])]
        keys = [(e.domain, e.source.lower()) for e in entries]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate glossary entry (domain, source)")
        return Glossary(int(d.get("version", 1)), entries)

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "entries": [e.to_dict() for e in self.entries]}

    def active(self, topic: str) -> list[GlossaryEntry]:
        return [e for e in self.entries if e.enabled and e.domain in ("general", topic)]


@dataclass
class Protected:
    text: str                                   # nguồn đã thay placeholder
    mapping: dict[str, str]                     # placeholder -> literal gốc
    spoken: dict[str, str]                      # placeholder -> cách đọc (nếu có)
    expected_counts: dict[str, int]
    hints: list[dict[str, str]]                 # gợi ý thuật ngữ translate


def protect(source: str, glossary: Glossary, topic: str, start_index: int = 1) -> Protected:
    if RESERVED in source:
        # Nguồn chứa namespace dự trữ: vô hiệu hóa để không nhầm với placeholder của chương trình.
        source = source.replace(RESERVED, "VD TERM_")
    spans: list[tuple[int, int, str, str | None]] = []   # start, end, literal, spoken

    def taken(s: int, e: int) -> bool:
        return any(not (e <= a or s >= b) for a, b, _, _ in spans)

    active = glossary.active(topic)
    for e in sorted((x for x in active if x.policy == "preserve"), key=lambda x: -len(x.source)):
        for m in e.pattern().finditer(source):
            if not taken(m.start(), m.end()):
                spans.append((m.start(), m.end(), m.group(0), e.target_spoken))
    for pat in _AUTO_PATTERNS:
        for m in pat.finditer(source):
            if not taken(m.start(), m.end()):
                spans.append((m.start(), m.end(), m.group(0), None))
    spans.sort()
    mapping: dict[str, str] = {}
    spoken: dict[str, str] = {}
    literal_to_ph: dict[str, str] = {}
    out, pos = [], 0
    counts: dict[str, int] = {}
    idx = start_index
    for s, e, lit, sp in spans:
        out.append(source[pos:s])
        ph = literal_to_ph.get(lit)
        if ph is None:
            ph = f"VDTERM_{idx:04d}"
            idx += 1
            literal_to_ph[lit] = ph
            mapping[ph] = lit
            if sp:
                spoken[ph] = sp
        counts[ph] = counts.get(ph, 0) + 1
        out.append(ph)
        pos = e
    out.append(source[pos:])
    hints = []
    for e in active:
        if e.policy == "translate" and e.pattern().search(source):
            hints.append({"source": e.source, "target": e.target_display or ""})
    return Protected("".join(out), mapping, spoken, counts, hints)


def restore(target: str, mapping: dict[str, str]) -> str:
    for ph, lit in mapping.items():
        target = target.replace(ph, lit)
    return target


def glossary_version_of(glossary: Glossary) -> int:
    return glossary.version


def merge_import(current: Glossary, incoming: Iterable[dict[str, Any]]) -> tuple[Glossary, list[str]]:
    """Nhập JSON: thêm mới/ghi đè theo (domain, source); trả danh sách xung đột đã ghi đè."""
    by_key = {(e.domain, e.source.lower()): e for e in current.entries}
    conflicts = []
    for d in incoming:
        e = GlossaryEntry.from_dict(d)
        k = (e.domain, e.source.lower())
        if k in by_key and by_key[k].to_dict() != e.to_dict():
            conflicts.append(f"{e.domain}:{e.source}")
        by_key[k] = e
    return Glossary(current.version + 1, list(by_key.values())), conflicts
