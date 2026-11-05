// Chụp bảng bên (sidepanel.html) ở 400 px, sáng/tối, từng tab — kiểm tra giao diện bằng mắt (UI Vision First).
import { readFileSync, mkdirSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CDP, freshProfile, launchChromePipe, sleep } from './cdp.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const HOME = 'D:/VietDubLocal';
const EXT_ID = JSON.parse(readFileSync(join(HOME, 'local-config.json'), 'utf8')).allowed_extension_ids[0];
const ORIGIN = `chrome-extension://${EXT_ID}`;
const out = join(HOME, 'e2e', 'panel-shots');
mkdirSync(out, { recursive: true });
const { proc, info } = await launchChromePipe({ exe: 'C:/Program Files/Google/Chrome/Application/chrome.exe', profile: freshProfile(),
  extension: join(root, 'apps/extension/dist'), extraArgs: ['--disable-audio-output'] });
const cdp = await CDP.connect(info.webSocketDebuggerUrl);
await sleep(1500);
const { targetId } = await cdp.send('Target.createTarget', { url: `${ORIGIN}/sidepanel.html` });
const s = await cdp.attach(targetId);
await cdp.send('Runtime.enable', {}, s);
await cdp.send('Emulation.setDeviceMetricsOverride', { width: 400, height: 900, deviceScaleFactor: 1, mobile: false }, s);
const ev = (e) => cdp.evaluate(s, e);
await sleep(1500);
await cdp.screenshot(s, join(out, '00-onboarding.png'));
// ghép nối thật qua native host
await ev(`(()=>{[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Kết nối'))?.click(); return true})()`);
for (let i = 0; i < 30; i++) { await sleep(1000); if (await ev(`!!document.querySelector('nav.tabs')`)) break; }
const tabs = ['Xem', 'Bản dịch', 'Thuật ngữ', 'Mô hình', 'Cài đặt', 'Chẩn đoán'];
for (const scheme of ['light', 'dark']) {
  await cdp.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scheme }] }, s);
  for (const [i, t] of tabs.entries()) {
    await ev(`(()=>{[...document.querySelectorAll('nav.tabs button')].find(b=>b.textContent===${JSON.stringify(t)})?.click(); return true})()`);
    await sleep(t === 'Mô hình' || t === 'Chẩn đoán' ? 2500 : 900);
    await cdp.screenshot(s, join(out, `${scheme}-${i + 1}-${t.replace(/\s/g, '_')}.png`));
  }
}
console.log('shots in', out);
cdp.close();
proc.kill();
process.exit(0);
