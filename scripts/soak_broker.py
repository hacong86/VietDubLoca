"""Soak ngắn (E10, docs/13): broker THẬT + Qwen + VieNeu GPU chạy liên tục N phút với client giả lập offscreen.

- Phụ đề dài lặp từ 80 câu seed (mỗi câu ~4 s) phủ hết thời lượng; clock tiến theo thời gian thật.
- Mỗi 3 phút tua (seek) sang vị trí khác → epoch mới; đo frame epoch cũ lọt ra sau tua.
- Mỗi 10 s lấy mẫu RSS (broker + con) và VRAM toàn GPU.
Không phải test trình duyệt. Kết quả: benchmarks/results/soak-<ts>.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psutil
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))
from vietdub.audio_frame import unpack_frame  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HOME = Path("D:/VietDubLocal")
EXT = json.loads((HOME / "local-config.json").read_text(encoding="utf-8-sig"))["allowed_extension_ids"][0]
ORIGIN = f"chrome-extension://{EXT}"


def vram_mb() -> int:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout
    return int(out.strip().splitlines()[0])


def rss_mb(pid: int) -> int:
    p = psutil.Process(pid)
    tot = 0
    for q in [p] + p.children(recursive=True):
        try:
            tot += q.memory_info().rss
        except psutil.Error:
            pass
    return round(tot / 2**20)


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=20)
    a = ap.parse_args()
    dur_ms = int(a.minutes * 60_000) + 30_000
    seeds = [json.loads(l)["source_text"] for l in (ROOT / "benchmarks/seed_envi.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    cues, t, i = [], 1000, 0
    while t < dur_ms:
        text = seeds[i % len(seeds)]
        d = max(2500, min(6000, len(text.split()) * 330))
        cues.append({"cue_id": f"c{i}", "start_ms": t, "end_ms": t + d, "text": text, "committed": True})
        t += d + 700
        i += 1
    st = json.loads((HOME / "runtime/broker.json").read_text(encoding="utf-8"))
    base = f"http://127.0.0.1:{st['port']}"
    stats = {"frames": 0, "audio_end": 0, "ready": 0, "blocked": 0, "errors": {}, "stale_frames_after_seek": 0, "seeks": 0}
    samples: list[dict] = []
    async with httpx.AsyncClient(base_url=base, trust_env=False, timeout=60) as cli:
        tok = (await cli.post("/internal/pair", headers={"X-VietDub-Pairing": st["pairing_secret"]}, json={"extension_origin": ORIGIN})).json()["session_token"]
        H = {"Authorization": f"Bearer {tok}", "Origin": ORIGIN}
        sid = (await cli.post("/v1/sessions", headers=H, json={"video_id": "soakTest001", "tab_id": 1, "mode": "vod_sync"})).json()["session_id"]
        epoch, media, t_last = 0, 0, time.monotonic()
        async with websockets.connect(f"ws://127.0.0.1:{st['port']}/v1/events", origin=ORIGIN, max_size=1 << 20) as ws:
            await ws.send(json.dumps({"type": "auth", "token": tok, "protocol_version": 1}))
            await ws.recv()
            await ws.send(json.dumps({"type": "subscribe", "session_id": sid}))
            for k in range(0, len(cues), 500):
                await cli.post(f"/v1/sessions/{sid}/captions", headers=H, json={
                    "session_id": sid, "timeline_epoch": 0, "source_id": "soak-src", "source_revision": 1, "source_kind": "manual",
                    "language": "en", "coverage": "full", "available_until_ms": cues[-1]["end_ms"], "cues": cues[k:k + 500]})

            async def clock_loop() -> None:
                nonlocal media, t_last, epoch
                t_end = time.monotonic() + a.minutes * 60
                next_seek = time.monotonic() + 180
                next_sample = time.monotonic()
                seek_at = None
                while time.monotonic() < t_end:
                    now = time.monotonic()
                    media += int((now - t_last) * 1000)
                    t_last = now
                    if now >= next_seek:
                        target = (media + 97_000) % (dur_ms - 60_000)
                        r = (await cli.post(f"/v1/sessions/{sid}/control", headers=H, json={"op": "seek", "media_ms": target})).json()
                        epoch, media, seek_at = r["timeline_epoch"], target, time.monotonic()
                        stats["seeks"] += 1
                        stats["_seek_guard"] = (epoch, seek_at)
                        next_seek = now + 180
                    await cli.post(f"/v1/sessions/{sid}/clock", headers=H, json={
                        "session_id": sid, "timeline_epoch": epoch, "video_id": "soakTest001", "media_ms": media, "monotonic_ms": now * 1000,
                        "playback_rate": 1.0, "paused": False, "seeking": False, "stalled": False, "ad_state": "content", "visibility": "visible"})
                    if now >= next_sample:
                        snap = (await cli.get("/v1/status", headers=H)).json()
                        sess = snap.get("session") or {}
                        samples.append({"t_s": round(now - t0), "rss_mb": rss_mb(st["pid"]), "vram_mb": vram_mb(), "state": sess.get("state"),
                                        "buffer_ms": sess.get("buffer_media_ms"), "lag_ms": sess.get("lag_ms")})
                        next_sample = now + 10
                    await asyncio.sleep(1)

            async def ws_loop() -> None:
                while True:
                    m = await ws.recv()
                    if isinstance(m, bytes):
                        h, _ = unpack_frame(m)
                        stats["frames"] += 1
                        g = stats.get("_seek_guard")
                        if g and h["timeline_epoch"] < g[0] and time.monotonic() - g[1] > 0.5:
                            stats["stale_frames_after_seek"] += 1
                        continue
                    e = json.loads(m)
                    ev = e["event"]
                    if ev == "audio.end":
                        stats["audio_end"] += 1
                    elif ev == "translation.ready":
                        stats["ready"] += 1
                    elif ev == "translation.blocked":
                        stats["blocked"] += 1
                    elif ev == "error":
                        c = e["payload"].get("code", "?")
                        stats["errors"][c] = stats["errors"].get(c, 0) + 1

            t0 = time.monotonic()
            wt = asyncio.create_task(ws_loop())
            try:
                await clock_loop()
            finally:
                wt.cancel()
            diag = (await cli.get("/v1/diagnostics/preview", headers=H)).json()
            await cli.delete(f"/v1/sessions/{sid}", headers=H)
    stats.pop("_seek_guard", None)
    first, last = samples[1] if len(samples) > 1 else samples[0], samples[-1]
    res = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "minutes": a.minutes, "cues": len(cues), "stats": stats,
           "rss_mb_first_last_max": [first["rss_mb"], last["rss_mb"], max(s["rss_mb"] for s in samples)],
           "vram_mb_first_last_max": [first["vram_mb"], last["vram_mb"], max(s["vram_mb"] for s in samples)],
           "states": sorted({s["state"] for s in samples if s["state"]}), "metrics": diag.get("metrics", {}), "samples": samples,
           "note_vi": "Client giả lập offscreen (không phải Chrome). VRAM đo toàn GPU gồm app khác."}
    out = ROOT / "benchmarks/results" / f"soak-{time.strftime('%Y%m%dT%H%M%S')}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("samples", "metrics")}, ensure_ascii=False))
    print("saved", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
