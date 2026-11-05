"""ASR worker faster-whisper (docs/05 §4–§8; FR-008, FR-009). Chạy bằng python venv ASR (mượn Hermes, chỉ đọc).

Nhận PCM s16le mono 16 kHz kèm (seq, capture_monotonic_ms, source_media_ms, playback_rate). Không micro.
- VAD năng lượng; cửa sổ tối đa ~8 s tiếng nói, overlap ~1 s, endpoint im lặng ~500 ms.
- Local-agreement: chỉ commit các từ trùng khớp ở hai lần decode liên tiếp (hoặc khi gặp endpoint).
- Draft và commit tách riêng; không bao giờ đưa draft sang TTS (broker chỉ nhận asr.commit làm cue).
- Gap seq hoặc media nhảy → chốt phần cũ, bắt đầu cửa sổ mới (không nối hai đoạn như liên tục).
- Audio thô chỉ nằm RAM (ring ≤ 30 s), không ghi đĩa.
"""
from __future__ import annotations

import glob
import os
import queue
import re
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from vietdub.workers.ipc import WorkerIO, log  # noqa: E402

SR = 16000
FRAME = 480                   # 30 ms
MAX_WINDOW_S = 8.0
OVERLAP_S = 1.0
ENDPOINT_SILENCE_S = 0.5
DECODE_EVERY_S = 1.0
RING_MAX_S = 30.0
MIN_SPEECH_S = 0.3


def _norm(w: str) -> str:
    return re.sub(r"[^\w']", "", w.lower())


class AsrWorker:
    def __init__(self) -> None:
        self.io = WorkerIO()
        self.np = None
        self.model = None
        self.jobs: "queue.Queue[tuple[dict, bytes]]" = queue.Queue()
        self.cfg = {}
        self.reset_state(0)

    # ---------------- state ----------------
    def reset_state(self, epoch: int, session_id: str | None = None) -> None:
        self.epoch = epoch
        self.session_id = session_id
        self.buf = None                       # np.float32
        self.anchors: list[tuple[int, int, float]] = []   # (sample_offset, media_ms, rate)
        self.last_seq = None
        self.prev_media = None
        self.prev_dur_ms = 0.0
        self.rate = 1.0
        self.samples_since_decode = 0
        self.speech_seen = False
        self.trailing_silence = 0.0
        self.noise_floor = 0.003
        self.prev_words: list[tuple[str, float, float]] = []   # (word, t0, t1) giây tương đối buffer
        self.committed_text_tail = ""
        self.cue_n = 0
        self.last_commit_end_media = -1

    def media_at(self, offset: float) -> int:
        """offset giây trong buffer → media ms theo anchor từng đoạn (không một tỉ lệ cố định cho cả phiên)."""
        s = int(offset * SR)
        a = self.anchors[0]
        for anc in self.anchors:
            if anc[0] <= s:
                a = anc
            else:
                break
        return int(a[1] + (s - a[0]) / SR * 1000 * a[2])

    # ---------------- ops ----------------
    def op_load(self, h: dict) -> None:
        import numpy as np
        self.np = np
        import site
        for sp in site.getsitepackages():
            for d in glob.glob(os.path.join(sp, "nvidia", "*", "bin")):
                try:
                    os.add_dll_directory(d)
                except OSError:
                    pass
        from faster_whisper import WhisperModel
        t0 = time.time()
        device = h.get("device", "cpu")
        compute = h.get("compute_type", "int8")
        self.model = WhisperModel(h["model_dir"], device=device, compute_type=compute,
                                  cpu_threads=int(h.get("cpu_threads", 6)), num_workers=1)
        self.cfg = {"beam_size": int(h.get("beam_size", 1))}
        warm = self.np.zeros(SR, dtype=self.np.float32)
        list(self.model.transcribe(warm, language="en", beam_size=1)[0])
        self.io.send({"op": "load", "job_id": h.get("job_id"), "ok": True, "device": device, "compute_type": compute,
                      "load_ms": round((time.time() - t0) * 1000)})

    def op_reset(self, h: dict) -> None:
        self.reset_state(int(h.get("epoch", 0)), h.get("session_id"))
        self.io.send({"op": "reset", "job_id": h.get("job_id"), "ok": True, "epoch": self.epoch})

    def op_feed(self, h: dict, payload: bytes) -> None:
        np = self.np
        if self.model is None or h.get("epoch") != self.epoch or h.get("session_id") != self.session_id:
            return                               # dữ liệu epoch/phiên cũ: bỏ
        seq, media = int(h["seq"]), int(h["source_media_ms"])
        pcm = np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768.0
        if pcm.size == 0:
            return
        dur_ms = pcm.size / SR * 1000
        gap = self.last_seq is not None and seq != self.last_seq + 1
        rate = self.rate
        if not gap and self.prev_media is not None and self.prev_dur_ms:
            est = (media - self.prev_media) / self.prev_dur_ms   # tốc độ phát suy từ đồng hồ media nguồn
            if 0.2 <= est <= 4.5:
                rate = est
            else:
                gap = True                                        # media nhảy (seek/quảng cáo) → không nối liền
        hr = h.get("playback_rate")
        if isinstance(hr, (int, float)) and 0.25 <= hr <= 4:
            rate = float(hr)
        if gap:
            self.io.send({"op": "asr.status", "event": "gap", "epoch": self.epoch, "session_id": self.session_id,
                          "seq": seq, "expected_seq": (self.last_seq or 0) + 1})
            self.finalize(reason="gap")
            self.buf = None
            self.anchors = []
        self.last_seq = seq
        self.prev_media, self.prev_dur_ms, self.rate = media, dur_ms, rate
        if self.buf is None:
            self.buf = pcm
            self.anchors = [(0, media, rate)]
        else:
            self.anchors.append((self.buf.size, media, rate))
            self.buf = np.concatenate([self.buf, pcm])
        # VAD năng lượng
        frames = pcm[: pcm.size // FRAME * FRAME].reshape(-1, FRAME) if pcm.size >= FRAME else pcm.reshape(1, -1)
        rms = np.sqrt(np.mean(frames ** 2, axis=1))
        for r in rms:
            thr = max(0.008, self.noise_floor * 3.0)
            if r > thr:
                self.speech_seen = True
                self.trailing_silence = 0.0
            else:
                self.trailing_silence += FRAME / SR
                self.noise_floor = 0.95 * self.noise_floor + 0.05 * float(r)
        self.samples_since_decode += pcm.size
        # ring RAM giới hạn
        if self.buf.size > RING_MAX_S * SR:
            self.finalize(reason="ring")
        if not self.speech_seen:
            # chỉ giữ ~1 s im lặng gần nhất để không lỡ âm đầu
            keep = int(1.0 * SR)
            if self.buf.size > keep:
                self.drop_front(self.buf.size - keep)
            return
        dur = self.buf.size / SR
        if self.trailing_silence >= ENDPOINT_SILENCE_S and dur > MIN_SPEECH_S:
            self.finalize(reason="endpoint")
        elif dur >= MAX_WINDOW_S or self.samples_since_decode >= DECODE_EVERY_S * SR:
            # Backpressure: còn feed chờ trong hàng → gộp thêm audio thay vì decode trung gian (theo kịp realtime).
            if dur < MAX_WINDOW_S and self.jobs.qsize() > 0:
                return
            self.decode_partial()

    def drop_front(self, n: int) -> None:
        if n <= 0 or self.buf is None:
            return
        n = min(n, self.buf.size)
        m0 = self.media_at(n / SR)
        seg = self.anchors[0]
        for anc in self.anchors:
            if anc[0] <= n:
                seg = anc
        self.buf = self.buf[n:]
        new_anchors = [(s - n, m, r) for s, m, r in self.anchors if s - n > 0]
        self.anchors = [(0, m0, seg[2])] + new_anchors
        self.prev_words = [(w, a - n / SR, b - n / SR) for w, a, b in self.prev_words if b - n / SR > 0]

    def transcribe(self) -> list[tuple[str, float, float]]:
        if self.buf is None or self.buf.size < MIN_SPEECH_S * SR:
            return []
        segs, _info = self.model.transcribe(self.buf, language="en", task="transcribe", beam_size=self.cfg["beam_size"],
                                            word_timestamps=True, vad_filter=False, condition_on_previous_text=False,
                                            initial_prompt=self.committed_text_tail[-200:] or None,
                                            temperature=0.0)
        words: list[tuple[str, float, float]] = []
        for s in segs:
            if s.no_speech_prob > 0.6 and s.avg_logprob < -1.0:
                continue                         # im lặng/nhạc bị model đoán chữ
            if s.compression_ratio > 2.4:
                continue                         # lặp ảo giác
            for w in (s.words or []):
                t = w.word.strip()
                if t:
                    words.append((t, float(w.start), float(w.end)))
        return words

    def decode_partial(self) -> None:
        self.samples_since_decode = 0
        words = self.transcribe()
        dur = self.buf.size / SR if self.buf is not None else 0
        horizon = dur - OVERLAP_S
        # local agreement: prefix chung giữa 2 lần decode, kết thúc trước horizon
        n = 0
        for (a, _, _), (b, _, _) in zip(self.prev_words, words):
            if _norm(a) != _norm(b):
                break
            n += 1
        stable = [w for w in words[:n] if w[2] <= horizon]
        if dur >= MAX_WINDOW_S and not stable and words:
            stable = [w for w in words if w[2] <= horizon]   # cửa sổ đầy: chốt phần trước overlap
        if stable:
            self.commit(stable, endpoint=False)
            cut = stable[-1][2]
            self.drop_front(int(cut * SR))
            words = [(w, a - cut, b - cut) for w, a, b in words[len(stable):]]
        self.prev_words = words
        draft = " ".join(w for w, _, _ in words)
        if draft:
            self.io.send({"op": "asr.draft", "epoch": self.epoch, "session_id": self.session_id, "text": draft[:2000],
                          "start_media_ms": self.media_at(words[0][1]), "end_media_ms": self.media_at(words[-1][2])})

    def finalize(self, reason: str) -> None:
        if self.buf is not None and self.speech_seen:
            words = self.transcribe()
            if words:
                self.commit(words, endpoint=True)
        self.buf = None
        self.anchors = []
        self.prev_words = []
        self.speech_seen = False
        self.trailing_silence = 0.0
        self.samples_since_decode = 0
        self.io.send({"op": "asr.draft", "epoch": self.epoch, "session_id": self.session_id, "text": "",
                      "start_media_ms": 0, "end_media_ms": 0, "reason": reason})

    def commit(self, words: list[tuple[str, float, float]], endpoint: bool) -> None:
        text = " ".join(w for w, _, _ in words).strip()
        if not text:
            return
        start = self.media_at(words[0][1])
        end = max(start, self.media_at(words[-1][2]))
        if end <= self.last_commit_end_media:
            return                               # chống phát hai lần cùng lời nói ở hai cửa sổ
        start = max(start, self.last_commit_end_media + 1)
        self.last_commit_end_media = end
        self.cue_n += 1
        self.committed_text_tail = (self.committed_text_tail + " " + text)[-400:]
        self.io.send({"op": "asr.commit", "epoch": self.epoch, "session_id": self.session_id,
                      "cue_id": f"asr-{self.epoch}-{self.cue_n}", "text": text[:4000], "start_media_ms": start,
                      "end_media_ms": end, "endpoint": endpoint})

    def op_flush(self, h: dict) -> None:
        if h.get("epoch") == self.epoch:
            self.finalize(reason="flush")
        self.io.send({"op": "flush", "job_id": h.get("job_id"), "ok": True})

    # ---------------- loop ----------------
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
                self.io.send({"op": "cancel", "job_id": h.get("job_id"), "ok": True})
                continue
            self.jobs.put((h, p))

    def run(self) -> None:
        threading.Thread(target=self.reader, daemon=True).start()
        self.io.send({"op": "hello", "worker": "asr", "pid": os.getpid()})
        while True:
            h, p = self.jobs.get()
            op = h.get("op")
            try:
                if op == "shutdown":
                    self.io.send({"op": "shutdown", "job_id": h.get("job_id"), "ok": True})
                    return
                if op == "load":
                    self.op_load(h)
                elif op == "reset":
                    self.op_reset(h)
                elif op == "feed":
                    self.op_feed(h, p)
                elif op == "flush":
                    self.op_flush(h)
                elif op == "health":
                    self.io.send({"op": "health", "job_id": h.get("job_id"), "ok": True, "loaded": self.model is not None,
                                  "buffer_s": round((self.buf.size / SR) if self.buf is not None else 0, 2)})
                elif op == "unload":
                    self.model = None
                    self.io.send({"op": "unload", "job_id": h.get("job_id"), "ok": True})
                else:
                    self.io.send({"op": op, "job_id": h.get("job_id"), "ok": False, "error": "VALIDATION_FAILED"})
            except BaseException as e:  # noqa: BLE001
                log("error: " + "".join(traceback.format_exception_only(type(e), e)).strip()[:300])
                if h.get("job_id"):
                    self.io.send({"op": op, "job_id": h.get("job_id"), "ok": False, "error": "WORKER_CRASHED"})


if __name__ == "__main__":
    AsrWorker().run()
