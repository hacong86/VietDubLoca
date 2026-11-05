/**
 * Content script (isolated world) — docs/03 §2, docs/06.
 * Theo dõi video/SPA/quảng cáo, gửi clock snapshot; overlay; nút trên player; thực thi lệnh pause/play/seek/volume
 * với quyền sở hữu rõ ràng. KHÔNG giữ token, KHÔNG gọi broker.
 */
import { NS, TO_CONTENT_TYPES, isNs, type ClockSnap, type FromContent, type PauseReason, type ToContent } from '../shared/messages';
import { SOURCE_QUALITY, type SourceKind } from '../shared/strings';
import { discoverCaptions } from './captions';
import { Overlay } from './overlay';
import { adState, controlsContainer, currentVideoId, isLiveNow, isShortsPage, playerEl, videoEl, videoTitle } from './youtube';

const overlay = new Overlay();
let active = false;
let mode: 'vod_sync' | 'live_delayed' | 'study' = 'vod_sync';
let captureMode = false;
let videoId: string | null = currentVideoId();
let boundVideo: HTMLVideoElement | null = null;
let lastHref = location.href;
let lastSegmentId: string | null = null;

// --- quyền sở hữu pause/play (docs/06 §5) ---
let appPauseReason: PauseReason | null = null;   // app đã pause và còn sở hữu
// Sự kiện pause/play do APP gây ra: nhận diện theo cửa sổ thời gian, không theo cờ dùng-một-lần — trình phát
// YouTube có thể bắn thêm sự kiện; trước đây sự kiện thừa bị coi là "người dùng tự dừng" → video không tự phát lại.
const APP_EVENT_WINDOW_MS = 1500;
let appPauseUntil = 0;
let appPlayUntil = 0;

// --- quyền sở hữu âm lượng (docs/06 §8) ---
const vol = { owned: false, snapshot: 1, applied: 1, ours: false };

function send(msg: FromContent): void {
  try {
    void chrome.runtime.sendMessage(msg).catch(() => undefined);
  } catch {
    /* extension reload → context invalid */
  }
}

function snapshot(): ClockSnap | null {
  const v = videoEl();
  if (!v || !videoId) return null;
  return {
    video_id: videoId,
    media_ms: Math.max(0, Math.round(v.currentTime * 1000)),
    playback_rate: Math.max(0.25, Math.min(4, v.playbackRate || 1)),
    paused: v.paused || v.ended,
    seeking: v.seeking,
    stalled: v.readyState < 3 && !v.paused,
    ad_state: adState(videoId),
    visibility: document.visibilityState === 'hidden' ? 'hidden' : 'visible',
    sent_epoch_ms: performance.timeOrigin + performance.now(),
    duration_ms: Number.isFinite(v.duration) ? Math.round(v.duration * 1000) : undefined,
    volume: v.volume,
    muted: v.muted,
  };
}

function sendClock(): void {
  const c = snapshot();
  if (c && active) send({ ns: NS, type: 'content.clock', clock: c });
}

function bindVideo(): void {
  const v = videoEl();
  if (!v || v === boundVideo) return;
  boundVideo = v;
  const onEv = () => sendClock();
  for (const e of ['play', 'playing', 'ratechange', 'waiting', 'stalled', 'canplay', 'seeked', 'loadedmetadata']) v.addEventListener(e, onEv);
  v.addEventListener('seeking', () => {
    if (active && videoId) send({ ns: NS, type: 'content.seek', video_id: videoId, media_ms: Math.round(v.currentTime * 1000) });
    sendClock();
  });
  v.addEventListener('pause', () => {
    if (performance.now() < appPauseUntil) {
      /* do app dừng (giữ hình / chuẩn bị) */
    } else if (active) {
      appPauseReason = null;                         // người dùng pause thắng mọi auto-resume
      send({ ns: NS, type: 'content.user_pause', paused: true });
    }
    sendClock();
  });
  v.addEventListener('play', () => {
    if (performance.now() < appPlayUntil) {
      /* do app tự phát lại */
    } else if (active) {
      appPauseReason = null;
      send({ ns: NS, type: 'content.user_pause', paused: false });
    }
  });
  v.addEventListener('ended', () => {
    if (active && videoId) send({ ns: NS, type: 'content.ended', video_id: videoId });
  });
  v.addEventListener('volumechange', () => {
    if (vol.ours) {
      vol.ours = false;
      return;
    }
    if (vol.owned && Math.abs(v.volume - vol.applied) > 0.01) vol.owned = false;   // người dùng chỉnh → không đè lại
  });
}

// --- vòng lặp render + clock ---
let clockTimer: number | undefined;
function tick(): void {
  const v = videoEl();
  if (v && active) {
    const seg = overlay.render(v.currentTime * 1000);
    if (seg !== lastSegmentId) lastSegmentId = seg;
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

function startClock(): void {
  stopClock();
  clockTimer = window.setInterval(sendClock, 200);
}
function stopClock(): void {
  if (clockTimer) clearInterval(clockTimer);
  clockTimer = undefined;
}

// --- điều hướng SPA (FR-031) ---
function checkNav(): void {
  if (location.href === lastHref) return;
  lastHref = location.href;
  const vid = currentVideoId();
  if (vid !== videoId) {
    videoId = vid;
    sourceKind = null;
    overlay.clear();
    appPauseReason = null;
    boundVideo = null;
    setTimeout(bindVideo, 500);
    send({ ns: NS, type: 'content.nav', video_id: vid, title: videoTitle(), is_live: isLiveNow(), is_shorts: isShortsPage() });
  }
}
document.addEventListener('yt-navigate-finish', () => setTimeout(checkNav, 50));
window.setInterval(() => {
  checkNav();
  bindVideo();
  ensureButton();
  if (active) overlay.attach(playerEl());
}, 1000);

// --- nút trên player (UI-06) ---
let btn: HTMLButtonElement | null = null;
let sourceKind: SourceKind | null = null;       // chấm màu = chất lượng nguồn phụ đề
function ensureButton(): void {
  const c = controlsContainer();
  if (!c || (btn && btn.isConnected)) return;
  btn = document.createElement('button');
  btn.className = 'ytp-button';
  btn.setAttribute('data-vietdub', 'toggle');
  btn.style.cssText = 'width:auto;padding:0 8px;font:600 13px/1 "Segoe UI",system-ui,sans-serif;color:#fff;opacity:.9;vertical-align:top;';
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    send({ ns: NS, type: 'content.toggle' });
  });
  updateButton();
  c.insertBefore(btn, c.firstChild);
}
function updateButton(): void {
  if (!btn) return;
  const q = active && sourceKind ? SOURCE_QUALITY[sourceKind] : null;
  btn.textContent = active ? 'VI ●' : 'VI';
  btn.title = active ? `Tắt thuyết minh tiếng Việt${q ? ` · Nguồn: ${q.label} — ${q.hint}` : ''}` : 'Bật tiếng Việt (VietDub Local)';
  btn.setAttribute('aria-label', btn.title);
  btn.setAttribute('aria-pressed', String(active));
  btn.style.color = active ? (q?.dot ?? '#7ee2a8') : '#fff';
  btn.dataset.source = q ? sourceKind ?? '' : '';
}

// --- lệnh từ extension (chỉ nhận từ runtime của chính extension) ---
async function playVideo(reason: PauseReason): Promise<void> {
  const v = videoEl();
  if (!v || !v.paused) return;
  if (appPauseReason === null && reason !== 'USER') return;      // user đã giành quyền: không tự play
  appPlayUntil = performance.now() + APP_EVENT_WINDOW_MS;
  appPauseReason = null;
  try {
    await v.play();
  } catch {
    appPlayUntil = 0;
    send({ ns: NS, type: 'content.autoplay_blocked' });
  }
}

function pauseVideo(reason: PauseReason): void {
  const v = videoEl();
  if (!v || v.paused) return;
  appPauseUntil = performance.now() + APP_EVENT_WINDOW_MS;
  appPauseReason = reason;
  v.pause();
}

function applyVolume(g: number): void {
  const v = videoEl();
  if (!v || captureMode) return;               // khi thu tab: giữ nguồn đủ lớn cho ASR, giảm bằng gain ở offscreen
  if (!vol.owned) {
    vol.snapshot = v.volume;
    vol.owned = true;
  }
  const target = Math.max(0, Math.min(1, vol.snapshot * g));
  vol.applied = target;
  vol.ours = true;
  v.volume = target;
}

function restoreVolume(): void {
  const v = videoEl();
  if (v && vol.owned && Math.abs(v.volume - vol.applied) <= 0.01) {
    vol.ours = true;
    v.volume = vol.snapshot;       // chỉ trả phần app còn sở hữu; không unmute
  }
  vol.owned = false;
}

chrome.runtime.onMessage.addListener((msg: unknown, sender) => {
  if (sender.id !== chrome.runtime.id || !isNs(msg) || !TO_CONTENT_TYPES.has(msg.type as ToContent['type'])) return;
  const m = msg as ToContent;
  if (m.type !== 'overlay.segments' && m.type !== 'ping') console.info('[vietdub] content got', m.type);
  switch (m.type) {
    case 'session.started':
      active = true;
      mode = m.mode;
      captureMode = m.capture;
      sourceKind = m.capture ? 'asr' : null;
      overlay.applyPrefs(m.prefs);
      overlay.attach(playerEl());
      startClock();
      sendClock();
      updateButton();
      if (!m.capture) applyVolume(m.original_gain);
      break;
    case 'session.stopped':
      active = false;
      overlay.setProgress(null, () => undefined);
      sourceKind = null;
      stopClock();
      restoreVolume();
      overlay.clear();
      overlay.detach();
      appPauseReason = null;
      updateButton();
      break;
    case 'overlay.segments':
      overlay.setSegments(m.segments);
      break;
    case 'overlay.draft':
      overlay.setDraft(m.text);
      break;
    case 'overlay.prefs':
      overlay.applyPrefs(m.prefs);
      break;
    case 'overlay.status':
      overlay.setStatus(m.text, m.level, m.level === 'info' ? 4000 : 0);
      break;
    case 'overlay.progress':
      overlay.setProgress(m.pct, () => send({ ns: NS, type: 'content.preload_skip' }));
      break;
    case 'video.pause':
      pauseVideo(m.reason);
      break;
    case 'video.play':
      void playVideo(m.reason);
      break;
    case 'video.seek': {
      const v = videoEl();
      if (v && Number.isFinite(m.media_ms)) v.currentTime = Math.max(0, m.media_ms / 1000);
      break;
    }
    case 'volume.apply':
      applyVolume(m.original_gain);
      break;
    case 'volume.restore':
      restoreVolume();
      break;
    case 'captions.fetch':
      void fetchCaptions();
      break;
    case 'ping':
      break;
  }
  void mode;
});

let fetching = false;
async function fetchCaptions(): Promise<void> {
  if (fetching || !videoId) return;
  fetching = true;
  const vid = videoId;
  try {
    const v = videoEl();
    const dur = v && Number.isFinite(v.duration) ? Math.round(v.duration * 1000) : undefined;
    const res = await discoverCaptions(vid, dur);
    console.info('[vietdub] captions', res.ok ? `ok ${res.payload.cues.length} ${res.payload.coverage}` : `fail ${res.tried.join(' | ')}`);
    if (vid !== videoId) return;                                    // đã chuyển video: bỏ kết quả cũ
    if (res.ok) {
      sourceKind = res.payload.source_kind as SourceKind;
      updateButton();
      send({ ns: NS, type: 'content.captions', payload: res.payload });
    }
    else send({ ns: NS, type: 'content.source_failed', video_id: vid, reason: res.reason, tried: res.tried });
  } finally {
    fetching = false;
  }
}

// chào extension để biết video hiện tại
bindVideo();
send({ ns: NS, type: 'content.hello', video_id: videoId, title: videoTitle(), is_live: isLiveNow(), is_shorts: isShortsPage() });
