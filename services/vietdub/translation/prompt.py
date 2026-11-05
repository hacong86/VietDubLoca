"""Dựng request dịch (docs/04 §3, §6; FR-011). Context tham khảo tách khỏi segments cần trả."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..paths import REPO_ROOT
from .glossary import Glossary, Protected, protect

PROMPT_VERSION = "translation-1.0"
CONTEXT_TOKENS = 4096
MAX_OUTPUT_TOKENS = 512
SAFETY_TOKENS = 128


def _read(name: str) -> str:
    return (REPO_ROOT / "prompts" / name).read_text(encoding="utf-8").strip()


SYSTEM_PROMPT = _read("translation_system.vi.txt")
REPAIR_PROMPT = _read("repair_system.vi.txt")


def estimate_tokens(text: str) -> int:
    """Ước lượng thận trọng (không có tokenizer trong broker): ~1 token / 3 ký tự, tiếng Việt ~1/2.5."""
    return int(len(text) / 2.5) + 8


@dataclass
class UnitInput:
    segment_id: str
    source_text: str


@dataclass
class BuiltRequest:
    payload: dict[str, Any]
    protected: dict[str, Protected]
    user_json: str
    context_before: list[str]
    context_after: list[str]


def output_schema(ids: list[str]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": ["translations"],
            "properties": {"translations": {"type": "array", "minItems": len(ids), "maxItems": len(ids),
                           "items": {"type": "object", "additionalProperties": False,
                                     "required": ["segment_id", "target_text"],
                                     "properties": {"segment_id": {"type": "string", "enum": ids},
                                                    "target_text": {"type": "string", "minLength": 1}}}}}}


def build_request(units: list[UnitInput], *, context_before: list[str], context_after: list[str], topic: str,
                  glossary: Glossary, model_alias: str, sampling: dict[str, Any],
                  max_output_tokens: int = MAX_OUTPUT_TOKENS) -> BuiltRequest:
    if not units:
        raise ValueError("no units")
    protected: dict[str, Protected] = {}
    segs = []
    next_idx = 1
    glossary_view: list[dict[str, str]] = []
    hints: list[dict[str, str]] = []
    for u in units:
        p = protect(u.source_text, glossary, topic, start_index=next_idx)
        next_idx += len(p.mapping)
        protected[u.segment_id] = p
        segs.append({"segment_id": u.segment_id, "source_text": p.text})
        glossary_view += [{"code": ph, "keep_exactly": lit} for ph, lit in p.mapping.items()]
        hints += [h for h in p.hints if h not in hints]
    cb, ca = list(context_before), list(context_after)

    def compose() -> str:
        body: dict[str, Any] = {"domain": topic, "context_before": cb, "context_after": ca,
                                "protected_codes": glossary_view, "terminology": hints, "segments": segs}
        return json.dumps(body, ensure_ascii=False)

    user = compose()
    budget = CONTEXT_TOKENS - max_output_tokens - SAFETY_TOKENS - estimate_tokens(SYSTEM_PROMPT)
    # Giảm context tham khảo trước; KHÔNG cắt văn bản cần dịch.
    while estimate_tokens(user) > budget and (cb or ca):
        if cb:
            cb.pop(0)
        else:
            ca.pop()
        user = compose()
    if estimate_tokens(user) > budget:
        raise ValueError("segments too long for context; builder must split units")
    ids = [u.segment_id for u in units]
    payload = {
        "model": model_alias,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
        "stream": False,
        "max_tokens": max_output_tokens,
        "response_format": {"type": "json_schema", "json_schema": {"name": "translations", "strict": True,
                                                                   "schema": output_schema(ids)}},
        **{k: v for k, v in sampling.items() if k in ("temperature", "top_p", "top_k", "seed", "chat_template_kwargs")},
    }
    return BuiltRequest(payload, protected, user, cb, ca)


def build_repair(original: BuiltRequest, bad_content: str, problems: list[str]) -> dict[str, Any]:
    p = dict(original.payload)
    note = json.dumps({"problems": problems[:10], "previous_output": (bad_content or "")[:4000]}, ensure_ascii=False)
    p["messages"] = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + REPAIR_PROMPT},
                     {"role": "user", "content": original.user_json},
                     {"role": "user", "content": note}]
    return p
