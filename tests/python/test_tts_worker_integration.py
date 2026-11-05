"""Tích hợp THẬT với VieNeu (GPU). Chạy khi đặt VIETDUB_INTEGRATION=1. Không mock."""
import asyncio
import os
import time

import numpy as np
import pytest

from vietdub.audio_frame import s16le_to_float
from vietdub.paths import SERVICES_DIR, default_paths, worker_env
from vietdub.runtime import locate
from vietdub.runtime.worker_proc import WorkerProcess

pytestmark = pytest.mark.skipif(os.environ.get("VIETDUB_INTEGRATION") != "1", reason="integration only")


def test_tts_worker_real_vieneu():
    paths = default_paths().ensure()
    rt = locate.load(paths)
    assert rt.tts_python, "không tìm thấy python TTS"

    async def run():
        w = WorkerProcess("tts", rt.tts_python, SERVICES_DIR / "vietdub" / "workers" / "tts_worker.py",
                          worker_env(paths), paths.home)
        await w.start()
        try:
            h, _ = await w.request("load", timeout=300, max_batch_size=2, warmup=True)
            assert h["ok"], h
            assert h["sample_rate"] == 48000
            v, _ = await w.request("list_voices", timeout=30)
            ids = [x["voice_id"] for x in v["voices"]]
            assert len(ids) > 0
            assert "Minh Quân" in v["aliases"] or "Minh Quân Pro" in ids
            t0 = time.perf_counter()
            r, pcms = await w.request("infer", timeout=60, want_pcm=1, text="Đừng xóa tệp gốc trước khi kiểm tra bản sao.",
                                      voice="Minh Quân", batch_size=1, watermark=True)
            dt = time.perf_counter() - t0
            assert r["ok"], r
            a = s16le_to_float(pcms[0])
            dur = len(a) / 48000
            assert 1.0 < dur < 8.0 and np.max(np.abs(a)) > 0.05
            print(f"infer {dt:.2f}s dur {dur:.2f}s voice {r['voice']}")
            bad, _ = await w.request("infer", timeout=30, text="xin chào", voice="Không Có Giọng Này")
            assert bad["ok"] is False and bad["error"] == "VOICE_NOT_FOUND"
            frames = []
            async for fh, fp in w.stream("infer_stream", text="Mở Inspector và bỏ chọn Apply Root Motion.", voice="Minh Quân Pro"):
                frames.append(fp)
            total = sum(len(f) for f in frames) // 2 / 48000
            assert total > 1.0
            health, _ = await w.request("health", timeout=10)
            print("health", health)
        finally:
            await w.stop()
        assert not w.alive

    asyncio.run(run())
