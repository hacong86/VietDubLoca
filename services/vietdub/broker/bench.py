"""Benchmark A/B local trong app (FR-039, docs/13). Chỉ đo latency/cấu trúc/lỗi; KHÔNG tự chấm chất lượng.

Chạy trên model đang nạp, tắt cache dịch, tùy chọn chạy VieNeu đồng thời (tải B). Không gửi dữ liệu đi đâu.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from typing import Any

from ..paths import REPO_ROOT
from ..translation.glossary import Glossary
from ..translation.service import UnitRequest, translate_batch


def _pct(v: list[float], q: float) -> float | None:
    if not v:
        return None
    a = sorted(v)
    i = (len(a) - 1) * q
    lo, hi = int(i), min(len(a) - 1, int(i) + 1)
    return round(a[lo] + (a[hi] - a[lo]) * (i - lo), 1)


async def run_benchmark(ctx: Any, job_id: str, *, limit: int, split: str, with_tts: bool) -> None:
    job = ctx.jobs[job_id]
    try:
        rows = [json.loads(l) for l in (REPO_ROOT / "benchmarks/seed_envi.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        rows = [r for r in rows if split == "all" or r["split"] == split][:max(1, min(limit, 80))]
        fp = ctx.rt.fingerprint()
        if fp is None or not ctx.rt.translation_ready():
            job.update(state="failed", error="MODEL_NOT_READY")
            return
        glossary = Glossary()
        lat: list[float] = []
        tts_lat: list[float] = []
        results = []
        stop = asyncio.Event()

        async def tts_load() -> None:              # tải B: VieNeu chạy đồng thời
            while not stop.is_set():
                t0 = time.perf_counter()
                try:
                    await ctx.rt.synth("Đây là câu thử tải đồng thời cho phép đo hiệu năng.", ctx.settings()["tts"]["voice_id"])
                    tts_lat.append((time.perf_counter() - t0) * 1000)
                except Exception:
                    await asyncio.sleep(0.5)

        tts_task = asyncio.create_task(tts_load()) if with_tts and ctx.rt.tts_ready() else None
        for i, r in enumerate(rows):
            u = UnitRequest(r["id"], r["source_text"], r["id"], r.get("context_before", []), r.get("context_after", []))
            t0 = time.perf_counter()
            [res] = await translate_batch(ctx.rt, [u], topic=r.get("domain", "general"), glossary=glossary, fp=fp, cache=None)
            ms = (time.perf_counter() - t0) * 1000
            if res.status == "READY":
                lat.append(ms)
            # reference_vi KHÔNG vào prompt; chỉ ghi kèm để người chấm xem sau.
            results.append({"id": r["id"], "source": r["source_text"], "output": res.target_display, "status": res.status,
                            "flags": res.flags, "ms": round(ms, 1)})
            job["progress"] = round((i + 1) / len(rows), 3)
        stop.set()
        if tts_task:
            await tts_task
        out = {"model_id": fp.model_id, "runtime_build": fp.runtime_build, "sampling": fp.sampling, "n": len(rows),
               "valid": len(lat), "failed": len(rows) - len(lat), "translate_p50_ms": _pct(lat, .5),
               "translate_p95_ms": _pct(lat, .95), "concurrent_tts": bool(tts_task), "tts_calls": len(tts_lat),
               "tts_p50_ms": _pct(tts_lat, .5), "semantic_quality": "NOT_REVIEWED — cần người chấm mù",
               "results": results, "created": time.strftime("%Y-%m-%d %H:%M:%S")}
        name = f"bench-{fp.model_id}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        (ctx.paths.diagnostics / name).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        job.update(state="done", result={k: v for k, v in out.items() if k != "results"} | {"file_name": name,
                                                                                           "sample": results[:10]})
    except Exception as e:  # noqa: BLE001
        job.update(state="failed", error=type(e).__name__)
    _ = statistics
