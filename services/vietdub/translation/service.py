"""Dịch một nhóm unit: cache → model → validate → ≤1 repair → display/spoken (docs/04; FR-010..FR-017)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..errors import AppError
from ..hashing import NORMALIZER_VERSION, content_key, sha256_hex
from .glossary import Glossary, restore
from .llm import LlmResult
from .prompt import PROMPT_VERSION, UnitInput, build_repair, build_request
from .spoken import PHONETIC_RULES_VERSION, is_sound_only, sound_description, strip_sound_annotations, to_spoken
from .validate import parse_and_check

MAX_UNITS_PER_BATCH = 3
MAX_WORDS_PER_BATCH = 120


class ChatBackend(Protocol):
    async def chat(self, payload: dict[str, Any]) -> LlmResult: ...


@dataclass
class ModelFingerprint:
    model_id: str
    alias: str
    artifact_sha256: str
    runtime_build: str
    sampling: dict[str, Any]

    def value(self) -> str:
        return content_key({"model": self.model_id, "sha": self.artifact_sha256, "rt": self.runtime_build,
                            "sampling": self.sampling})


@dataclass
class UnitRequest:
    segment_id: str
    source_text: str
    source_hash: str
    context_before: list[str]
    context_after: list[str]


@dataclass
class UnitResult:
    segment_id: str
    status: str                          # READY | BLOCKED
    target_display: str = ""
    target_spoken: str = ""
    cache_key: str = ""
    context_hash: str = ""
    flags: list[str] = field(default_factory=list)
    from_cache: bool = False
    error_code: str | None = None
    latency_ms: float = 0.0


def context_hash(before: list[str], after: list[str]) -> str:
    return content_key({"b": before, "a": after})


def translation_cache_key(u: UnitRequest, *, topic: str, glossary_version: int, fp: ModelFingerprint, source_language: str = "en") -> str:
    fields = {"src": u.source_text, "src_hash": u.source_hash,
                        "ctx": context_hash(u.context_before, u.context_after), "sl": source_language.lower(), "tl": "vi",
                        "topic": topic, "glossary_version": glossary_version, "prompt": PROMPT_VERSION,
                        "model": fp.value(), "norm": NORMALIZER_VERSION}
    if strip_sound_annotations(u.source_text) != u.source_text:
        fields["sound_filter"] = PHONETIC_RULES_VERSION
    return content_key(fields)


class TranslationCache(Protocol):
    def get(self, cache_key: str) -> dict[str, Any] | None: ...


def pronunciations_from(glossary: Glossary, topic: str) -> dict[str, str]:
    return {e.source: e.target_spoken for e in glossary.active(topic) if e.target_spoken}


def plan_batches(units: list[UnitRequest]) -> list[list[UnitRequest]]:
    batches: list[list[UnitRequest]] = []
    cur: list[UnitRequest] = []
    words = 0
    for u in units:
        w = len(u.source_text.split())
        if cur and (len(cur) >= MAX_UNITS_PER_BATCH or words + w > MAX_WORDS_PER_BATCH):
            batches.append(cur)
            cur, words = [], 0
        cur.append(u)
        words += w
    if cur:
        batches.append(cur)
    return batches


async def translate_batch(backend: ChatBackend, units: list[UnitRequest], *, topic: str, glossary: Glossary,
                          fp: ModelFingerprint, cache: TranslationCache | None = None,
                          max_repairs: int = 1, source_language: str = "en") -> list[UnitResult]:
    results: dict[str, UnitResult] = {}
    todo: list[UnitRequest] = []
    for u in units:
        key = translation_cache_key(u, topic=topic, glossary_version=glossary.version, fp=fp, source_language=source_language)
        label = sound_description(u.source_text)
        if label is not None:
            results[u.segment_id] = UnitResult(u.segment_id, "READY", label, "", key,
                                               context_hash(u.context_before, u.context_after), ["NON_SPEECH"])
            continue
        hit = cache.get(key) if cache else None
        if hit and hit.get("status") in ("READY",):
            spoken = "" if is_sound_only(u.source_text) else to_spoken(hit["target_spoken"])
            results[u.segment_id] = UnitResult(u.segment_id, "READY", hit["target_display"], spoken,
                                               key, context_hash(u.context_before, u.context_after),
                                               list(hit.get("flags", [])), True)
        else:
            todo.append(u)
    if todo:
        # Context chung của nhóm: trước unit đầu, sau unit cuối.
        req = build_request([UnitInput(u.segment_id, strip_sound_annotations(u.source_text) or u.source_text) for u in todo],
                            context_before=todo[0].context_before, context_after=todo[-1].context_after,
                            topic=topic, glossary=glossary, model_alias=fp.alias, sampling=fp.sampling, source_language=source_language)
        expected = {sid: {"source": p.text, "counts": p.expected_counts, "mapping": p.mapping}
                    for sid, p in req.protected.items()}
        fatal_kinds = ("TRUNCATED", "REASONING_PRESENT", "REASONING_TAG", "JSON_INVALID", "SCHEMA_TOP",
                       "TOOL_FIELDS", "NO_CONTENT")
        res = await backend.chat(req.payload)
        chk = parse_and_check(res.content, res.finish_reason, expected, res.reasoning_present)
        total_ms = res.latency_ms
        fatal1 = [e for e in chk.errors if e in fatal_kinds]
        # accepted[sid] = UnitCheck từ một lượt không có lỗi cấp batch và không lỗi unit
        best = {sid: (uc, fatal1) for sid, uc in chk.units.items()}
        repaired = False
        needs = [sid for sid in expected if sid not in best or best[sid][0].errors or best[sid][1]]
        if needs and max_repairs > 0:
            problems = chk.errors + [f"{sid}:{e}" for sid, uc in chk.units.items() for e in uc.errors]
            res2 = await backend.chat(build_repair(req, res.content if isinstance(res.content, str) else "", problems))
            total_ms += res2.latency_ms
            chk2 = parse_and_check(res2.content, res2.finish_reason, expected, res2.reasoning_present)
            fatal2 = [e for e in chk2.errors if e in fatal_kinds]
            for sid in needs:
                if sid in chk2.units:
                    best[sid] = (chk2.units[sid], fatal2)
            repaired = True
        pron = pronunciations_from(glossary, topic)
        for u in todo:
            key = translation_cache_key(u, topic=topic, glossary_version=glossary.version, fp=fp, source_language=source_language)
            ch = context_hash(u.context_before, u.context_after)
            uc, batch_fatal = best.get(u.segment_id, (None, []))
            if uc is None or uc.errors or batch_fatal:
                code = "TRANSLATION_TRUNCATED" if "TRUNCATED" in batch_fatal else "TRANSLATION_INVALID"
                flags = (uc.errors if uc else ["MISSING_ID"]) + batch_fatal
                results[u.segment_id] = UnitResult(u.segment_id, "BLOCKED", "", "", key, ch, flags,
                                                   error_code=code, latency_ms=total_ms)
                continue
            p = req.protected[u.segment_id]
            display = restore(uc.target_text.strip(), p.mapping)
            spoken_map = dict(pron)
            for ph, say in p.spoken.items():
                spoken_map[p.mapping[ph]] = say
            spoken = "" if is_sound_only(u.source_text) else to_spoken(display, spoken_map)
            flags = list(uc.warnings) + (["REPAIRED"] if repaired and u.segment_id in needs else [])
            results[u.segment_id] = UnitResult(u.segment_id, "READY", display, spoken, key, ch, flags,
                                               latency_ms=total_ms)
    return [results[u.segment_id] for u in units]


def audio_cache_key(*, display: str, spoken: str, voice_id: str, voice_fingerprint: str, sdk_version: str,
                    tts_model_revision: str, controls: dict[str, Any]) -> str:
    return content_key({"display": sha256_hex(display), "spoken": spoken, "voice": voice_id, "vfp": voice_fingerprint,
                        "sdk": sdk_version, "model": tts_model_revision, "controls": controls,
                        "phonetic": PHONETIC_RULES_VERSION})


def ensure_not_blocked(r: UnitResult) -> None:
    if r.status != "READY":
        raise AppError(r.error_code or "TRANSLATION_INVALID", {"segment_id": r.segment_id})
