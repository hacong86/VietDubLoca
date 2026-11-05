"""VieNeu v3 Turbo worker (docs/07). Chạy bằng python của venv TTS (mượn venv Hermes, chỉ đọc).

Chỉ import: thư viện chuẩn, numpy, vieneu (+ torch gián tiếp). Không gọi cloud: HF_HUB_OFFLINE=1.
Lệnh: load, list_voices, infer, infer_batch, infer_stream, cancel, health, unload, shutdown.
Output PCM: s16le mono, sample_rate lấy từ engine (Turbo = 48000), clamp [-1,1], reject NaN/Inf/rỗng/im lặng.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from vietdub.workers.ipc import WorkerIO, log  # noqa: E402

MAX_TEXT = 2000
STREAM_FRAME_SAMPLES = 24000   # 0,5 s ở 48 kHz → frame < 256 KiB


class TtsWorker:
    def __init__(self) -> None:
        self.io = WorkerIO()
        self.engine = None
        self.np = None
        self.cancelled: set[str] = set()
        self.jobs: "queue.Queue[tuple[dict, bytes]]" = queue.Queue()
        self.backend = None
        self.device = None
        self.sdk_version = None
        self.model_revision = None
        self.oom_count = 0

    # ---------- helpers ----------
    def reply(self, h: dict, **kw) -> None:
        self.io.send({"op": h.get("op"), "job_id": h.get("job_id"), **kw})

    def to_pcm(self, audio) -> bytes:
        np = self.np
        a = np.asarray(audio, dtype=np.float32).reshape(-1)
        if a.size == 0:
            raise ValueError("TTS_INVALID_AUDIO:empty")
        if not np.all(np.isfinite(a)):
            raise ValueError("TTS_INVALID_AUDIO:nan")
        if float(np.max(np.abs(a))) < 1e-4:
            raise ValueError("TTS_INVALID_AUDIO:silent")
        a = np.clip(a, -1.0, 1.0)
        return np.round(a * 32767.0).astype("<i2").tobytes()

    def is_oom(self, e: BaseException) -> bool:
        s = f"{type(e).__name__} {e}".lower()
        return "out of memory" in s or "outofmemory" in s or "cuda error: out of memory" in s

    def free_gpu(self) -> None:
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def err(self, h: dict, e: BaseException) -> None:
        msg = str(e)
        if self.is_oom(e):
            code = "GPU_OOM"
            self.oom_count += 1
            self.free_gpu()
        elif msg.startswith("TTS_INVALID_AUDIO"):
            code = "TTS_INVALID_AUDIO"
        elif msg.startswith("VOICE_NOT_FOUND"):
            code = "VOICE_NOT_FOUND"
        elif msg.startswith("MODEL_NOT_READY"):
            code = "MODEL_NOT_READY"
        else:
            code = "WORKER_CRASHED"
            log("error: " + "".join(traceback.format_exception_only(type(e), e)).strip()[:300])
        self.reply(h, ok=False, error=code)

    def voice(self, name: str | None) -> str:
        if self.engine is None:
            raise RuntimeError("MODEL_NOT_READY")
        vid = self.engine.resolve_voice_name(name) if name else None
        if not vid:
            raise ValueError(f"VOICE_NOT_FOUND:{name}")
        return vid

    def synth(self, text: str, vid: str, batch: int, wm: bool):
        try:
            return self.engine.infer(text, voice=vid, batch_size=batch, apply_watermark=wm)
        except Exception as e:  # watermark lib có thể thiếu trên máy → tắt watermark, báo trong result
            if wm and ("watermark" in str(e).lower() or "perth" in str(e).lower()):
                return self.engine.infer(text, voice=vid, batch_size=batch, apply_watermark=False)
            raise

    # ---------- ops ----------
    def op_load(self, h: dict) -> None:
        t0 = time.time()
        import numpy as np
        self.np = np
        from vieneu import Vieneu
        try:
            import importlib.metadata as md
            self.sdk_version = md.version("vieneu")
        except Exception:
            self.sdk_version = "unknown"
        device = h.get("device", "auto")
        backend = "onnx" if device == "cpu" else "auto"
        self.engine = Vieneu(mode="v3turbo", device=device, backend=backend,
                             max_batch_size=int(h.get("max_batch_size", 2)), max_streams=int(h.get("max_streams", 1)))
        self.backend = getattr(self.engine, "backend", "?")
        self.device = "cuda" if self.backend == "pytorch" else "cpu"
        self.model_revision = self._revision()
        load_ms = (time.time() - t0) * 1000
        warm_ms = None
        if h.get("warmup", True):
            t1 = time.time()
            vid = self.voice(h.get("warmup_voice")) if h.get("warmup_voice") else self.engine.list_preset_voices()[0][1]
            for txt in ("Xin chào, đây là câu thử giọng.", "Mở Unity rồi bấm Play."):
                self.engine.infer(txt, voice=vid, apply_watermark=False)
            warm_ms = (time.time() - t1) * 1000
        self.reply(h, ok=True, backend=self.backend, device=self.device, sample_rate=self.engine.sample_rate,
                   sdk_version=self.sdk_version, model_revision=self.model_revision,
                   load_ms=round(load_ms), warmup_ms=round(warm_ms) if warm_ms else None)

    def _revision(self) -> str | None:
        try:
            hub = os.path.join(os.environ.get("HF_HOME", ""), "hub", "models--pnnbao-ump--VieNeu-TTS-v3-Turbo", "refs", "main")
            with open(hub, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return None

    def op_list_voices(self, h: dict) -> None:
        if self.engine is None:
            raise RuntimeError("MODEL_NOT_READY")
        voices = [{"voice_id": vid, "label": label} for label, vid in self.engine.list_preset_voices()]
        aliases = dict(getattr(self.engine, "_voice_aliases", {}) or {})
        self.reply(h, ok=True, voices=voices, aliases=aliases)

    def op_infer(self, h: dict) -> None:
        jid = h["job_id"]
        if jid in self.cancelled:
            self.cancelled.discard(jid)
            self.reply(h, ok=False, error="CANCELLED")
            return
        text = str(h.get("text", ""))[:MAX_TEXT]
        vid = self.voice(h.get("voice"))
        t0 = time.time()
        audio = self.synth(text, vid, int(h.get("batch_size", 1)), bool(h.get("watermark", True)))
        pcm = self.to_pcm(audio)
        if jid in self.cancelled:
            self.cancelled.discard(jid)
            self.reply(h, ok=False, error="CANCELLED")
            return
        self.reply(h, ok=True, sample_rate=self.engine.sample_rate, samples=len(pcm) // 2, voice=vid,
                   infer_ms=round((time.time() - t0) * 1000), is_last=True, seq=0)
        # payload riêng để header không phình
        self.io.send({"op": "pcm", "job_id": jid, "seq": 0, "is_last": True}, pcm)

    def op_infer_batch(self, h: dict) -> None:
        jid = h["job_id"]
        texts = [str(t)[:MAX_TEXT] for t in h.get("texts", [])][:4]
        vid = self.voice(h.get("voice"))
        t0 = time.time()
        outs = self.engine.infer_batch(texts, voice=vid, batch_size=int(h.get("batch_size", 2)),
                                       apply_watermark=bool(h.get("watermark", True)))
        pcms = [self.to_pcm(a) for a in outs]
        self.reply(h, ok=True, sample_rate=self.engine.sample_rate, count=len(pcms),
                   samples=[len(p) // 2 for p in pcms], infer_ms=round((time.time() - t0) * 1000))
        for i, p in enumerate(pcms):
            self.io.send({"op": "pcm", "job_id": jid, "seq": i, "is_last": i == len(pcms) - 1, "index": i}, p)

    def op_infer_stream(self, h: dict) -> None:
        jid = h["job_id"]
        text = str(h.get("text", ""))[:MAX_TEXT]
        vid = self.voice(h.get("voice"))
        seq = 0
        t0 = time.time()
        first_ms = None
        np = self.np
        pending = []
        for chunk in self.engine.infer_stream(text, voice=vid, apply_watermark=bool(h.get("watermark", True))):
            if jid in self.cancelled:
                self.cancelled.discard(jid)
                self.reply(h, ok=False, error="CANCELLED")
                return
            a = np.asarray(chunk, dtype=np.float32).reshape(-1)
            if a.size == 0:
                continue
            if not np.all(np.isfinite(a)):
                raise ValueError("TTS_INVALID_AUDIO:nan")
            pending.append(a)
            buf = np.concatenate(pending)
            while buf.size >= STREAM_FRAME_SAMPLES:
                part, buf = buf[:STREAM_FRAME_SAMPLES], buf[STREAM_FRAME_SAMPLES:]
                if first_ms is None:
                    first_ms = (time.time() - t0) * 1000
                self.io.send({"op": "pcm", "job_id": jid, "seq": seq, "is_last": False},
                             np.round(np.clip(part, -1, 1) * 32767).astype("<i2").tobytes())
                seq += 1
            pending = [buf] if buf.size else []
        tail = np.concatenate(pending) if pending else np.zeros(0, dtype=np.float32)
        self.io.send({"op": "pcm", "job_id": jid, "seq": seq, "is_last": True},
                     np.round(np.clip(tail, -1, 1) * 32767).astype("<i2").tobytes())
        self.reply(h, ok=True, sample_rate=self.engine.sample_rate, frames=seq + 1,
                   first_chunk_ms=round(first_ms) if first_ms else None, total_ms=round((time.time() - t0) * 1000))

    def op_health(self, h: dict) -> None:
        info = {"ok": True, "loaded": self.engine is not None, "backend": self.backend, "device": self.device,
                "oom_count": self.oom_count, "sdk_version": self.sdk_version, "model_revision": self.model_revision}
        try:
            import torch
            if torch.cuda.is_available():
                info["vram_allocated_mb"] = round(torch.cuda.memory_allocated() / 2**20)
                info["vram_reserved_mb"] = round(torch.cuda.memory_reserved() / 2**20)
        except Exception:
            pass
        self.reply(h, **info)

    def op_unload(self, h: dict) -> None:
        if self.engine is not None:
            try:
                self.engine.close()
            except Exception:
                pass
        self.engine = None
        self.free_gpu()
        self.reply(h, ok=True)

    # ---------- loop ----------
    def reader(self) -> None:
        while True:
            try:
                h, p = self.io.recv()
            except EOFError:
                self.jobs.put(({"op": "shutdown"}, b""))
                return
            except Exception as e:
                log(f"bad frame: {e}")
                self.jobs.put(({"op": "shutdown"}, b""))
                return
            if h.get("op") == "cancel":
                for j in h.get("job_ids", []):
                    self.cancelled.add(str(j))
                self.reply(h, ok=True)
                continue
            self.jobs.put((h, p))

    def run(self) -> None:
        threading.Thread(target=self.reader, daemon=True).start()
        handlers = {"load": self.op_load, "list_voices": self.op_list_voices, "infer": self.op_infer,
                    "infer_batch": self.op_infer_batch, "infer_stream": self.op_infer_stream,
                    "health": self.op_health, "unload": self.op_unload}
        self.io.send({"op": "hello", "worker": "tts", "pid": os.getpid()})
        while True:
            h, _ = self.jobs.get()
            op = h.get("op")
            if op == "shutdown":
                self.reply(h, ok=True)
                return
            fn = handlers.get(op)
            if not fn:
                self.reply(h, ok=False, error="VALIDATION_FAILED")
                continue
            try:
                fn(h)
            except BaseException as e:  # noqa: BLE001 — mọi lỗi phải thành frame lỗi, không crash im lặng
                self.err(h, e)


if __name__ == "__main__":
    TtsWorker().run()
