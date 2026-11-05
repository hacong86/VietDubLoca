/**
 * Service worker MV3 (ADR-004): điều phối quyền Chrome, Native Messaging, vòng đời offscreen, phiên active.
 * KHÔNG giữ hàng đợi audio. Trạng thái bền nằm ở chrome.storage.session (trusted contexts).
 */
import { NativeReply } from '../../../../packages/contracts/src';
import { api, ApiError, getPairing, type Pairing } from '../shared/api';
import { NS, TO_CONTENT_TYPES, isNs, type Mode, type OverlayPrefs, type ToContent } from '../shared/messages';

const HOST = 'com.vietdub.local';
// Nhật ký vòng (chẩn đoán, không payload) — đọc qua DevTools/harness: globalThis.__vdlog
const vdlog: string[] = [];
function dlog(...a: unknown[]): void {
  vdlog.push(`${new Date().toISOString().slice(11, 23)} ${a.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).join(' ')}`.slice(0, 300));
  if (vdlog.length > 200) vdlog.shift();
}
(globalThis as unknown as Record<string, unknown>).__vdlog = vdlog;
const YT = /^https:\/\/(www|m)\.youtube\.com\//;

interface TabInfo { video_id: string | null; title: string; is_live: boolean; is_shorts: boolean }
interface Active { tab_id: number; video_id: string; session_id: string; mode: Mode; capture: boolean; started_at: number }

// storage.session chỉ cho trusted contexts (mặc định) — content script không đọc được token.
void chrome.storage.session.setAccessLevel?.({ accessLevel: 'TRUSTED_CONTEXTS' });
void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false }).catch(() => undefined);

async function getActive(): Promise<Active | null> {
  return ((await chrome.storage.session.get('active')).active as Active | undefined) ?? null;
}
async function setActive(a: Active | null): Promise<void> {
  if (a) await chrome.storage.session.set({ active: a });
  else await chrome.storage.session.remove('active');
  await updateBadge(a);
}
async function tabInfo(tabId: number): Promise<TabInfo | null> {
  const t = ((await chrome.storage.session.get('tabs')).tabs ?? {}) as Record<string, TabInfo>;
  return t[String(tabId)] ?? null;
}
async function setTabInfo(tabId: number, info: TabInfo | null): Promise<void> {
  const t = ((await chrome.storage.session.get('tabs')).tabs ?? {}) as Record<string, TabInfo>;
  if (info) t[String(tabId)] = info;
  else delete t[String(tabId)];
  await chrome.storage.session.set({ tabs: t });
}

async function updateBadge(a: Active | null): Promise<void> {
  await chrome.action.setBadgeText({ text: a ? 'VI' : '' });
  await chrome.action.setBadgeBackgroundColor({ color: '#2e7d4f' });
  await chrome.action.setTitle({ title: a ? 'VietDub Local — đang thuyết minh' : 'VietDub Local' });
}

// ------------------------------------------------------------------ Native Messaging pairing (FR-003)
async function native(msg: Record<string, unknown>): Promise<NativeReply> {
  try {
    const r = await chrome.runtime.sendNativeMessage(HOST, msg);
    const p = NativeReply.safeParse(r);
    return p.success ? p.data : { type: 'error', code: 'PROTOCOL_MISMATCH' };
  } catch (e) {
    const m = String((e as Error).message ?? e);
    return { type: 'error', code: /not found|not registered|Specified native messaging host/i.test(m) ? 'NATIVE_HOST_MISSING' : 'CONNECT_FAILED' };
  }
}

async function pair(): Promise<{ ok: boolean; code?: string }> {
  const hello = await native({ type: 'hello', protocol_version: 1 });
  if (hello.type === 'error') return { ok: false, code: hello.code };
  if (hello.type === 'hello' && !hello.compatible) return { ok: false, code: 'PROTOCOL_MISMATCH' };
  const r = await native({ type: 'start' });
  if (r.type !== 'paired') return { ok: false, code: r.type === 'error' ? r.code : 'CONNECT_FAILED' };
  const p: Pairing = { broker_url: r.broker_url, session_token: r.session_token, expires_at: r.expires_at };
  await chrome.storage.session.set({ pairing: p });
  return { ok: true };
}

async function ensurePaired(): Promise<Pairing> {
  let p = await getPairing();
  if (p) {
    try {
      const r = await fetch(p.broker_url + '/health', { cache: 'no-store' });
      if (r.ok) return p;
    } catch {
      /* broker có thể đã khởi động lại với port/token mới */
    }
  }
  const res = await pair();
  if (!res.ok) throw new ApiError(res.code ?? 'CONNECT_FAILED', 'Không kết nối được chương trình trên máy.', 0);
  p = await getPairing();
  if (!p) throw new ApiError('AUTH_REQUIRED', 'Cần ghép nối lại.', 401);
  return p;
}

// ------------------------------------------------------------------ offscreen (docs/06 §9)
/** Tuần tự hóa mọi thao tác tạo/đóng offscreen (Codex #5). */
let offscreenLock: Promise<unknown> = Promise.resolve();
function serial<T>(fn: () => Promise<T>): Promise<T> {
  const run = offscreenLock.then(fn, fn);
  offscreenLock = run.catch(() => undefined);
  return run;
}

async function ensureOffscreen(withCapture = false): Promise<void> {
  await serial(async () => {
    const url = chrome.runtime.getURL('offscreen.html');
    const ctxs = await chrome.runtime.getContexts({ contextTypes: [chrome.runtime.ContextType.OFFSCREEN_DOCUMENT], documentUrls: [url] });
    const hasCapture = (await chrome.storage.session.get('offscreen_capture')).offscreen_capture === true;
    if (ctxs.length > 0 && (!withCapture || hasCapture)) return;
    if (ctxs.length > 0) await chrome.offscreen.closeDocument();        // cần thêm USER_MEDIA: tạo lại
    // USER_MEDIA chỉ khi thực sự thu âm tab (docs/06 §9)
    const reasons = withCapture ? [chrome.offscreen.Reason.AUDIO_PLAYBACK, chrome.offscreen.Reason.USER_MEDIA] : [chrome.offscreen.Reason.AUDIO_PLAYBACK];
    await chrome.offscreen.createDocument({ url: 'offscreen.html', reasons, justification: 'Phát thuyết minh tiếng Việt và thu âm tab do người dùng yêu cầu' });
    await chrome.storage.session.set({ offscreen_capture: withCapture });
  });
}

/** Chờ script offscreen đăng ký xong listener (module lớn) rồi mới gửi lệnh — tránh mất 'offscreen.start'. */
async function offscreenReady(timeoutMs = 5000): Promise<boolean> {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const r = await sendOffscreen<{ status?: unknown }>({ type: 'offscreen.get_status' });
    if (r && r.status !== undefined) return true;
    await new Promise((res) => setTimeout(res, 100));
  }
  return false;
}

/** Handshake đủ: offscreen nhận cấu hình VÀ WS đã auth + subscribe đúng phiên (Codex #4). */
async function startOffscreen(cfg: Record<string, unknown>, timeoutMs = 8000): Promise<boolean> {
  const sid = cfg.session_id as string;
  const t0 = Date.now();
  let started = false;
  while (Date.now() - t0 < timeoutMs) {
    if (!started) {
      await offscreenReady(2000);
      const r = await sendOffscreen<{ ok: boolean }>({ type: 'offscreen.start', cfg });
      started = !!r?.ok;
    } else {
      const st = await sendOffscreen<{ status?: { connection: string; session?: { session_id: string } | null } }>({ type: 'offscreen.get_status' });
      if (!st?.status) started = false;                  // document vừa bị đóng/tạo lại
      else if (st.status.connection === 'connected' && st.status.session?.session_id === sid) return true;
    }
    await new Promise((res) => setTimeout(res, 150));
  }
  dlog('startOffscreen timeout', sid.slice(0, 10), started);
  return false;
}

async function sendOffscreen<T = unknown>(msg: Record<string, unknown>): Promise<T | undefined> {
  try {
    return (await chrome.runtime.sendMessage({ ns: NS, ...msg })) as T;
  } catch {
    return undefined;
  }
}

async function toTab(tabId: number, msg: ToContent): Promise<void> {
  try {
    await chrome.tabs.sendMessage(tabId, msg);
  } catch (e) {
    dlog('toTab failed', msg.type, String((e as Error).message ?? e).slice(0, 120));
  }
}

// ------------------------------------------------------------------ phiên (FR-021, FR-030, FR-031)
async function loadEngineSettings() {
  const s = await api<{ value: Record<string, Record<string, unknown>> }>('GET', '/v1/settings');
  const pb = s.value.playback ?? {};
  return {
    settings: {
      vietnamese_gain: Number(pb.vietnamese_gain ?? 1), original_gain: Number(pb.original_gain ?? 0.15),
      auto_hold_vod: pb.auto_hold_vod !== false, residual_stretch_max: Number(pb.residual_stretch_max ?? 1.25),
      preload_enabled: pb.preload_enabled !== false, preload_target_ms: Math.min(Math.round(Number(pb.preload_target_s ?? 30) * 1000), Number(pb.prefetch_target_ms ?? 30000)),   // không vượt vùng broker tạo giọng trước
      seek_mid_sentence: (pb.seek_mid_sentence === 'skip_current' ? 'skip_current' : 'replay_prompt') as 'replay_prompt' | 'skip_current',
    },
    prefs: { subtitle_mode: (pb.subtitle_mode ?? 'bilingual') as OverlayPrefs['subtitle_mode'], subtitle_size: Number(pb.subtitle_size ?? 22),
      subtitle_position: (pb.subtitle_position ?? 'bottom') as OverlayPrefs['subtitle_position'] },
    mode: (pb.mode ?? 'vod_sync') as Mode,
  };
}

async function offscreenCfg(a: Active, epoch: number, mode: Mode) {
  const p = await ensurePaired();
  const es = await loadEngineSettings();
  const info = await tabInfo(a.tab_id);
  return { es, cfg: { broker_url: p.broker_url, token: p.session_token, session_id: a.session_id, epoch, tab_id: a.tab_id, video_id: a.video_id,
    title: info?.title ?? '', mode, settings: es.settings, prefs: es.prefs, is_live: !!info?.is_live, is_shorts: !!info?.is_shorts } };
}

async function startSession(tabId: number, modeOverride?: Mode): Promise<{ ok: boolean; code?: string; message?: string }> {
  const info = await tabInfo(tabId);
  if (!info?.video_id) return { ok: false, code: 'SOURCE_UNAVAILABLE', message: 'Tab này chưa mở video YouTube.' };
  let created: Active | null = null;
  try {
    await ensurePaired();
    const prev = await getActive();
    if (prev) await stopSession(prev.tab_id !== tabId ? 'switched_tab' : 'restart');   // một tab chủ động; giải phóng trước
    const es = await loadEngineSettings();
    const mode: Mode = modeOverride ?? (info.is_live ? 'live_delayed' : es.mode);
    const s = await api<{ session_id: string; timeline_epoch: number; mode: Mode }>('POST', '/v1/sessions', {
      video_id: info.video_id, tab_id: tabId, mode, source_language: 'en', target_language: 'vi', title: info.title,
      request_id: crypto.randomUUID(),
    });
    created = { tab_id: tabId, video_id: info.video_id, session_id: s.session_id, mode: s.mode, capture: false, started_at: Date.now() };
    await setActive(created);
    await ensureOffscreen(false);
    const { cfg } = await offscreenCfg(created, s.timeline_epoch, s.mode);
    if (!(await startOffscreen({ ...cfg, preload: true }))) throw new ApiError('WORKER_CRASHED', 'Không khởi động được bộ phát âm thanh của tiện ích.', 0);
    if ((await getActive())?.session_id !== s.session_id) return { ok: false, code: 'SESSION_CONFLICT' };
    await toTab(tabId, { ns: NS, type: 'session.started', mode: s.mode, prefs: es.prefs, capture: false, original_gain: es.settings.original_gain });
    await toTab(tabId, { ns: NS, type: 'captions.fetch' });
    return { ok: true };
  } catch (e) {
    const err = e instanceof ApiError ? e : new ApiError('CONNECT_FAILED', 'Không kết nối được chương trình trên máy.', 0);
    dlog('startSession failed', err.code);
    if (created && (await getActive())?.session_id === created.session_id) await stopSession('start_failed');   // hoàn tác (Codex #4)
    return { ok: false, code: err.code, message: err.messageVi };
  }
}

async function stopSession(reason: string): Promise<void> {
  const a = await getActive();
  dlog('stopSession', reason, !!a);
  await setActive(null);
  await sendOffscreen({ type: 'offscreen.stop', reason });
  if (a) {
    await toTab(a.tab_id, { ns: NS, type: 'session.stopped', reason });
    try {
      await api('DELETE', `/v1/sessions/${a.session_id}`);
    } catch {
      /* broker đã tắt */
    }
  }
}

async function toggle(tabId: number): Promise<{ ok: boolean; code?: string; message?: string }> {
  const a = await getActive();
  if (a && a.tab_id === tabId) {
    await stopSession('user_toggle');
    return { ok: true };
  }
  return startSession(tabId);
}

async function startCapture(tabId: number): Promise<{ ok: boolean; code?: string }> {
  let a = await getActive();
  if (!a || a.tab_id !== tabId) {
    const r = await startSession(tabId, 'live_delayed');
    if (!r.ok) return r;
    a = await getActive();
  }
  if (!a) return { ok: false, code: 'CONNECT_FAILED' };
  const granted = await chrome.permissions.contains({ permissions: ['tabCapture'] });
  if (!granted) return { ok: false, code: 'PERMISSION_DENIED' };
  let streamId: string;
  try {
    streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
  } catch {
    return { ok: false, code: 'PERMISSION_DENIED' };
  }
  const sid = a.session_id;
  try {
    await ensureOffscreen(true);                                   // cần USER_MEDIA
    const snap = await api<{ timeline_epoch: number }>('GET', `/v1/sessions/${sid}`);
    const { cfg, es } = await offscreenCfg(a, snap.timeline_epoch, 'live_delayed');
    if (!(await startOffscreen(cfg))) throw new ApiError('WORKER_CRASHED', '', 0);
    await api('POST', `/v1/sessions/${sid}/control`, { op: 'asr_start' });
    await sendOffscreen({ type: 'offscreen.mode', mode: 'live_delayed' });
    const r = await sendOffscreen<{ ok: boolean; code?: string }>({ type: 'offscreen.capture_start', stream_id: streamId });
    if (!r?.ok) throw new ApiError(r?.code ?? 'PERMISSION_DENIED', '', 0);
    if ((await getActive())?.session_id !== sid) return { ok: false, code: 'SESSION_CONFLICT' };
    // chỉ commit trạng thái khi MỌI bước thành công (Codex #6)
    await setActive({ ...a, mode: 'live_delayed', capture: true });
    await toTab(tabId, { ns: NS, type: 'session.started', mode: 'live_delayed', prefs: es.prefs, capture: true, original_gain: es.settings.original_gain });
    return { ok: true };
  } catch (e) {
    const code = e instanceof ApiError ? e.code : 'CONNECT_FAILED';
    dlog('startCapture failed', code);
    await sendOffscreen({ type: 'offscreen.capture_stop' });
    try {
      await api('POST', `/v1/sessions/${sid}/control`, { op: 'asr_stop' });
    } catch {
      /* bỏ qua */
    }
    return { ok: false, code };
  }
}

let rehydrating: { sid: string; p: Promise<void> } | null = null;
/** Offscreen AUDIO_PLAYBACK tự đóng sau ~30 s im lặng: dựng lại khi phiên còn (một lần/phiên, không chồng). */
async function ensureSessionOffscreen(a: Active): Promise<void> {
  const ctxs = await chrome.runtime.getContexts({ contextTypes: [chrome.runtime.ContextType.OFFSCREEN_DOCUMENT] });
  if (ctxs.length > 0) {
    const st = await sendOffscreen<{ status?: { video?: unknown } }>({ type: 'offscreen.get_status' });
    if (st?.status?.video) return;                              // offscreen đang giữ cấu hình phiên
  }
  if (!rehydrating || rehydrating.sid !== a.session_id) {
    const p = rehydrate(a).finally(() => { if (rehydrating?.p === p) rehydrating = null; });
    rehydrating = { sid: a.session_id, p };
  }
  await rehydrating.p;
}

async function rehydrate(a: Active): Promise<void> {
  for (let attempt = 0; attempt < 3; attempt++) {
    if ((await getActive())?.session_id !== a.session_id) return;       // phiên đã đổi: không đè (Codex #5)
    let snap: { timeline_epoch: number; mode: Mode } | null = null;
    try {
      snap = await api('GET', `/v1/sessions/${a.session_id}`);
    } catch (e) {
      if (e instanceof ApiError && e.code === 'NOT_FOUND') {
        // broker xác nhận phiên đã kết thúc → mới được xóa (Codex #2)
        if ((await getActive())?.session_id === a.session_id) {
          await setActive(null);
          await toTab(a.tab_id, { ns: NS, type: 'session.stopped', reason: 'session_gone' });
        }
        return;
      }
      dlog('rehydrate transient', attempt, e instanceof ApiError ? e.code : String(e));
    }
    if (snap) {
      try {
        await ensureOffscreen(a.capture);
        const { cfg } = await offscreenCfg(a, snap.timeline_epoch, snap.mode);
        if (await startOffscreen(cfg)) return;
      } catch (e) {
        dlog('rehydrate error', attempt, e instanceof ApiError ? e.code : String(e));
      }
    }
    await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
  }
  dlog('rehydrate gave up', a.session_id.slice(0, 10));
  await toTab(a.tab_id, { ns: NS, type: 'overlay.status', text: 'Mất kết nối bộ phát — mở bảng bên và bấm Bật tiếng Việt lại.', level: 'error' });
}

/** Lệnh content quan trọng: bảo đảm offscreen có phiên rồi chuyển tiếp, có ack; thử lại 1 lần (Codex #3). */
async function forwardToOffscreen(a: Active, msg: Record<string, unknown>): Promise<boolean> {
  for (let i = 0; i < 2; i++) {
    await ensureSessionOffscreen(a);
    const r = await sendOffscreen<{ ok: boolean }>({ type: 'offscreen.fwd', tab_id: a.tab_id, msg });
    if (r?.ok) return true;
  }
  dlog('forward failed', String(msg.type));
  return false;
}

// ------------------------------------------------------------------ sự kiện Chrome
chrome.action.onClicked.addListener(async (tab) => {
  if (tab.id === undefined) return;
  await chrome.sidePanel.open({ tabId: tab.id });   // mở bảng bên; thao tác này cũng "gọi" extension trên tab (tabCapture hợp lệ)
});

chrome.commands.onCommand.addListener(async (cmd, tab) => {
  const tabId = tab?.id ?? (await chrome.tabs.query({ active: true, currentWindow: true }))[0]?.id;
  if (tabId === undefined) return;
  if (cmd === 'toggle-narration') await toggle(tabId);
  else if (cmd === 'replay-sentence') {
    const st = await sendOffscreen<{ status: { replay_prompt?: { segment_id: string } | null; now_segment?: string | null } }>({ type: 'offscreen.get_status' });
    const seg = st?.status.replay_prompt?.segment_id;
    if (seg) await sendOffscreen({ type: 'offscreen.replay', segment_id: seg });
  } else if (cmd === 'capture-tab') {
    const r = await startCapture(tabId);
    if (!r.ok) await toTab(tabId, { ns: NS, type: 'overlay.status', text: 'Không thu được âm thanh tab — mở bảng bên để xem hướng dẫn.', level: 'error' });
  }
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  await setTabInfo(tabId, null);
  const a = await getActive();
  if (a?.tab_id === tabId) await stopSession('tab_closed');
});

chrome.tabs.onUpdated.addListener(async (tabId, change) => {
  if (change.url && !YT.test(change.url)) {
    const a = await getActive();
    if (a?.tab_id === tabId) await stopSession('left_youtube');
  }
});

chrome.runtime.onMessage.addListener((msg: unknown, sender, sendResponse) => {
  if (!isNs(msg) || sender.id !== chrome.runtime.id) return;
  const m = msg as Record<string, unknown> & { type: string };
  // Trang extension (side panel, options — kể cả khi mở dạng tab, offscreen) có URL thuộc origin extension.
  const fromExtensionPage = !!sender.url && sender.url.startsWith(chrome.runtime.getURL(''));
  const tabId = fromExtensionPage ? undefined : sender.tab?.id;
  if (m.type !== 'content.clock' && m.type !== 'status') dlog('msg', m.type, fromExtensionPage ? 'ext' : `tab:${tabId}`);
  // ---- từ content script (chỉ tab YouTube)
  if (!fromExtensionPage && tabId !== undefined && sender.tab?.url && YT.test(sender.tab.url)) {
    void (async () => {
      switch (m.type) {
        case 'content.hello':
        case 'content.nav': {
          const info: TabInfo = { video_id: typeof m.video_id === 'string' ? m.video_id : null, title: String(m.title ?? '').slice(0, 300),
            is_live: m.is_live === true, is_shorts: m.is_shorts === true };
          await setTabInfo(tabId, info);
          const a = await getActive();
          if (a && a.tab_id === tabId && a.video_id !== info.video_id) {
            // chuyển video (SPA/playlist/Shorts): đóng phiên cũ, không dùng transcript cũ; tự mở phiên mới cho video mới
            await stopSession('video_changed');
            if (info.video_id) await startSession(tabId);
          } else if (a && a.tab_id === tabId && m.type === 'content.hello') {
            // content được nạp lại (reload trang) → đồng bộ lại trạng thái
            await stopSession('page_reloaded');
          }
          break;
        }
        case 'content.toggle':
          await toggle(tabId);
          break;
        case 'content.seek':
        case 'content.user_pause':
        case 'content.captions':
        case 'content.source_failed':
        case 'content.autoplay_blocked':
        case 'content.preload_skip': {
          const a = await getActive();
          if (a?.tab_id === tabId) await forwardToOffscreen(a, m);
          break;
        }
        case 'content.ended': {
          const a = await getActive();
          if (a?.tab_id === tabId && a.capture) await sendOffscreen({ type: 'offscreen.capture_stop' });
          break;
        }
        case 'content.clock': {
          // offscreen có thể đã bị đóng khi im lặng lâu → tạo lại (rehydrate) khi còn phiên
          const a = await getActive();
          if (a?.tab_id === tabId) await ensureSessionOffscreen(a);
          break;
        }
        default:
          break;
      }
    })();
    return;
  }
  // ---- từ extension pages (offscreen / side panel / options)
  if (fromExtensionPage) {
    switch (m.type) {
      case 'relay':
        void (async () => {
          const a = await getActive();
          const inner = m.msg as ToContent;
          if (a && a.tab_id === m.tab_id && isNs(inner) && TO_CONTENT_TYPES.has(inner.type)) await toTab(a.tab_id, inner);
          else if (isNs(inner) && inner.type === 'session.stopped' && typeof m.tab_id === 'number' && sender.url?.endsWith('/offscreen.html')) await toTab(m.tab_id, inner);
          else dlog('relay dropped', inner?.type, !!a, a?.tab_id === m.tab_id);
        })();
        return;
      case 'panel.pair':
        void pair().then(sendResponse);
        return true;
      case 'panel.toggle':
        void toggle(Number(m.tab_id)).then(sendResponse);
        return true;
      case 'panel.start':
        void startSession(Number(m.tab_id), m.mode as Mode | undefined).then(sendResponse);
        return true;
      case 'panel.stop':
        void stopSession('user_stop').then(() => sendResponse({ ok: true }));
        return true;
      case 'panel.capture_start':
        void startCapture(Number(m.tab_id)).then(sendResponse);
        return true;
      case 'panel.capture_stop':
        void (async () => {
          const a = await getActive();
          await sendOffscreen({ type: 'offscreen.capture_stop' });
          if (a) {
            try {
              await api('POST', `/v1/sessions/${a.session_id}/control`, { op: 'asr_stop' });
            } catch {
              /* bỏ qua */
            }
            await setActive({ ...a, capture: false });
          }
          sendResponse({ ok: true });
        })();
        return true;
      case 'panel.import_captions':
        void (async () => {
          const a = await getActive();
          if (!a) {
            const r = await startSession(Number(m.tab_id));
            if (!r.ok) return sendResponse(r);
          }
          const act = await getActive();
          if (!act) return sendResponse({ ok: false, code: 'CONNECT_FAILED' });
          await ensureSessionOffscreen(act);
          // gửi như tin content (offscreen chỉ tin content từ tab active → dùng kênh panel riêng)
          const r = await sendOffscreen<{ ok: boolean }>({ type: 'offscreen.import', payload: { ...(m.payload as object), video_id: act.video_id } });
          sendResponse(r ?? { ok: false, code: 'CONNECT_FAILED' });
        })();
        return true;
      case 'panel.settings_changed':
        void (async () => {
          const a = await getActive();
          if (!a) return sendResponse({ ok: true });
          const es = await loadEngineSettings();
          await sendOffscreen({ type: 'offscreen.settings', settings: es.settings, prefs: es.prefs });
          sendResponse({ ok: true });
        })();
        return true;
      case 'panel.preview':
        void (async () => {
          try {
            const p = await ensurePaired();
            await ensureOffscreen((await getActive())?.capture ?? false);
            let voice = m.voice_id as string | undefined;
            if (!voice) voice = (await api<{ value: { tts: { voice_id: string } } }>('GET', '/v1/settings')).value.tts.voice_id;
            sendResponse(await sendOffscreen({ type: 'offscreen.preview', broker_url: p.broker_url, token: p.session_token, voice_id: voice, text: m.text }));
          } catch (e) {
            sendResponse({ ok: false, code: e instanceof ApiError ? e.code : 'CONNECT_FAILED' });
          }
        })();
        return true;
      case 'panel.get_active':
        void (async () => {
          const q = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
          const t = q[0];
          sendResponse({ active: await getActive(), tab_id: t?.id ?? null, tab: t?.id !== undefined ? await tabInfo(t.id) : null,
            paired: !!(await getPairing()), youtube: !!t?.url && YT.test(t.url) });
        })();
        return true;
      case 'offscreen.auth_failed':
        void chrome.storage.session.remove('pairing');
        return;
      default:
        return;
    }
  }
});

chrome.runtime.onInstalled.addListener(() => void updateBadge(null));
chrome.runtime.onStartup.addListener(() => void chrome.storage.session.clear());
