"""E2E pipeline TRỰC TIẾP (ASR) trên broker thật: âm thanh tab (fixture tiếng Anh) → faster-whisper CPU → dịch Qwen →
VieNeu streaming → PCM, qua WS đúng như offscreen (frame asr_pcm 100 ms, nhịp thời gian thực).

Đo: độ trễ từ cuối câu nguồn tới âm Việt đầu tiên (NFR-08 mục tiêu p95 ≤ 6 s), lặp câu (FR-009), không phát draft.
Không kiểm tabCapture/AudioWorklet (cần thao tác người dùng — kiểm tay trên Chrome thật).
"""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))
from vietdub.audio_frame import pack_frame, unpack_frame  # noqa: E402

HOME = Path("D:/VietDubLocal")
FIX = HOME / "e2e" / "fixtures"
EXT = json.loads((HOME / "local-config.json").read_text(encoding="utf-8"))["allowed_extension_ids"][0]
ORIGIN = f"chrome-extension://{EXT}"


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    st = json.loads((HOME / "runtime/broker.json").read_text(encoding="utf-8"))
    base = f"http://127.0.0.1:{st['port']}"
    pcm = (FIX / "fake16k.pcm").read_bytes()
    sentences = json.loads((FIX / "sentences.json").read_text(encoding="utf-8-sig"))
    report: dict = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "events": []}
    async with httpx.AsyncClient(base_url=base, trust_env=False, timeout=120) as cli:
        tok = (await cli.post("/internal/pair", headers={"X-VietDub-Pairing": st["pairing_secret"]},
                              json={"extension_origin": ORIGIN})).json()["session_token"]
        H = {"Authorization": f"Bearer {tok}", "Origin": ORIGIN}
        sid = (await cli.post("/v1/sessions", headers=H, json={"video_id": "VDliveTest1", "tab_id": 99, "mode": "live_delayed"})).json()["session_id"]
        async with websockets.connect(f"ws://127.0.0.1:{st['port']}/v1/events", origin=ORIGIN, max_size=1 << 20) as ws:
            await ws.send(json.dumps({"type": "auth", "token": tok, "protocol_version": 1}))
            await ws.recv()
            await ws.send(json.dumps({"type": "subscribe", "session_id": sid}))
            t_asr = time.time()
            r = await cli.post(f"/v1/sessions/{sid}/control", headers=H, json={"op": "asr_start"})
            report["asr_start_s"] = round(time.time() - t_asr, 2)
            print("asr_start", r.status_code, r.json(), "in", report["asr_start_s"], "s")
            epoch = r.json()["timeline_epoch"]
            t0 = time.monotonic()
            first_audio: dict[str, float] = {}
            commits: list[dict] = []
            drafts = 0
            ready: dict[str, dict] = {}

            async def reader() -> None:
                nonlocal drafts
                while True:
                    m = await ws.recv()
                    now = (time.monotonic() - t0) * 1000
                    if isinstance(m, bytes):
                        h, _ = unpack_frame(m)
                        first_audio.setdefault(h["segment_id"], now)
                        continue
                    e = json.loads(m)
                    if e["event"] == "asr.draft" and e["payload"].get("text"):
                        drafts += 1
                    elif e["event"] == "source.changed" and e["payload"].get("committed_text"):
                        commits.append({"t": now, "text": e["payload"]["committed_text"]})
                    elif e["event"] == "translation.ready":
                        ready[e["payload"]["segment_id"]] = {**e["payload"], "t": now}
                    elif e["event"] in ("error", "warning"):
                        report["events"].append(e["payload"])

            rt = asyncio.create_task(reader())
            step = 3200  # 100 ms s16le 16 kHz
            seq = 0
            for off in range(0, len(pcm), step):
                media = int(off / 32)                                # ms
                target = t0 + media / 1000
                await asyncio.sleep(max(0, target - time.monotonic()))
                chunk = pcm[off:off + step]
                if len(chunk) % 2:
                    chunk = chunk[:-1]
                hdr = {"protocol_version": 1, "kind": "asr_pcm", "session_id": sid, "timeline_epoch": epoch, "segment_id": None,
                       "revision": 0, "seq": seq, "sample_rate": 16000, "channels": 1, "codec": "pcm_s16le",
                       "sample_count": len(chunk) // 2, "is_last": False, "capture_monotonic_ms": round(media, 1), "source_media_ms": media}
                await ws.send(pack_frame(hdr, chunk))
                seq += 1
                if seq % 5 == 0:
                    await ws.send(json.dumps({"type": "clock", "clock": {"session_id": sid, "timeline_epoch": epoch, "video_id": "VDliveTest1",
                        "media_ms": media, "monotonic_ms": round(media, 1), "playback_rate": 1, "paused": False, "seeking": False,
                        "stalled": False, "ad_state": "content", "visibility": "visible"}}))
                    await ws.send(json.dumps({"type": "queue.status", "queued_ms": 0}))
            await asyncio.sleep(15)
            rt.cancel()
            segs = (await cli.get(f"/v1/sessions/{sid}/segments", headers=H)).json()["segments"]
            status = (await cli.get(f"/v1/sessions/{sid}", headers=H)).json()
            await cli.delete(f"/v1/sessions/{sid}", headers=H)
    # độ trễ: cuối câu nguồn (mốc biết trước) → âm Việt đầu tiên của unit chứa câu đó
    lat = []
    for s in segs:
        if s["segment_id"] in first_audio:
            src_end = next((x["end_ms"] for x in sentences if x["start_ms"] - 800 <= s["start_ms"] <= x["end_ms"]), s["end_ms"])
            lat.append(first_audio[s["segment_id"]] - src_end)
    all_text = " ".join(c["text"] for c in commits).lower()
    dup = sum(all_text.count(w) > 1 for w in ("original file", "root motion", "api key", "polygon count", "rigidbody"))
    lat_sorted = sorted(lat)
    report.update({
        "commits": len(commits), "drafts": drafts, "units": len(segs), "units_with_audio": len(first_audio),
        "latency_ms": [round(x) for x in lat], "latency_p50_ms": round(statistics.median(lat)) if lat else None,
        "latency_p95_ms": round(lat_sorted[max(0, int(len(lat_sorted) * 0.95) - 1)]) if lat else None,
        "duplicate_phrases": dup, "final_state": status["state"], "lag_ms": status.get("lag_ms"),
        "sample": [{"en": s["source_text"], "vi": s["target_display"]} for s in segs[:6]],
        "asr_text": all_text[:600],
    })
    out = HOME / "e2e" / f"live-asr-{time.strftime('%Y%m%dT%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("sample",)}, ensure_ascii=False, indent=1)[:2500])
    for x in report["sample"]:
        print("  EN:", x["en"], "\n  VI:", x["vi"])
    print("report", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
