// Thăm dò cách lấy timedtext trên YouTube thật (main world của trang).
import { readFileSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CDP, launchChromePipe, sleep } from './cdp.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const HOME = 'D:/VietDubLocal';
const vid = process.argv[2] ?? 'aircAruvnKk';
const { proc, info } = await launchChromePipe({ exe: 'C:/Program Files/Google/Chrome/Application/chrome.exe', profile: join(HOME, 'e2e-profile'),
  extension: join(root, 'apps/extension/dist'), extraArgs: ['--disable-audio-output', '--autoplay-policy=no-user-gesture-required'] });
const cdp = await CDP.connect(info.webSocketDebuggerUrl);
const { targetId } = await cdp.send('Target.createTarget', { url: `https://www.youtube.com/watch?v=${vid}` });
const page = await cdp.attach(targetId);
await cdp.send('Runtime.enable', {}, page);
for (let i = 0; i < 40; i++) {
  if (await cdp.evaluate(page, `!!document.querySelector('.ytp-subtitles-button') && !!document.getElementById('movie_player')?.getPlayerResponse`).catch(() => false)) break;
  await sleep(1000);
}
await sleep(3000);
const r1 = await cdp.evaluate(page, `(async () => {
  const p = document.getElementById('movie_player');
  const resp = p.getPlayerResponse();
  const tracks = resp?.captions?.playerCaptionsTracklistRenderer?.captionTracks ?? [];
  const out = { tracks: tracks.map(t => ({ lang: t.languageCode, kind: t.kind, url: t.baseUrl.slice(0, 160) })) };
  if (tracks[0]) {
    const u = new URL(tracks[0].baseUrl, location.href); u.searchParams.set('fmt', 'json3');
    const r = await fetch(u); const txt = await r.text();
    out.direct = { status: r.status, len: txt.length, head: txt.slice(0, 80) };
  }
  out.cc_pressed = document.querySelector('.ytp-subtitles-button')?.getAttribute('aria-pressed');
  return JSON.stringify(out);
})()`);
console.log('R1', r1);
// Hook XHR/fetch để bắt NỘI DUNG phản hồi timedtext của chính player
await cdp.evaluate(page, `(() => {
  window.__ttb = [];
  const oo = XMLHttpRequest.prototype.open, os = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u, ...r) { this.__u = String(u); return oo.call(this, m, u, ...r); };
  XMLHttpRequest.prototype.send = function (...a) { if ((this.__u||'').includes('/api/timedtext')) this.addEventListener('load', () => window.__ttb.push({ via: 'xhr', url: this.__u.slice(0, 100), len: (this.responseText||'').length, head: (this.responseText||'').slice(0, 80) })); return os.apply(this, a); };
  const of = window.fetch;
  window.fetch = function (i, init) { const u = typeof i === 'string' ? i : i.url; const p = of.call(this, i, init); if (String(u).includes('/api/timedtext')) p.then(r => r.clone().text()).then(t => window.__ttb.push({ via: 'fetch', url: String(u).slice(0, 100), len: t.length, head: t.slice(0, 80) })); return p; };
  return true;
})()`);
const btnState = await cdp.evaluate(page, `document.querySelector('.ytp-subtitles-button')?.getAttribute('aria-pressed')`);
if (btnState === 'true') { await cdp.evaluate(page, `document.querySelector('.ytp-subtitles-button').click(); true`); await sleep(800); }
await cdp.evaluate(page, `(() => { const p = document.getElementById('movie_player'); p.loadModule('captions'); p.setOption('captions', 'track', { languageCode: 'en' }); return true })()`);
await sleep(4000);
console.log('R2', await cdp.evaluate(page, `JSON.stringify(window.__ttb)`));
// Transcript DOM
await cdp.evaluate(page, `(() => { const b = [...document.querySelectorAll('button')].find(b => /Show transcript/i.test(b.getAttribute('aria-label') || b.textContent || '')); b?.click(); return !!b })()`);
await sleep(4000);
console.log('R3', await cdp.evaluate(page, `(() => {
  const panel = document.querySelector('ytd-engagement-panel-section-list-renderer[target-id*="transcript"], [target-id="engagement-panel-searchable-transcript"]');
  const cands = ['ytd-transcript-segment-renderer', 'transcript-segment-view-model', 'ytd-transcript-segment-list-renderer', '[class*="segment"]'];
  const counts = Object.fromEntries(cands.map(c => [c, document.querySelectorAll(c).length]));
  const first = document.querySelector('ytd-transcript-segment-renderer, transcript-segment-view-model');
  return JSON.stringify({ panel: !!panel, visibility: panel?.getAttribute('visibility'), counts, firstHtml: first ? first.outerHTML.replace(/\s+/g, ' ').slice(0, 700) : null });
})()`));
cdp.close();
proc.kill();
process.exit(0);
