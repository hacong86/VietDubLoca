"""Tích hợp THẬT faster-whisper small.en CPU int8 với fixture SAPI tiếng Anh. VIETDUB_INTEGRATION=1."""
import asyncio
import os
import time
import wave

import pytest

from vietdub.paths import REPO_ROOT, SERVICES_DIR, default_paths, worker_env
from vietdub.runtime import locate
from vietdub.runtime.worker_proc import WorkerProcess

pytestmark = pytest.mark.skipif(os.environ.get("VIETDUB_INTEGRATION") != "1", reason="integration only")


def test_asr_worker_commits_stable_text_once():
    paths = default_paths().ensure()
    rt = locate.load(paths)
    wav = wave.open(str(REPO_ROOT / "tests/fixtures/audio/en_sapi_16k.wav"))
    assert wav.getframerate() == 16000 and wav.getnchannels() == 1
    pcm = wav.readframes(wav.getnframes())
    silence = b"\x00\x00" * 16000

    async def run():
        w = WorkerProcess("asr", rt.asr_python, SERVICES_DIR / "vietdub/workers/asr_worker.py", worker_env(paths), paths.home)
        await w.start()
        try:
            h, _ = await w.request("load", timeout=120, model_dir=str(paths.asr_models / "whisper_small_en"),
                                   device="cpu", compute_type="int8", cpu_threads=6)
            assert h["ok"], h
            print("load_ms", h["load_ms"])
            await w.request("reset", epoch=3, session_id="s1")
            data = pcm + silence
            step = 3200  # 100 ms
            t0 = time.perf_counter()
            for i, off in enumerate(range(0, len(data), step * 2)):
                chunk = data[off:off + step * 2]
                await w.push("feed", chunk, seq=i, epoch=3, session_id="s1", source_media_ms=60000 + i * 100,
                             capture_monotonic_ms=1000.0 + i * 100, playback_rate=1.0)
            # dữ liệu epoch cũ phải bị bỏ
            await w.push("feed", silence, seq=999, epoch=2, session_id="s1", source_media_ms=0, capture_monotonic_ms=0,
                         playback_rate=1.0)
            await w.request("flush", timeout=60, epoch=3)
            elapsed = time.perf_counter() - t0
            commits, drafts = [], 0
            while not w.events.empty():
                ev, _ = w.events.get_nowait()
                if ev["op"] == "asr.commit":
                    commits.append(ev)
                elif ev["op"] == "asr.draft":
                    drafts += 1
            text = " ".join(c["text"] for c in commits).lower()
            print("elapsed", round(elapsed, 2), "audio_s", len(data) / 32000, "commits", len(commits), "drafts", drafts)
            print(text)
            assert "original file" in text and "inspector" in text and "root motion" in text
            assert text.count("original file") == 1          # không lặp ở hai cửa sổ
            assert all(c["epoch"] == 3 for c in commits)
            assert all(c["start_media_ms"] >= 60000 for c in commits)
            ends = [c["end_media_ms"] for c in commits]
            assert ends == sorted(ends)
        finally:
            await w.stop()

    asyncio.run(run())
