"""Fresh install and interrupted setup wiring; real model manager, fake inference/network."""
import asyncio
import hashlib
from types import SimpleNamespace

import httpx
import pytest

from vietdub.broker.setup import BASE_MODELS, FirstRunSetup
from vietdub.errors import AppError
from vietdub.models.manager import ModelManager
from vietdub.paths import AppPaths


def make_setup(tmp_path, *, corrupt=False):
    paths = AppPaths(tmp_path).ensure()
    requests = []
    content = b'test model payload'

    def response(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=b'x' * len(content) if corrupt else content)

    mm = ModelManager(paths, transport=httpx.MockTransport(response))
    mm.catalog = {mid: {
        'id': mid, 'kind': 'translation' if mid == BASE_MODELS[0] else 'asr',
        'repo': 'test/model', 'revision': 'a' * 40, 'size_bytes': len(content), 'license': 'MIT',
        'files': [{'path': mid+'.bin', 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}],
    } for mid in (*BASE_MODELS, 'whisper_small_en')}

    class Runtime:
        models = mm
        verified = {}
        rts = SimpleNamespace(asr_python='python', tts_python='python', llama_server='llama')
        translation = False
        tts = False
        loaded = []
        fail_tts = False

        def translation_ready(self): return self.translation
        def tts_ready(self): return self.tts

        async def verify_models(self, ids):
            for mid in ids: self.verified[mid] = mm.verify_full(mid)
            return {mid: self.verified[mid] for mid in ids}

        async def activate_translation(self, mid):
            self.loaded.append(mid)
            self.translation = True

        async def start_tts(self, device):
            assert all(self.verified[mid] for mid in BASE_MODELS)
            if self.fail_tts: raise AppError('GPU_OOM')
            self.loaded.append('tts')
            self.tts = True

    rt = Runtime()
    ctx = SimpleNamespace(rt=rt, session=None, startup_task=None, settings=lambda: {'tts': {'device': 'auto'}})
    setup = FirstRunSetup(ctx)
    body = {'consent': True, 'accepted_sizes': {mid: len(content) for mid in BASE_MODELS}}
    return setup, body, rt, requests


@pytest.mark.asyncio
async def test_fresh_install_downloads_codec_then_loads_both_engines(tmp_path):
    setup, body, rt, requests = make_setup(tmp_path)
    setup.start(body)
    task = setup.task
    setup.start(body)
    assert setup.task is task
    await task
    assert setup.snapshot()['ready'] and setup.state == 'ready'
    assert len(requests) == 3 and rt.loaded == [BASE_MODELS[0], 'tts']
    setup.start(body)
    await setup.task
    assert len(requests) == 3  # subsequent setup reuses verified files


@pytest.mark.asyncio
async def test_exact_consent_required_before_any_download(tmp_path):
    setup, body, _, requests = make_setup(tmp_path)
    for bad in ({}, {**body, 'consent': False}, {**body, 'accepted_sizes': {}}):
        with pytest.raises(AppError, match='CONSENT_REQUIRED'): setup.start(bad)
    assert not requests and setup.task is None


@pytest.mark.asyncio
async def test_checksum_failure_never_loads_inference(tmp_path):
    setup, body, rt, _ = make_setup(tmp_path, corrupt=True)
    setup.start(body)
    await setup.task
    assert setup.state == 'failed' and setup.error == 'MODEL_CHECKSUM_MISMATCH'
    assert not rt.loaded


@pytest.mark.asyncio
async def test_pause_before_download_and_resume(tmp_path):
    setup, body, rt, requests = make_setup(tmp_path)
    setup.start(body)
    setup.pause()
    await setup.task
    assert setup.state == 'paused' and not requests
    setup.start(body)
    await setup.task
    assert setup.state == 'ready' and rt.tts


@pytest.mark.asyncio
async def test_failed_voice_load_can_retry_without_redownload(tmp_path):
    setup, body, rt, requests = make_setup(tmp_path)
    rt.fail_tts = True
    setup.start(body)
    await setup.task
    assert setup.error == 'GPU_OOM' and not setup.snapshot()['ready']
    rt.fail_tts = False
    setup.start(body)
    await setup.task
    assert setup.snapshot()['ready'] and len(requests) == 3


@pytest.mark.asyncio
async def test_asr_requires_installed_environment_and_separate_consent(tmp_path):
    setup, body, rt, _ = make_setup(tmp_path)
    rt.rts.asr_python = None
    with pytest.raises(AppError, match='MODEL_NOT_READY'): setup.start({**body, 'include_asr': True})
    rt.rts.asr_python = 'python'
    with pytest.raises(AppError, match='CONSENT_REQUIRED'): setup.start({**body, 'include_asr': True})
    body['include_asr'] = True
    body['accepted_sizes']['whisper_small_en'] = next(iter(body['accepted_sizes'].values()))
    setup.start(body)
    await setup.task
    assert rt.verified['whisper_small_en']


def test_setup_routes_require_auth(client):
    assert client.get('/v1/setup').status_code == 401
    assert client.post('/v1/setup', json={}).status_code == 401
    assert client.post('/v1/setup/pause', json={}).status_code == 401


@pytest.mark.asyncio
async def test_setup_waits_for_autoload_before_touching_models(tmp_path):
    setup, body, rt, requests = make_setup(tmp_path)
    gate = asyncio.Event()
    setup.ctx.startup_task = asyncio.create_task(gate.wait())
    setup.start(body)
    await asyncio.sleep(0)
    assert not requests and not rt.loaded
    gate.set()
    await setup.task
    assert setup.snapshot()['ready']


@pytest.mark.asyncio
async def test_missing_runtime_does_not_download_weights(tmp_path):
    setup, body, rt, requests = make_setup(tmp_path)
    rt.rts.tts_python = None
    setup.start(body)
    await setup.task
    assert setup.error == 'MODEL_NOT_READY' and not requests


def test_busy_setup_blocks_conflicting_model_and_session_actions(client, ctx, token):
    ctx.setup.task = SimpleNamespace(done=lambda: False)
    headers = {'Authorization': 'Bearer ' + token}
    for method, url in [('DELETE', '/v1/models/qwen35_4b_q5'), ('POST', '/v1/sessions')]:
        r = client.request(method, url, headers=headers)
        assert r.status_code != 200 and r.json()['code'] == 'MODEL_NOT_READY'
    assert client.get('/v1/setup', headers=headers).status_code == 200
