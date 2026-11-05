// Debug E2E: mở Chrome riêng, bật VI, gom console/lỗi của SW + offscreen + content, dump trạng thái.
import { readFileSync, writeFileSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CDP, launchChromePipe, sleep } from './cdp.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const HOME = 'D:/VietDubLocal';
const EXT_ID = JSON.parse(readFileSync(join(HOME, 'local-config.json'), 'utf8')).allowed_extension_ids[0];
const ORIGIN = `chrome-extension://${EXT_ID}`;
const videoId = process.argv[2] ?? 'aircAruvnKk';
const waitS = Number(process.argv[3] ?? 40);
const { proc, info } = await launchChromePipe({ exe: 'C:/Program Files/Google/Chrome/Application/chrome.exe', profile: join(HOME, 'e2e-profile'),
  extension: join(root, 'apps/extension/dist'), extraArgs: ['--disable-audio-output', '--autoplay-policy=no-user-gesture-required'] });
const cdp = await CDP.connect(info.webSocketDebuggerUrl);
const logs = [];
cdp.on((m) => {
  if (m.method === 'Runtime.consoleAPICalled') logs.push({ s: m.sessionId?.slice(0, 6), type: m.params.type, args: m.params.args.map((a) => a.value ?? a.description).join(' ').slice(0, 400) });
  if (m.method === 'Runtime.exceptionThrown') logs.push({ s: m.sessionId?.slice(0, 6), type: 'EXC', args: (m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text).slice(0, 600) });
  if (m.method === 'Log.entryAdded') logs.push({ s: m.sessionId?.slice(0, 6), type: 'log-' + m.params.entry.level, args: `${m.params.entry.text} ${m.params.entry.url ?? ''}`.slice(0, 400) });
});
await cdp.send('Target.setDiscoverTargets', { discover: true });
const attached = new Map();
async function attachAll() {
  for (const t of await cdp.targets()) {
    if (attached.has(t.targetId) || !(t.url.startsWith(ORIGIN) || t.url.includes('youtube.com'))) continue;
    try {
      const s = await cdp.attach(t.targetId);
      attached.set(t.targetId, { s, url: t.url, type: t.type });
      await cdp.send('Runtime.enable', {}, s).catch(() => {});
      await cdp.send('Log.enable', {}, s).catch(() => {});
      await cdp.send('Runtime.runIfWaitingForDebugger', {}, s).catch(() => {});
    } catch { /* */ }
  }
}
await sleep(1500);
const { targetId } = await cdp.send('Target.createTarget', { url: `https://www.youtube.com/watch?v=${videoId}` });
await sleep(6000);
await attachAll();
const page = [...attached.entries()].find(([id]) => id === targetId)?.[1].s;
await cdp.send('Target.activateTarget', { targetId });
await cdp.send('Page.bringToFront', {}, page).catch(() => {});
let hasBtn = false;
for (let i = 0; i < 40 && !hasBtn; i++) {
  hasBtn = await cdp.evaluate(page, `!!document.querySelector('[data-vietdub=toggle]') && !!document.querySelector('video.html5-main-video')`).catch(() => false);
  if (!hasBtn) await sleep(1000);
}
console.log('button', hasBtn);
await cdp.evaluate(page, `(()=>{const v=document.querySelector('video.html5-main-video'); v.play().catch(()=>{}); return true})()`, false);
await sleep(2000);
if (!hasBtn) { await cdp.screenshot(page, join(HOME, 'e2e', 'debug-nobutton.png')); console.log('diag', await cdp.evaluate(page, `JSON.stringify({href: location.href, title: document.title, player: !!document.getElementById('movie_player'), ctrl: !!document.querySelector('.ytp-right-controls'), vd: !!document.querySelector('video')})`)); }
await cdp.evaluate(page, `document.querySelector('[data-vietdub=toggle]')?.click()`);
for (let i = 0; i < waitS; i += 5) {
  await sleep(5000);
  await attachAll();
}
const out = { targets: (await cdp.targets()).map((t) => ({ type: t.type, url: t.url.slice(0, 90) })) };
for (const [, t] of attached) {
  if (t.url.includes('background.js')) out.sw_storage = await cdp.evaluate(t.s, `chrome.storage.session.get(null).then(x=>JSON.stringify({...x, pairing: x.pairing ? {...x.pairing, session_token: '***'} : null}))`).catch((e) => String(e));
  if (t.url.includes('offscreen.html')) out.offscreen = await cdp.evaluate(t.s, `JSON.stringify(globalThis.__vietdub?.status())`).catch((e) => String(e));
}
out.page = await cdp.evaluate(page, `JSON.stringify({ href: location.href, ad: document.getElementById('movie_player')?.classList.contains('ad-showing'), paused: document.querySelector('video')?.paused, t: document.querySelector('video')?.currentTime, overlay: !!document.querySelector('[data-vietdub=overlay]') })`);
await cdp.screenshot(page, join(HOME, 'e2e', 'debug.png'));
out.logs = logs.slice(-80);
writeFileSync(join(HOME, 'e2e', 'debug.json'), JSON.stringify(out, null, 1));
console.log(JSON.stringify(out, null, 1).slice(0, 9000));
cdp.close();
proc.kill();
process.exit(0);
