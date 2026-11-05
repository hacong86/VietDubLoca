"""Smoke E2E broker THẬT (llama.cpp Qwen + VieNeu GPU) bằng client giả lập offscreen.

Không phải test trình duyệt: kiểm pairing, REST, WS auth, caption→dịch→TTS→PCM 48k, seek/epoch, override.
Chạy khi broker đang chạy:  .venv-broker/Scripts/python.exe scripts/e2e_broker_smoke.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import wave
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))
from vietdub.audio_frame import unpack_frame  # noqa: E402
from vietdub.subtitles import parse  # noqa: E402

HOME = Path("D:/VietDubLocal")
EXT = json.loads((HOME / "local-config.json").read_text(encoding="utf-8"))["allowed_extension_ids"][0]
ORIGIN = f"chrome-extension://{EXT}"
SRT = """1
00:00:01,000 --> 00:00:03,200
Welcome back. In this video we are going to set up

2
00:00:03,200 --> 00:00:05,600
a character controller in Unity.

3
00:00:06,500 --> 00:00:09,000
Make sure you don't delete the original file

4
00:00:09,000 --> 00:00:11,000
before checking the copy.

5
00:00:12,000 --> 00:00:15,500
Open the Inspector and uncheck Apply Root Motion.

6
00:00:16,000 --> 00:00:19,500
If the reference is null, skip this step and show a warning.

7
00:00:20,000 --> 00:00:24,000
You can enable this option, but only after creating a backup.

8
00:00:25,000 --> 00:00:28,000
Never paste your API key into a public issue.
"""


async def main() -> int:
    st = json.loads((HOME / "runtime/broker.json").read_text(encoding="utf-8"))
    base = f"http://127.0.0.1:{st['port']}"
    async with httpx.AsyncClient(base_url=base, trust_env=False, timeout=60) as cli:
        t = await cli.post("/internal/pair", headers={"X-VietDub-Pairing": st["pairing_secret"]},
                           json={"extension_origin": ORIGIN})
        tok = t.json()["session_token"]
        H = {"Authorization": f"Bearer {tok}", "Origin": ORIGIN}
        # chờ model sẵn sàng
        t0 = time.time()
        while True:
            s = (await cli.get("/v1/status", headers=H)).json()
            rt = s["runtime"]
            if rt["translation"]["state"] == "ready" and rt["tts"]["state"] == "ready":
                break
            if time.time() - t0 > 300:
                print("TIMEOUT waiting runtime", rt)
                return 2
            await asyncio.sleep(1)
        print("runtime ready after", round(time.time() - t0, 1), "s:", json.dumps(rt, ensure_ascii=False))
        print("gpu:", s["gpu"])
        env = (await cli.get("/v1/env", headers=H)).json()
        print("env.ready =", env["ready"], [i["key"] for i in env["items"] if not i["ok"]])
        voices = (await cli.get("/v1/voices", headers=H)).json()
        print("voices:", len(voices["voices"]), "selected:", voices["selected"])
        r = await cli.post("/v1/sessions", headers=H, json={"video_id": "smokeTest01", "tab_id": 1, "mode": "vod_sync"})
        sid = r.json()["session_id"]
        async with websockets.connect(f"ws://127.0.0.1:{st['port']}/v1/events", origin=ORIGIN,
                                      max_size=1 << 20) as ws:
            await ws.send(json.dumps({"type": "auth", "token": tok, "protocol_version": 1}))
            print("ws:", json.loads(await ws.recv())["event"])
            await ws.send(json.dumps({"type": "subscribe", "session_id": sid}))
            cues = [{"cue_id": f"c{c.index}", "start_ms": c.start_ms, "end_ms": c.end_ms, "text": c.text, "committed": True}
                    for c in parse(SRT)]
            tb = time.time()
            r = await cli.post(f"/v1/sessions/{sid}/captions", headers=H, json={
                "session_id": sid, "timeline_epoch": 0, "source_id": "smoke-en", "source_revision": 1,
                "source_kind": "import", "language": "en", "coverage": "full", "available_until_ms": 28000, "cues": cues})
            print("captions:", r.status_code, r.json())
            clock = {"session_id": sid, "timeline_epoch": 0, "video_id": "smokeTest01", "media_ms": 0, "monotonic_ms": 1,
                     "playback_rate": 1.0, "paused": False, "seeking": False, "stalled": False, "ad_state": "content",
                     "visibility": "visible"}
            await cli.post(f"/v1/sessions/{sid}/clock", headers=H, json=clock)
            ready, audio, first_audio_s = {}, {}, None
            pcm_by_seg: dict[str, bytearray] = {}
            while time.time() - tb < 120 and len(audio) < len(cues) - 1:
                try:
                    m = await asyncio.wait_for(ws.recv(), 15)
                except asyncio.TimeoutError:
                    break
                if isinstance(m, bytes):
                    h, pcm = unpack_frame(m)
                    pcm_by_seg.setdefault(h["segment_id"], bytearray()).extend(pcm)
                    if first_audio_s is None:
                        first_audio_s = time.time() - tb
                    continue
                e = json.loads(m)
                if e["event"] == "translation.ready":
                    ready[e["payload"]["segment_id"]] = e["payload"]
                    print(f"  [{time.time()-tb:5.2f}s] {e['payload']['start_ms']/1000:5.1f}s  EN: {e['payload']['source_text']}")
                    print(f"                    VI: {e['payload']['target_display']}   flags={e['payload']['flags']}")
                elif e["event"] == "translation.blocked":
                    print("  BLOCKED", e["payload"])
                elif e["event"] == "audio.end":
                    audio[e["payload"]["segment_id"]] = e["payload"]
                    print(f"  [{time.time()-tb:5.2f}s] audio.end {e['payload']['segment_id'][:10]} {e['payload']['duration_ms']} ms")
                elif e["event"] in ("error", "warning"):
                    print("  ", e["event"], e["payload"])
            print("first audio frame after", round(first_audio_s or -1, 2), "s; units ready", len(ready), "audio", len(audio))
            seg0 = next(iter(pcm_by_seg))
            out = HOME / "tmp" / "e2e_first_unit.wav"
            with wave.open(str(out), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000); w.writeframes(bytes(pcm_by_seg[seg0]))
            print("wrote", out, round(len(pcm_by_seg[seg0]) / 96000, 2), "s audio")
            # seek → epoch 1, audio re-delivered with epoch 1
            r = await cli.post(f"/v1/sessions/{sid}/control", headers=H, json={"op": "seek", "media_ms": 11900})
            ep = r.json()["timeline_epoch"]
            await cli.post(f"/v1/sessions/{sid}/clock", headers=H, json={**clock, "timeline_epoch": ep, "media_ms": 11900})
            got_stop, epochs = False, set()
            t1 = time.time()
            while time.time() - t1 < 10:
                m = await asyncio.wait_for(ws.recv(), 10)
                if isinstance(m, bytes):
                    epochs.add(unpack_frame(m)[0]["timeline_epoch"])
                    if ep in epochs:
                        break
                elif json.loads(m)["event"] == "audio.stop":
                    got_stop = True
            print("seek: new epoch", ep, "audio.stop seen", got_stop, "frame epochs", epochs)
            segs = (await cli.get(f"/v1/sessions/{sid}/segments", headers=H)).json()["segments"]
            print("segments:", [(s["start_ms"], s["status"], s["audio"]) for s in segs])
            await cli.delete(f"/v1/sessions/{sid}", headers=H)
        st2 = (await cli.get("/v1/status", headers=H)).json()
        print("after: runtime", json.dumps(st2["runtime"], ensure_ascii=False), "gpu", st2["gpu"])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
