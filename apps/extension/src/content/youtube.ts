/**
 * Adapter YouTube có version (NFR-13): mọi selector DOM gom tại đây, có nhiều tín hiệu dự phòng.
 * adapter_version: yt-dom-1 (kiểm với YouTube desktop 2026-09).
 */
export const ADAPTER_VERSION = 'yt-dom-1';

export function currentVideoId(loc: Location = location): string | null {
  const u = new URL(loc.href);
  if (u.pathname === '/watch') return sanitizeId(u.searchParams.get('v'));
  const m = /^\/(?:shorts|live|embed)\/([A-Za-z0-9_-]{6,20})/.exec(u.pathname);
  return m ? sanitizeId(m[1] ?? null) : null;
}

export function sanitizeId(v: string | null): string | null {
  return v && /^[A-Za-z0-9_-]{6,20}$/.test(v) ? v : null;
}

export function isShortsPage(loc: Location = location): boolean {
  return loc.pathname.startsWith('/shorts/');
}

export function playerEl(): HTMLElement | null {
  if (isShortsPage()) {
    return (document.querySelector('ytd-reel-video-renderer[is-active] #shorts-player') as HTMLElement | null)
      ?? (document.querySelector('#shorts-player') as HTMLElement | null);
  }
  return (document.getElementById('movie_player') as HTMLElement | null)
    ?? (document.querySelector('.html5-video-player') as HTMLElement | null);
}

export function videoEl(): HTMLVideoElement | null {
  const p = playerEl();
  const v = (p?.querySelector('video.html5-main-video') ?? p?.querySelector('video')) as HTMLVideoElement | null;
  return v ?? (document.querySelector('video.html5-main-video') as HTMLVideoElement | null);
}

/** Quảng cáo: nhiều tín hiệu; không chắc → 'unknown' (docs/06 §7). Không bypass/skip/chặn quảng cáo. */
export function adState(expectedVideoId: string | null): 'content' | 'ad' | 'unknown' {
  const p = playerEl();
  if (!p) return 'unknown';
  if (p.classList.contains('ad-showing') || p.classList.contains('ad-interrupting')) return 'ad';
  if (p.querySelector('.ytp-ad-player-overlay, .ytp-ad-player-overlay-layout, .video-ads .ytp-ad-module *:not(:empty)')) {
    const vid = p.querySelector('.ytp-ad-text, .ytp-ad-preview-container, .ytp-ad-simple-ad-badge');
    if (vid) return 'ad';
  }
  if (expectedVideoId && currentVideoId() !== expectedVideoId) return 'unknown';
  return 'content';
}

export function isLiveNow(): boolean {
  const p = playerEl();
  if (!p) return false;
  const badge = p.querySelector('.ytp-live-badge') as HTMLElement | null;
  return !!badge && !badge.hasAttribute('disabled') && getComputedStyle(badge).display !== 'none';
}

export function videoTitle(): string {
  const h = document.querySelector('h1.ytd-watch-metadata yt-formatted-string, h1.title, ytd-reel-video-renderer[is-active] h2') as HTMLElement | null;
  return (h?.textContent ?? document.title.replace(/ - YouTube$/, '')).trim().slice(0, 300);
}

export function controlsContainer(): HTMLElement | null {
  return playerEl()?.querySelector('.ytp-right-controls') as HTMLElement | null;
}

/** Transcript DOM (UI "Hiện bản chép lời"). Trả null nếu không có nút/không mở được. */
export async function readTranscriptDom(timeoutMs = 8000): Promise<{ rows: { ts: string; text: string }[]; stable: boolean } | null> {
  const findRows = () => Array.from(document.querySelectorAll('ytd-transcript-segment-renderer, transcript-segment-view-model'));
  if (findRows().length === 0) {
    const btn = (document.querySelector('ytd-video-description-transcript-section-renderer button')
      ?? Array.from(document.querySelectorAll('button')).find((b) => /transcript|bản chép lời/i.test(b.getAttribute('aria-label') ?? b.textContent ?? ''))) as HTMLButtonElement | undefined;
    if (!btn) return null;
    btn.click();
  }
  const t0 = Date.now();
  let last = -1;
  let stableRounds = 0;
  while (Date.now() - t0 < timeoutMs) {
    await new Promise((r) => setTimeout(r, 400));
    const rows = findRows();
    const container = rows[0]?.closest('#segments-container, ytd-transcript-segment-list-renderer, [role="list"]')?.parentElement;
    if (container) container.scrollTop = container.scrollHeight;       // nạp phần lazy
    if (rows.length > 0 && rows.length === last) stableRounds++;
    else stableRounds = 0;
    last = rows.length;
    if (stableRounds >= 3) break;
  }
  const rows = findRows().map((r) => ({
    ts: ((r.querySelector('.segment-timestamp, [class*="timestamp"]')?.textContent) ?? '').trim(),
    text: ((r.querySelector('.segment-text, [class*="segment-text"], span[role="text"]')?.textContent) ?? '').trim(),
  })).filter((r) => r.ts && r.text);
  return rows.length ? { rows, stable: stableRounds >= 3 } : null;
}
