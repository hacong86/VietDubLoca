/**
 * Offscreen document: điều khiển phiên (WS + REST tới broker), audio engine, thu âm tab (ASR).
 * Chỉ có chrome.runtime → cấu hình (broker_url/token) do service worker gửi qua 'offscreen.start'.
 * Nhận tin content trực tiếp (runtime broadcast) nhưng CHỈ từ tab đang active của phiên.
 */
import { EventEnvelope, SessionSnapshot, TranslationReady } from '../../../../packages/contracts/src';
import { StreamResampler, floatToS16, mediaNow, packFrame, unpackFrame } from '../../../../packages/audio/src';
import { NS, isNs, type CaptionPayload, type ClockSnap, type Mode, type OverlayPrefs, type OverlaySeg, type PanelStatus, type PauseReason, type ToContent } from '../shared/messages';
import { STATE_VI, T } from '../shared/strings';
import { AudioEngine, type EngineSettings } from './engine';

interface Cfg {
  broker_url: string;
  token: string;
  session_id: string;
  epoch: number;
  tab_id: number;
  video_id: string;
  title: string;
  mode: Mode;
  settings: EngineSettings;
  prefs: OverlayPrefs;
  is_live: boolean;
  is_shorts: boolean;
  preload?: boolean;                                 // true = phiên mới (chuẩn bị trước khi phát); rehydrate = false
}

let cfg: Cfg | null = null;
let previewCfg: { broker_url: string; token: string } | null = null;
const base = () => cfg ?? previewCfg;
let ws: WebSocket | null = null;
let wsState: PanelStatus['connection'] = 'unpaired';
let lastPong = 0;
let snapshot: SessionSnapshot | null = null;
let replayPrompt: string | null = null;
let draft = '';
let sourceLabel: string | null = null;
let sourceFailed: { reason: string; tried: string[] } | null = null;
let lastError: string | null = null;
let capture: { stream: MediaStream; node: AudioWorkletNode; src: MediaStreamAudioSourceNode; seq: number; rs: StreamResampler | null; pending: number[] } | null = null;
let autoplayBlocked = false;
let lastClockSent = 0;
let segRefreshTimer: number | undefined;
let captionsPosting = false;

const engine = new AudioEngine({
  pauseVideo: (reason) => toTab({ ns: NS, type: 'video.pause', reason }),
  playVideo: (reason) => toTab({ ns: NS, type: 'video.play', reason }),
  status: () => broadcast(),
  stopped: (epoch, reason) => wsSend({ type: 'audio.stopped', epoch, reason }),
  replayPrompt: (seg) => {
    replayPrompt = seg;
    toTab({ ns: NS, type: 'overlay.status', text: `${T.replay_current}? Mở bảng bên hoặc bấm Alt+Shift+R`, level: 'info' });
    broadcast();
  },
  progress: (pct) => {
    toTab({ ns: NS, type: 'overlay.progress', pct });
    broadcast();
  },
  notice: (text) => toTab({ ns: NS, type: 'overlay.status', text, level: 'info' }),
});

// ------------------------------------------------------------------ helpers
function toTab(msg: ToContent): void {
  if (!cfg) return;
  void chrome.runtime.sendMessage({ ns: NS, type: 'relay', tab_id: cfg.tab_id, msg }).catch(() => undefined);
}

async function rest<T>(method: string, path: string, body?: unknown): Promise<T> {
  const b = base();
  if (!b) throw new Error('no session');
  const r = await fetch(b.broker_url + path, {
    method, cache: 'no-store', credentials: 'omit', redirect: 'error',
    headers: { Authorization: `Bearer ${b.token}`, ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = r.status === 204 ? null : await r.json().catch(() => null);
  if (!r.ok) throw Object.assign(new Error((data as { code?: string } | null)?.code ?? 'HTTP_' + r.status), { data });
  return data as T;
}

function holdText(reason: PauseReason | undefined): string {
  switch (reason) {
    case 'AUTO_BUFFER': return T.preparing_next;
    case 'AUTO_SENTENCE': return T.reading_rest;
    case 'CATCHUP': return 'Đang bắt kịp tiếng Việt…';
    case 'PRELOAD': return 'Đang chuẩn bị thuyết minh…';
    case 'BLOCKED': return T.blocked;
    default: return '';
  }
}

function status(): PanelStatus {
  return {
    connection: wsState,
    error_code: lastError,
    session: snapshot,
    hold: engine.hold ? { reason: engine.hold.reason, text: holdText(engine.hold.reason) } : null,
    preload: engine.preload ? { pct: Math.max(0, engine.preload.lastPct) } : null,
    replay_prompt: replayPrompt ? { segment_id: replayPrompt } : null,
    queue_ms: engine.queuedMs(),
    lag_ms: snapshot?.lag_ms ?? null,
    draft,
    capture: !!capture,
    video: cfg ? { video_id: cfg.video_id, title: cfg.title, tab_id: cfg.tab_id, is_live: cfg.is_live, is_shorts: cfg.is_shorts } : null,
    source_label: sourceLabel,
    source_failed: sourceFailed,
    autoplay_blocked: autoplayBlocked,
    media_ms: Math.max(0, Math.round(mediaNow(engine.anchor, engine.ctx.currentTime))),
  };
}

let broadcastTimer: number | undefined;
function broadcast(): void {
  if (broadcastTimer) return;
  broadcastTimer = window.setTimeout(() => {
    broadcastTimer = undefined;
    void chrome.runtime.sendMessage({ ns: NS, type: 'status', status: status(), stats: engine.stats }).catch(() => undefined);
  }, 60);
}
setInterval(broadcast, 1000);

// ------------------------------------------------------------------ WebSocket
function wsSend(obj: unknown): void {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function connect(): void {
  const b = base();
  if (!b) return;
  wsState = wsState === 'connected' ? 'reconnecting' : 'connecting';
  const url = b.broker_url.replace(/^http:/, 'ws:') + '/v1/events';
  const sock = new WebSocket(url);
  ws = sock;
  sock.binaryType = 'arraybuffer';
  sock.onopen = () => {
    sock.send(JSON.stringify({ type: 'auth', token: base()?.token, protocol_version: 1, role: 'audio' }));
  };
  sock.onmessage = (ev) => {
    if (sock !== ws) return;
    if (ev.data instanceof ArrayBuffer) return onBinary(ev.data);
    let parsed: unknown;
    try {
      parsed = JSON.parse(String(ev.data));
    } catch {
      return;
    }
    const env = EventEnvelope.safeParse(parsed);
    if (env.success) onEvent(env.data);
  };
  sock.onclose = () => {
    if (sock !== ws) return;
    ws = null;
    if (!cfg) return;
    wsState = 'reconnecting';
    engine.stopAll('connection_lost', undefined, true);
    broadcast();
    setTimeout(connect, 1500);
  };
  sock.onerror = () => undefined;
}

// Heartbeat: mất WS được báo trong ~3 s (NFR-18).
setInterval(() => {
  if (!cfg || !ws || ws.readyState !== WebSocket.OPEN) return;
  wsSend({ type: 'ping', t: Date.now() });
  if (wsState === 'connected' && lastPong && Date.now() - lastPong > 3500) {
    wsState = 'reconnecting';
    engine.stopAll('heartbeat_lost', undefined, true);
    broadcast();
    try {
      ws.close();
    } catch {
      /* bỏ qua */
    }
  }
}, 1000);

function onBinary(buf: ArrayBuffer): void {
  try {
    const { header, pcm } = unpackFrame(buf);
    if (header.kind !== 'tts_pcm' || !header.segment_id) return;
    engine.chunk({ segment_id: header.segment_id, revision: header.revision, timeline_epoch: header.timeline_epoch, session_id: header.session_id }, pcm);
  } catch {
    /* frame lỗi: bỏ, không crash */
  }
}

function onEvent(e: EventEnvelope): void {
  const p = e.payload as Record<string, unknown>;
  switch (e.event) {
    case 'auth.ok':
      wsState = 'connected';
      lastPong = Date.now();
      lastError = null;
      if (cfg) wsSend({ type: 'subscribe', session_id: cfg.session_id });
      break;
    case 'auth.error':
      wsState = 'error';
      lastError = String(p.code ?? 'AUTH_REQUIRED');
      void chrome.runtime.sendMessage({ ns: NS, type: 'offscreen.auth_failed', code: lastError }).catch(() => undefined);
      break;
    case 'pong':
      lastPong = Date.now();
      break;
    case 'session.state': {
      const s = SessionSnapshot.safeParse(p);
      if (s.success && cfg && s.data.session_id === cfg.session_id) {
        const prevEpoch = engine.epoch;
        snapshot = s.data;
        engine.sourceComplete = s.data.source?.coverage === 'full';
        engine.setEpoch(s.data.timeline_epoch);
        engine.mode = s.data.mode;
        if (s.data.timeline_epoch !== prevEpoch) {
          // gửi lại clock ngay theo epoch mới
          lastClockSent = 0;
        }
        if (s.data.state === 'STOPPED') {
          engine.reset();
        }
        if (s.data.state === 'ERROR' && s.data.last_error === 'LIVE_QUEUE_OVERFLOW') {
          toTab({ ns: NS, type: 'overlay.status', text: T.overflow, level: 'error' });
          stopCapture();
        }
      }
      break;
    }
    case 'source.changed':
      if (typeof p.committed_text === 'string') draft = '';
      scheduleSegRefresh(100);
      break;
    case 'translation.ready':
    case 'translation.blocked': {
      const t = TranslationReady.partial().safeParse(p);
      if (t.success && t.data.segment_id) {
        const seg = { segment_id: t.data.segment_id, revision: t.data.revision ?? 1, start_ms: t.data.start_ms ?? 0, end_ms: t.data.end_ms ?? 0,
          status: e.event === 'translation.ready' ? 'ready' : 'blocked' };
        engine.segments.set(seg.segment_id, { ...seg, status: e.event === 'translation.ready' && t.data.target_spoken === '' ? 'silent' : seg.status });
        toTab({ ns: NS, type: 'overlay.segments', segments: [{ ...seg, source_text: t.data.source_text ?? '', target_display: t.data.target_display ?? '' }] });
      }
      break;
    }
    case 'audio.begin':
      if (typeof p.segment_id === 'string') {
        engine.begin({ segment_id: p.segment_id, revision: Number(p.revision ?? 1), epoch: p.preview ? engine.epoch : e.timeline_epoch,
          start_ms: Number(p.start_ms ?? 0), end_ms: Number(p.end_ms ?? 0), next_start_ms: (p.next_start_ms as number | null) ?? null,
          duration_ms: Number(p.duration_ms ?? 0), preview: p.preview === true });
      }
      break;
    case 'audio.end':
      if (typeof p.segment_id === 'string') engine.end(p.segment_id, Number(p.revision ?? 1), p.complete === true);
      break;
    case 'audio.stop':
      if (!cfg || e.session_id !== cfg.session_id) break;                     // sự kiện phiên khác: bỏ (Codex #9)
      if (typeof p.segment_id === 'string' && typeof p.stop_revision_below === 'number') engine.invalidateRevision(p.segment_id, p.stop_revision_below);
      else if (typeof p.stop_epoch === 'number' && p.stop_epoch >= engine.epoch) {
        engine.stopAll(String(p.reason ?? 'stop'));
        if (p.reason === 'user_stop' || p.reason === 'replaced_by_new_session' || p.reason === 'companion_exit') engine.reset();
      }
      break;
    case 'asr.draft':
      draft = typeof p.text === 'string' ? p.text : '';
      toTab({ ns: NS, type: 'overlay.draft', text: draft });
      break;
    case 'error':
      lastError = String(p.code ?? 'INTERNAL');
      if (lastError === 'GPU_OOM' || lastError === 'WORKER_CRASHED') toTab({ ns: NS, type: 'overlay.status', text: T.gpu_busy, level: 'error' });
      break;
    case 'model.progress':
      void chrome.runtime.sendMessage({ ns: NS, type: 'model.progress', payload: p }).catch(() => undefined);
      break;
    default:
      break;
  }
  broadcast();
}

function scheduleSegRefresh(delay = 1500): void {
  if (segRefreshTimer) return;
  segRefreshTimer = window.setTimeout(async () => {
    segRefreshTimer = undefined;
    if (!cfg) return;
    try {
      const r = await rest<{ segments: (OverlaySeg & { final: boolean; audio: string })[] }>('GET', `/v1/sessions/${cfg.session_id}/segments`);
      for (const s of r.segments) engine.segments.set(s.segment_id, { segment_id: s.segment_id, revision: s.revision, start_ms: s.start_ms, end_ms: s.end_ms, status: s.audio === 'silent' ? 'silent' : s.status });
      toTab({ ns: NS, type: 'overlay.segments', segments: r.segments.filter((s) => s.status === 'ready' || s.status === 'blocked').map((s) => ({
        segment_id: s.segment_id, revision: s.revision, start_ms: s.start_ms, end_ms: s.end_ms, source_text: s.source_text, target_display: s.target_display, status: s.status })) });
    } catch {
      /* thử lại lần sau */
    }
  }, delay);
}
setInterval(() => cfg && scheduleSegRefresh(0), 4000);

// ------------------------------------------------------------------ captions
let captionQueue: CaptionPayload | null = null;
async function postCaptions(pl: CaptionPayload): Promise<boolean> {
  if (!cfg || pl.video_id !== cfg.video_id) return false;
  if (captionsPosting) {
    captionQueue = pl;                              // gửi sau lượt hiện tại (không bỏ caption của phiên mới)
    return true;
  }
  captionsPosting = true;
  const sid = cfg.session_id;                       // chụp phiên lúc bắt đầu (Codex #7)
  sourceLabel = pl.label;
  sourceFailed = null;
  try {
    for (let i = 0; i < pl.cues.length; i += 500) {
      if (!cfg || cfg.session_id !== sid) return false;
      const part = pl.cues.slice(i, i + 500);
      await rest('POST', `/v1/sessions/${sid}/captions`, {
        session_id: sid, timeline_epoch: engine.epoch, source_id: pl.source_id, source_revision: 1,
        source_kind: pl.source_kind, language: pl.language, coverage: pl.coverage, available_until_ms: pl.available_until_ms,
        cues: part, ...(pl.offset_ms ? { offset_ms: pl.offset_ms } : {}),
      });
    }
    lastError = null;
    return true;
  } catch (e) {
    lastError = (e as Error).message;
    return false;
  } finally {
    captionsPosting = false;
    broadcast();
    const next = captionQueue;
    captionQueue = null;
    if (next) void postCaptions(next);
  }
}

// ------------------------------------------------------------------ clock
function onClock(c: ClockSnap): void {
  if (!cfg || c.video_id !== cfg.video_id) return;
  engine.onClock(c);
  const now = Date.now();
  if (engine.epochPending) return;
  if (now - lastClockSent >= 200 || c.paused || c.seeking) {
    lastClockSent = now;
    wsSend({ type: 'clock', clock: {
      session_id: cfg.session_id, timeline_epoch: engine.epoch, video_id: cfg.video_id, media_ms: Math.max(0, Math.round(c.media_ms)),
      monotonic_ms: Math.round(performance.now()), playback_rate: c.playback_rate, paused: c.paused, seeking: c.seeking, stalled: c.stalled,
      ad_state: c.ad_state, visibility: c.visibility } });
  }
  if (c.ad_state !== 'content') toTab({ ns: NS, type: 'volume.restore' });      // quảng cáo: trả tiếng gốc
}

// ------------------------------------------------------------------ capture (ASR)
async function startCapture(streamId: string): Promise<void> {
  if (!cfg || capture) return;
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { mandatory: { chromeMediaSource: 'tab', chromeMediaSourceId: streamId } } as unknown as MediaTrackConstraints,
    video: false,
  });
  await engine.ctx.audioWorklet.addModule(chrome.runtime.getURL('capture-worklet.js'));
  const src = engine.ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(engine.ctx, 'vietdub-capture');
  src.connect(node);                   // nhánh ASR: TRƯỚC gain nghe
  src.connect(engine.srcGain);         // nhánh nghe: tiếng gốc qua gain (tab bị capture sẽ im nếu không nối lại)
  capture = { stream, node, src, seq: 0, rs: null, pending: [] };
  const captureEpoch = engine.epoch;
  node.port.onmessage = (ev: MessageEvent<{ samples: Float32Array; rate: number }>) => {
    if (!capture || !cfg) return;
    if (engine.epoch !== captureEpoch && capture.seq > 0) {
      capture.seq = 0;                 // epoch mới: đánh số lại
    }
    if (!capture.rs || capture.rs.inRate !== ev.data.rate) capture.rs = new StreamResampler(ev.data.rate, 16000);
    const out = capture.rs.process(ev.data.samples);
    for (const v of out) capture.pending.push(v);
    while (capture.pending.length >= 1600) {        // 100 ms
      const block = Float32Array.from(capture.pending.splice(0, 1600));
      const pcm = floatToS16(block);
      const mediaMs = Math.max(0, Math.round(mediaNow(engine.anchor, engine.ctx.currentTime) - 100 * engine.anchor.rate));
      if (!engine.anchor.playing || engine.epochPending) continue;   // video dừng: không có lời mới để thu
      const frame = packFrame({ protocol_version: 1, kind: 'asr_pcm', session_id: cfg.session_id, timeline_epoch: engine.epoch, segment_id: null,
        revision: 0, seq: capture.seq++, sample_rate: 16000, channels: 1, codec: 'pcm_s16le', sample_count: pcm.length, is_last: false,
        capture_monotonic_ms: Math.round(performance.now()), source_media_ms: mediaMs }, new Uint8Array(pcm.buffer));
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(frame);
    }
  };
  stream.getAudioTracks()[0]?.addEventListener('ended', () => {
    lastError = 'AUDIO_CAPTURE_ENDED';
    stopCapture();
    void rest('POST', `/v1/sessions/${cfg?.session_id}/control`, { op: 'asr_stop' }).catch(() => undefined);
    broadcast();
  });
  broadcast();
}

function stopCapture(): void {
  if (!capture) return;
  capture.node.port.onmessage = null;
  try {
    capture.src.disconnect();
    capture.node.disconnect();
  } catch {
    /* bỏ qua */
  }
  capture.stream.getTracks().forEach((t) => t.stop());
  capture = null;
  broadcast();
}

// queue.status cho live (broker tính backlog + overflow)
setInterval(() => {
  if (cfg && engine.mode === 'live_delayed') wsSend({ type: 'queue.status', queued_ms: engine.queuedMs() });
}, 1000);

let seekSeq = 0;
/** STOP cục bộ trước rồi mới báo broker (docs/03 §7). Chỉ phản hồi của seek MỚI NHẤT được mở khóa pending. */
function doSeek(mediaMs: number, sentEpochMs?: number): void {
  engine.epochPending = true;
  engine.stopAll('seek', sentEpochMs ?? performance.timeOrigin + performance.now());
  replayPrompt = null;
  engine.endPreload(false);
  engine.beginPreload('seek');                       // sau khi tua: chuẩn bị ngắn (~8 s) rồi tự phát
  engine.hold = null;
  if (!cfg) return;
  const seq = ++seekSeq;
  const sid = cfg.session_id;
  const before = engine.epoch;
  const finish = (epoch: number | null) => {
    if (seq !== seekSeq || !cfg || cfg.session_id !== sid) return;
    if (epoch !== null && epoch > before) engine.setEpoch(epoch);
    else void rest<{ timeline_epoch: number }>('GET', `/v1/sessions/${sid}`).then((s) => {
      if (seq === seekSeq) {
        if (s.timeline_epoch > engine.epoch) engine.setEpoch(s.timeline_epoch);
        else engine.epochPending = false;
      }
    }).catch(() => undefined);                   // giữ audio dừng tới khi xác minh epoch
  };
  void rest<{ timeline_epoch: number }>('POST', `/v1/sessions/${sid}/control`, { op: 'seek', media_ms: Math.max(0, Math.round(mediaMs || 0)) })
    .then((r) => finish(r.timeline_epoch)).catch(() => finish(null));
  broadcast();
}

function replayCurrent(segmentId: string | undefined): void {
  const seg = segmentId ? engine.segments.get(segmentId) : undefined;
  replayPrompt = null;
  if (seg && cfg) {
    const paused = engine.userPaused || !!engine.hold;
    doSeek(seg.start_ms);
    toTab({ ns: NS, type: 'video.seek', media_ms: seg.start_ms });
    if (paused) toTab({ ns: NS, type: 'video.play', reason: 'USER' });
  }
  broadcast();
}

// ------------------------------------------------------------------ messages
chrome.runtime.onMessage.addListener((msg: unknown, sender, sendResponse) => {
  if (!isNs(msg)) return;
  const fromExtensionPage = sender.id === chrome.runtime.id && (!!sender.url && sender.url.startsWith(chrome.runtime.getURL('')));
  const fromActiveTab = !!cfg && !fromExtensionPage && sender.id === chrome.runtime.id && sender.tab?.id === cfg.tab_id;
  const m = msg as Record<string, unknown> & { type: string };
  if (fromExtensionPage) {
    switch (m.type) {
      case 'offscreen.start': {
        const c = m.cfg as Cfg;
        if (cfg && cfg.session_id === c.session_id) {
          sendResponse({ ok: true });
          return;
        }
        engine.reset();
        stopCapture();
        cfg = c;
        engine.sessionId = c.session_id;
        engine.epoch = c.epoch;
        engine.mode = c.mode;
        engine.applySettings(c.settings);
        snapshot = null;
        sourceLabel = null;
        sourceFailed = null;
        replayPrompt = null;
        lastError = null;
        autoplayBlocked = false;
        connect();
        if (c.preload !== false) engine.beginPreload('start');     // phiên mới: chuẩn bị ~30 s trước khi phát
        sendResponse({ ok: true });
        return;
      }
      case 'offscreen.stop': {
        const c = cfg;
        stopCapture();
        engine.reset();
        cfg = null;
        wsState = 'unpaired';
        const sock = ws;
        ws = null;
        sock?.close();
        snapshot = null;
        if (c) void chrome.runtime.sendMessage({ ns: NS, type: 'relay', tab_id: c.tab_id, msg: { ns: NS, type: 'session.stopped', reason: String(m.reason ?? 'stop') } }).catch(() => undefined);
        broadcast();
        sendResponse({ ok: true });
        return;
      }
      case 'offscreen.settings':
        if (cfg) {
          cfg.settings = { ...cfg.settings, ...(m.settings as Partial<EngineSettings>) };
          engine.applySettings(cfg.settings);
          if (m.prefs) {
            cfg.prefs = m.prefs as OverlayPrefs;
            toTab({ ns: NS, type: 'overlay.prefs', prefs: cfg.prefs });
          }
          if (!capture) toTab({ ns: NS, type: 'volume.apply', original_gain: cfg.settings.original_gain });
        }
        sendResponse({ ok: true });
        return;
      case 'offscreen.capture_start':
        void startCapture(String(m.stream_id)).then(() => {
          toTab({ ns: NS, type: 'volume.restore' });
          sendResponse({ ok: true });
        }).catch((e: Error) => {
          lastError = 'PERMISSION_DENIED';
          broadcast();
          sendResponse({ ok: false, code: 'PERMISSION_DENIED', detail: e.name });
        });
        return true;
      case 'offscreen.capture_stop':
        stopCapture();
        if (cfg) toTab({ ns: NS, type: 'volume.apply', original_gain: cfg.settings.original_gain });
        sendResponse({ ok: true });
        return;
      case 'offscreen.replay': {
        replayCurrent(String(m.segment_id));
        sendResponse({ ok: true });
        return;
      }
      case 'offscreen.resume_audio':
        void engine.ctx.resume();
        autoplayBlocked = false;
        toTab({ ns: NS, type: 'video.play', reason: 'USER' });
        sendResponse({ ok: true });
        return;
      case 'offscreen.preload_skip':
        engine.endPreload(true);
        broadcast();
        sendResponse({ ok: true });
        return;
      case 'offscreen.skip_blocked':
        if (engine.hold?.reason === 'BLOCKED' && engine.hold.seg) {
          const s = engine.segments.get(engine.hold.seg);
          if (s) s.status = 'skipped_by_user';
          engine.hold = null;
          toTab({ ns: NS, type: 'video.play', reason: 'BLOCKED' });
        }
        broadcast();
        sendResponse({ ok: true });
        return;
      case 'offscreen.preview':
        void (async () => {
          if (!cfg) previewCfg = { broker_url: String(m.broker_url), token: String(m.token) };
          if (!ws || ws.readyState > 1) connect();
          const t0 = Date.now();
          while (wsState !== 'connected' && Date.now() - t0 < 4000) await new Promise((r) => setTimeout(r, 100));
          try {
            await engine.ctx.resume();
            await rest('POST', '/v1/voices/preview', { voice_id: m.voice_id, ...(m.text ? { text: String(m.text).slice(0, 300) } : {}) });
            sendResponse({ ok: true });
          } catch (e) {
            sendResponse({ ok: false, code: (e as Error).message });
          }
        })();
        return true;
      case 'offscreen.replay_current': {
        const now = mediaNow(engine.anchor, engine.ctx.currentTime);
        const cur = Array.from(engine.segments.values()).find((x) => x.start_ms <= now && now < x.end_ms + 400)
          ?? Array.from(engine.segments.values()).filter((x) => x.start_ms <= now).sort((a, b) => b.start_ms - a.start_ms)[0];
        replayCurrent(cur?.segment_id);
        sendResponse({ ok: !!cur });
        return;
      }
      case 'offscreen.fwd': {
        const inner = m.msg as Record<string, unknown> & { type: string };
        if (!cfg || m.tab_id !== cfg.tab_id || !isNs(inner)) {
          sendResponse({ ok: false, code: 'NO_SESSION' });
          return;
        }
        void handleContentCommand(inner).then(sendResponse);
        return true;
      }
      case 'offscreen.import':
        void postCaptions(m.payload as CaptionPayload).then((ok) => sendResponse({ ok }));
        return true;
      case 'offscreen.get_status':
        sendResponse({ status: status(), stats: engine.stats });
        return;
      case 'offscreen.mode':
        if (cfg) {
          cfg.mode = m.mode as Mode;
          engine.mode = cfg.mode;
        }
        sendResponse({ ok: true });
        return;
      default:
        return;
    }
  }
  // clock: nhận trực tiếp (tần suất cao, mất một nhịp không sao). Lệnh quan trọng đến qua SW ('offscreen.fwd').
  if (fromActiveTab && m.type === 'content.clock') onClock(m.clock as ClockSnap);
});

/** Lệnh content quan trọng do SW chuyển tiếp sau khi bảo đảm offscreen tồn tại (Codex #3). Trả ack. */
async function handleContentCommand(m: Record<string, unknown> & { type: string }): Promise<{ ok: boolean }> {
  switch (m.type) {
    case 'content.seek':
      doSeek(Number(m.media_ms));
      return { ok: true };
    case 'content.preload_skip':
      engine.endPreload(true);                      // "Xem luôn"
      broadcast();
      return { ok: true };
    case 'content.user_pause':
      engine.userPaused = m.paused === true;
      if (!engine.userPaused && engine.preload) engine.endPreload(false);   // người dùng tự bấm play = bỏ qua chuẩn bị
      if (engine.userPaused) engine.hold = null;         // người dùng thắng auto-resume
      if (cfg) void rest('POST', `/v1/sessions/${cfg.session_id}/control`, { op: engine.userPaused ? 'pause' : 'play', reason: 'USER' }).catch(() => undefined);
      broadcast();
      return { ok: true };
    case 'content.captions':
      return { ok: await postCaptions(m.payload as CaptionPayload) };
    case 'content.source_failed':
      sourceFailed = { reason: String(m.reason), tried: (m.tried as string[]).slice(0, 10).map(String) };
      toTab({ ns: NS, type: 'overlay.status', text: T.no_future_captions, level: 'warn' });
      broadcast();
      return { ok: true };
    case 'content.autoplay_blocked':
      autoplayBlocked = true;
      toTab({ ns: NS, type: 'overlay.status', text: T.click_to_resume_audio, level: 'warn' });
      broadcast();
      return { ok: true };
    default:
      return { ok: false };
  }
}

void chrome.runtime.sendMessage({ ns: NS, type: 'offscreen.ready' }).catch(() => undefined);
void STATE_VI;

// Hook chẩn đoán cho harness E2E/diagnostic (chỉ trong trang extension, không lộ ra web).
(globalThis as unknown as Record<string, unknown>).__vietdub = {
  engine,
  status,
  speaking: () => engine.isSpeaking(),
  wsState: () => wsState,
};
