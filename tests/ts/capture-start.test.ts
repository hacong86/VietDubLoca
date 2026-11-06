import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const stubs = vi.hoisted(() => ({ api: vi.fn(), pairing: vi.fn() }));
vi.mock('../../apps/extension/src/shared/api', async (load) => ({
  ...await load<typeof import('../../apps/extension/src/shared/api')>(),
  api: stubs.api,
  getPairing: stubs.pairing,
}));

describe('starting tab audio capture', () => {
  let listener: (message: unknown, sender: unknown, reply: (result: any) => void) => void;
  let state: Record<string, any>;
  let calls: string[];
  let granted: boolean;
  let tabActive: boolean;
  let streamError: string | null;

  const invoke = () => new Promise<any>((resolve) => listener(
    { ns: 'vietdub', type: 'panel.capture_start', tab_id: 17 },
    { id: 'extension-id', url: 'chrome-extension://extension-id/sidepanel.html' }, resolve,
  ));

  beforeEach(async () => {
    vi.resetModules();
    calls = [];
    granted = true;
    tabActive = true;
    streamError = null;
    state = {
      active: { tab_id: 17, video_id: 'abcdefghijk', session_id: 'session-1', mode: 'vod_sync', capture: false },
      tabs: { 17: { title: 'Test', is_live: false, is_shorts: false } },
      offscreen_capture: true,
    };
    const event = () => ({ addListener: vi.fn() });
    vi.stubGlobal('chrome', {
      storage: { session: { setAccessLevel: vi.fn(), get: vi.fn(async (key: string) => ({ [key]: state[key] })),
        set: vi.fn(async (value: object) => Object.assign(state, value)), remove: vi.fn(), clear: vi.fn() } },
      sidePanel: { setPanelBehavior: vi.fn(async () => {}), open: vi.fn() },
      action: { onClicked: event(), setBadgeText: vi.fn(), setBadgeBackgroundColor: vi.fn(), setTitle: vi.fn() },
      commands: { onCommand: event() },
      tabs: { onRemoved: event(), onUpdated: event(), get: vi.fn(async () => ({ active: tabActive })), sendMessage: vi.fn(async () => {}) },
      permissions: { contains: vi.fn(async () => granted) },
      tabCapture: { getMediaStreamId: vi.fn(async () => { calls.push('stream-id'); if (streamError) throw new Error(streamError); return 'stream-id'; }) },
      runtime: { id: 'extension-id', ContextType: { OFFSCREEN_DOCUMENT: 'OFFSCREEN_DOCUMENT' }, getURL: (p: string) => `chrome-extension://extension-id/${p}`,
        getContexts: vi.fn(async () => [{}]), onMessage: { addListener: (fn: typeof listener) => { listener = fn; } }, onInstalled: event(), onStartup: event(),
        sendMessage: vi.fn(async (m: { type: string }) => {
          calls.push(m.type);
          if (m.type === 'offscreen.get_status') return { status: { connection: 'connected', session: { session_id: 'session-1' } } };
          return { ok: true };
        }) },
    });
    stubs.pairing.mockReset().mockResolvedValue({ broker_url: 'http://127.0.0.1:8765', session_token: 'test', expires_at: Date.now() / 1000 + 3600 });
    stubs.api.mockReset().mockImplementation(async (method: string, path: string, body?: { op: string }) => {
      if (path === '/v1/settings') return { value: {} };
      if (method === 'GET') return { timeline_epoch: 1 };
      calls.push(body?.op ?? 'post');
      return {};
    });
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true })));
    await import('../../apps/extension/src/background/index');
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it('prepares ASR before obtaining and immediately consuming the short-lived stream ID', async () => {
    expect(await invoke()).toEqual({ ok: true });
    expect(calls.indexOf('asr_start')).toBeLessThan(calls.indexOf('stream-id'));
    expect(calls[calls.indexOf('stream-id') + 1]).toBe('offscreen.capture_start');
    expect(state.active.capture).toBe(true);
  });

  it('does not start ASR if the user has not granted tab capture', async () => {
    granted = false;
    expect(await invoke()).toEqual({ ok: false, code: 'PERMISSION_DENIED' });
    expect(calls).not.toContain('asr_start');
  });

  it('explains missing ASR installation and does not request a stream', async () => {
    const { ApiError } = await import('../../apps/extension/src/shared/api');
    stubs.api.mockImplementation(async (method: string, path: string, body?: { op: string }) => {
      if (path === '/v1/settings') return { value: {} };
      if (method === 'GET') return { timeline_epoch: 1 };
      if (body?.op === 'asr_start') throw new ApiError('MODEL_NOT_READY', 'missing', 503, { reason: 'asr_runtime_missing' });
      return {};
    });
    expect(await invoke()).toMatchObject({ ok: false, code: 'ASR_NOT_INSTALLED' });
    expect(calls).not.toContain('stream-id');
    expect(state.active.capture).toBe(false);
  });

  it('explains when the ASR model has not been downloaded', async () => {
    const { ApiError } = await import('../../apps/extension/src/shared/api');
    stubs.api.mockImplementation(async (method: string, path: string, body?: { op: string }) => {
      if (path === '/v1/settings') return { value: {} };
      if (method === 'GET') return { timeline_epoch: 1 };
      if (body?.op === 'asr_start') throw new ApiError('MODEL_NOT_READY', 'missing', 503, { model_id: 'whisper_small_en' });
      return {};
    });
    expect(await invoke()).toMatchObject({ ok: false, code: 'ASR_MODEL_MISSING' });
    expect(calls).not.toContain('stream-id');
  });

  it('rejects a second request while ASR is loading', async () => {
    let unblock!: () => void;
    const wait = new Promise<void>(resolve => { unblock = resolve; });
    stubs.api.mockImplementation(async (method: string, path: string, body?: { op: string }) => {
      if (path === '/v1/settings') return { value: {} };
      if (method === 'GET') return { timeline_epoch: 1 };
      if (body?.op === 'asr_start') await wait;
      return {};
    });
    const first = invoke();
    expect(await invoke()).toEqual({ ok: false, code: 'CAPTURE_IN_PROGRESS' });
    unblock();
    expect(await first).toEqual({ ok: true });
  });

  it('stops ASR and restores the session mode when Chrome denies access to the tab', async () => {
    streamError = 'Extension has not been invoked for the current page';
    expect(await invoke()).toMatchObject({ ok: false, code: 'CAPTURE_TAB_NOT_ACTIVE' });
    expect(calls).toContain('offscreen.capture_stop');
    expect(calls).toContain('asr_stop');
    expect(calls).toContain('mode');
    expect(state.active.capture).toBe(false);
  });

  it('does not request a stream for an inactive tab', async () => {
    tabActive = false;
    expect(await invoke()).toMatchObject({ ok: false, code: 'CAPTURE_TAB_NOT_ACTIVE' });
    expect(calls).not.toContain('stream-id');
    expect(calls).toContain('asr_stop');
  });
});
