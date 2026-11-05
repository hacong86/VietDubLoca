"""E2E broker THẬT (Qwen + VieNeu GPU): phụ đề có '>>' → 2 người nói → 2 giọng VieNeu khác nhau.

Chạy khi broker đang chạy:  .venv-broker/Scripts/python.exe scripts/e2e_speakers.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import websockets

HOME = Path("D:/VietDubLocal")
EXT = json.loads((HOME / "local-config.json").read_text(encoding="utf-8-sig"))["allowed_extension_ids"][0]
ORIGIN = f"chrome-extension://{EXT}"
CUES = [
    (1000, 3500, ">> So how long have you been making games?"),
    (4000, 6500, ">> About ten years now, mostly in Unity."),
    (7000, 9000, "I started with small mobile puzzles."),
    (9500, 12000, ">> That is impressive. What was the hardest part?"),
    (12500, 15500, ">> Shipping. Finishing a game is always the hardest part."),
]


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    st = json.loads((HOME / "runtime/broker.json").read_text(encoding="utf-8"))
    base = f"http://127.0.0.1:{st['port']}"
    async with httpx.AsyncClient(base_url=base, trust_env=False, timeout=60) as cli:
        tok = (await cli.post("/internal/pair", headers={"X-VietDub-Pairing": st["pairing_secret"]},
                              json={"extension_origin": ORIGIN})).json()["session_token"]
        H = {"Authorization": f"Bearer {tok}", "Origin": ORIGIN}
        for _ in range(300):
            rt = (await cli.get("/v1/status", headers=H)).json()["runtime"]
            if rt["translation"]["state"] == "ready" and rt["tts"]["state"] == "ready":
                break
            await asyncio.sleep(1)
        sid = (await cli.post("/v1/sessions", headers=H, json={"video_id": "speakerTest1", "tab_id": 1, "mode": "vod_sync"})).json()["session_id"]
        async with websockets.connect(f"ws://127.0.0.1:{st['port']}/v1/events", origin=ORIGIN, max_size=1 << 20) as ws:
            await ws.send(json.dumps({"type": "auth", "token": tok, "protocol_version": 1}))
            await ws.recv()
            await ws.send(json.dumps({"type": "subscribe", "session_id": sid}))
            cues = [{"cue_id": f"c{i}", "start_ms": a, "end_ms": b, "text": t, "committed": True} for i, (a, b, t) in enumerate(CUES)]
            await cli.post(f"/v1/sessions/{sid}/captions", headers=H, json={
                "session_id": sid, "timeline_epoch": 0, "source_id": "spk-test", "source_revision": 1, "source_kind": "auto",
                "language": "en", "coverage": "full", "available_until_ms": 15500, "cues": cues})
            await cli.post(f"/v1/sessions/{sid}/clock", headers=H, json={
                "session_id": sid, "timeline_epoch": 0, "video_id": "speakerTest1", "media_ms": 0, "monotonic_ms": 1,
                "playback_rate": 1.0, "paused": False, "seeking": False, "stalled": False, "ad_state": "content", "visibility": "visible"})
            begins: dict[str, dict] = {}
            t0 = time.time()
            while time.time() - t0 < 90 and len(begins) < 4:
                m = await asyncio.wait_for(ws.recv(), 30)
                if isinstance(m, bytes):
                    continue
                e = json.loads(m)
                if e["event"] == "audio.begin":
                    begins[e["payload"]["segment_id"]] = e["payload"]
            segs = (await cli.get(f"/v1/sessions/{sid}/segments", headers=H)).json()["segments"]
            await cli.delete(f"/v1/sessions/{sid}", headers=H)
    rows = []
    for s in segs:
        b = begins.get(s["segment_id"], {})
        rows.append({"start": s["start_ms"], "speaker": s["speaker"], "voice": b.get("voice_id") or s.get("voice"),
                     "en": s["source_text"], "vi": s["target_display"]})
        print(json.dumps(rows[-1], ensure_ascii=False))
    def who(prefix: str) -> str | None:
        return next((r["speaker"] for r in rows if r["en"].startswith(prefix)), None)
    voices = {r["speaker"]: r["voice"] for r in rows if r["voice"]}
    ok = (who("So how long") == "Người nói 1" and who("About ten") == "Người nói 2" and who("I started") == "Người nói 2"
          and who("That is impressive") == "Người nói 1" and who("Shipping") == "Người nói 2"
          and len(set(voices.values())) == 2 and not any(">>" in r["en"] for r in rows))
    print("RESULT", "PASS" if ok else "FAIL", json.dumps(voices, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
