"""Kiểm tra output model trước TTS (docs/04 §6; FR-015). Chặn cấu trúc sai; cảnh báo heuristic."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..contracts import no_duplicate_keys
from .glossary import PLACEHOLDER_RE

_REASONING = re.compile(r"</?think>|<\|[a-z_]+\|>|\bassistant\s*:|^\s*(?:Suy nghĩ|Reasoning)\s*:", re.I | re.M)
_TOOLISH = re.compile(r'"(?:tool_calls|function_call|name)"\s*:')
_VI_DIACRITIC = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)
_LATIN_WORD = re.compile(r"[A-Za-zÀ-ỹ]+")


@dataclass
class UnitCheck:
    segment_id: str
    target_text: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class BatchCheck:
    ok: bool
    units: dict[str, UnitCheck]
    errors: list[str]           # lỗi cấp batch (JSON/ID)

    def failed_ids(self) -> list[str]:
        return [k for k, u in self.units.items() if u.errors]


def parse_and_check(content: Any, finish_reason: str | None, expected: dict[str, dict[str, Any]],
                    reasoning_present: bool = False) -> BatchCheck:
    """``expected``: segment_id -> {"source": text có placeholder, "counts": {ph: n}, "mapping": {ph: literal}}."""
    errors: list[str] = []
    if finish_reason == "length":
        errors.append("TRUNCATED")
    if reasoning_present:
        errors.append("REASONING_PRESENT")
    if not isinstance(content, str):
        return BatchCheck(False, {}, errors + ["NO_CONTENT"])
    if _REASONING.search(content):
        errors.append("REASONING_TAG")
    try:
        obj = json.loads(content, object_pairs_hook=no_duplicate_keys)
    except (ValueError, json.JSONDecodeError):
        return BatchCheck(False, {}, errors + ["JSON_INVALID"])
    if not isinstance(obj, dict) or set(obj) != {"translations"} or not isinstance(obj["translations"], list):
        return BatchCheck(False, {}, errors + ["SCHEMA_TOP"])
    units: dict[str, UnitCheck] = {}
    for item in obj["translations"]:
        if not isinstance(item, dict) or set(item) != {"segment_id", "target_text"}:
            errors.append("SCHEMA_ITEM")
            continue
        sid, txt = item["segment_id"], item["target_text"]
        if not isinstance(sid, str) or not isinstance(txt, str):
            errors.append("SCHEMA_ITEM")
            continue
        if sid not in expected:
            errors.append("UNKNOWN_ID")
            continue
        if sid in units:
            errors.append("DUPLICATE_ID")
            continue
        units[sid] = check_unit(sid, txt, expected[sid])
    missing = set(expected) - set(units)
    if missing:
        errors.append("MISSING_ID")
    if _TOOLISH.search(content):
        errors.append("TOOL_FIELDS")
    ok = not errors and all(not u.errors for u in units.values())
    return BatchCheck(ok, units, errors)


def check_unit(sid: str, txt: str, exp: dict[str, Any]) -> UnitCheck:
    u = UnitCheck(sid, txt)
    t = txt.strip()
    if not t:
        u.errors.append("EMPTY")
        return u
    if _REASONING.search(t):
        u.errors.append("REASONING_TAG")
    if "{" in t and "segment_id" in t:
        u.errors.append("JSON_LEAK")
    counts: dict[str, int] = exp.get("counts", {})
    mapping: dict[str, str] = exp.get("mapping", {})
    for ph, n in counts.items():
        got = t.count(ph)
        # Model đôi khi viết thẳng literal gốc thay vì mã: literal CHÍNH XÁC được tính tương đương (ADR-011).
        lit = mapping.get(ph)
        if got < n and lit:
            got += t.count(lit)
        if got != n:
            u.errors.append(f"PLACEHOLDER_COUNT:{ph}")
    for ph in set(PLACEHOLDER_RE.findall(t)):
        if ph not in counts:
            u.errors.append("UNKNOWN_PLACEHOLDER")
    if "VDTERM" in PLACEHOLDER_RE.sub("", t):
        u.errors.append("MANGLED_PLACEHOLDER")
    # Cảnh báo (không chặn): ngôn ngữ và tỉ lệ độ dài.
    src = exp.get("source", "")
    plain = PLACEHOLDER_RE.sub("", t)
    words = _LATIN_WORD.findall(plain)
    if len(words) >= 6 and not _VI_DIACRITIC.search(plain):
        u.warnings.append("LANG_SUSPECT")
    sw = max(1, len(src.split()))
    ratio = len(t.split()) / sw
    if sw >= 4 and (ratio < 0.5 or ratio > 3.0):
        u.warnings.append(f"LENGTH_RATIO:{ratio:.2f}")
    return u
