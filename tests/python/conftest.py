import asyncio
import json
import math
import struct

import pytest
from fastapi.testclient import TestClient

from vietdub.broker.app import Ctx, create_app
from vietdub.broker.events import Hub
from vietdub.broker.security import TokenStore
from vietdub.errors import AppError
from vietdub.paths import AppPaths
from vietdub.storage.audio_cache import AudioCache
from vietdub.storage.db import Database
from vietdub.translation.llm import LlmResult
from vietdub.translation.service import ModelFingerprint

EXT_ID = "abcdefghijklmnopabcdefghijklmnop"
ORIGIN = f"chrome-extension://{EXT_ID}"
PORT = 8765


class FakeRuntime:
    """Runtime giả cho test wiring (KHÔNG phải bằng chứng AI chạy thật)."""

    def __init__(self):
        self.calls = 0
        self.synth_calls = []
        self.fail_next_tts: list[str] = []
        self.voices = [{"voice_id": "Minh Quân Pro", "label": "Minh Quân Pro"}, {"voice_id": "Mai Anh", "label": "Mai Anh"}]
        self.voice_aliases = {"Minh Quân": "Minh Quân Pro"}
        self.tts_info = {"sdk_version": "3.8.1", "model_revision": "rev", "backend": "fake"}
        self.translation_state = "ready"
        self.tts_state = "ready"
        self.asr_state = "stopped"
        self.verified = {}
        self.asr_consumer = None
        self.asr_fed = []
        self.slow = 0.0
        from vietdub.models.manager import load_catalog

        class _MM:
            catalog = load_catalog()
            jobs = {}

            def status(self, mid, **kw):
                return {"model_id": mid, "state": "not_downloaded"}
        self.models = _MM()

        class _L:
            model_id = "qwen35_4b_q5"
            ctx = 4096
        self.llama = _L()

        class _R:
            llama_build = "fake"
            llama_server = None
            tts_python = None
            asr_python = None
            source = {}
        self.rts = _R()

    def translation_ready(self):
        return self.translation_state == "ready"

    def fingerprint(self):
        return ModelFingerprint("qwen35_4b_q5", "qwen35_4b_q5", "f" * 64, "fake", {"temperature": 0.7})

    async def chat(self, payload):
        self.calls += 1
        if self.slow:
            await asyncio.sleep(self.slow)
        user = json.loads(payload["messages"][1]["content"])
        out = [{"segment_id": s["segment_id"], "target_text": "VI: " + s["source_text"]} for s in user["segments"]]
        return LlmResult(json.dumps({"translations": out}, ensure_ascii=False), "stop", False, None, 5.0)

    def tts_ready(self):
        return self.tts_state == "ready"

    def resolve_voice(self, v):
        ids = {x["voice_id"] for x in self.voices}
        return v if v in ids else (self.voice_aliases.get(v) if self.voice_aliases.get(v) in ids else None)

    async def synth(self, text, voice, watermark=True):
        if self.fail_next_tts:
            raise AppError(self.fail_next_tts.pop(0))
        if not self.resolve_voice(voice):                     # như runtime thật: không tự đổi giọng
            raise AppError("VOICE_NOT_FOUND", {"voice_id": voice[:60]})
        self.synth_calls.append((text, voice))
        n = 48000 * max(1, min(4, len(text) // 20)) // 2
        pcm = b"".join(struct.pack("<h", int(8000 * math.sin(i / 20))) for i in range(n))
        return pcm, {"sample_rate": 48000, "samples": n}

    def synth_stream(self, text, voice):
        raise NotImplementedError

    def voice_fingerprint(self, voice):
        return "vfp-" + (self.resolve_voice(voice) or voice)

    def tts_versions(self):
        return "3.8.1", "rev"

    async def asr_reset(self, session_id, epoch):
        pass

    async def asr_feed(self, header, pcm):
        self.asr_fed.append(header)

    async def asr_flush(self, epoch):
        pass

    async def start_asr(self):
        self.asr_state = "ready"

    async def tts_cancel_all(self):
        pass

    def on_tts_failure(self, code):
        return "stop" if code == "GPU_OOM" and len(self.fail_next_tts) == 0 else "retry"

    def model_states(self):
        return {}

    async def verify_models(self, ids=None):
        return {i: False for i in (ids or [])}

    async def health(self):
        return {"translation": {"state": self.translation_state}, "tts": {"state": self.tts_state}, "asr": {"state": self.asr_state}}

    async def shutdown(self):
        pass


@pytest.fixture
def ctx(tmp_path):
    paths = AppPaths(tmp_path).ensure()
    db = Database(paths.db_file, paths.backups)
    cache = AudioCache(paths.audio_cache, db)
    rt = FakeRuntime()
    c = Ctx(paths=paths, db=db, cache=cache, rt=rt, hub=Hub(), tokens=TokenStore({EXT_ID}), port=PORT)  # type: ignore[arg-type]
    yield c
    db.close()


@pytest.fixture
def client(ctx):
    app = create_app(ctx)
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as cl:
        yield cl


@pytest.fixture
def token(ctx):
    tok, _ = ctx.tokens.issue(ctx.tokens.pairing_secret, ORIGIN)
    return tok


def H(token):
    return {"Authorization": f"Bearer {token}", "Origin": ORIGIN}
