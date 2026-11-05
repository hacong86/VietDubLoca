// Thăm dò đường relay offscreen → SW → content trên Chrome riêng.
import { readFileSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CDP, launchChromePipe, sleep } from './cdp.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const HOME = 'D:/VietDubLocal';
const EXT_ID = JSON.parse(readFileSync(join(HOME, 'local-config.json'), 'utf8')).allowed_extension_ids[0];
const ORIGIN = `chrome-extension://${EXT_ID}`;
const { proc, info } = await launchChromePipe({ exe: 'C:/Program Files/Google/Chrome/Application/chrome.exe', profile: join(HOME, 'e2e-profile'),
  extension: join(root, 'apps/extension/dist'), extraArgs: ['--disable-audio-output', '--autoplay-policy=no-user-gesture-required'] });
const cdp = await CDP.connect(info.webSocketDebuggerUrl);
const logs = [];
cdp.on((m) => {
  if (m.method === 'Runtime.consoleAPICalled') logs.push(`[${m.sessionId?.slice(0, 4)}] ${m.params.args.map((a) => a.value ?? a.description).join(' ').slice(0, 300)}`);
  if (m.method === 'Runtime.exceptionThrown') logs.push(`[${m.sessionId?.slice(0, 4)}] EXC ${(m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text).slice(0, 400)}`);
});
// auto-attach mọi target mới để không mất log
await cdp.send('Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: false, flatten: true });
cdp.on(async (m) => {
  if (m.method === 'Target.attachedToTarget') {
    const s = m.params.sessionId;
    await cdp.send('Runtime.enable', {}, s).catch(() => {});
  }
});
const sw = (await cdp.targets()).find((t) => t.type === 'service_worker' && t.url.startsWith(ORIGIN));
const swS = await cdp.attach(sw.targetId);
await cdp.send('Runtime.enable', {}, swS);
const { targetId } = await cdp.send('Target.createTarget', { url: 'https://www.youtube.com/watch?v=aircAruvnKk' });
const page = await cdp.attach(targetId);
await cdp.send('Runtime.enable', {}, page);
for (let i = 0; i < 40; i++) {
  if (await cdp.evaluate(page, `!!document.querySelector('[data-vietdub=toggle]')`).catch(() => false)) break;
  await sleep(1000);
}
const tabId = await cdp.evaluate(swS, `chrome.tabs.query({url:'https://www.youtube.com/*'}).then(t=>t[0]?.id)`);
console.log('tabId', tabId);
console.log('direct ping:', await cdp.evaluate(swS, `chrome.tabs.sendMessage(${tabId}, {ns:'vietdub', type:'ping'}).then(()=> 'ok').catch(e=>'ERR '+e.message)`));
await cdp.evaluate(page, `document.querySelector('[data-vietdub=toggle]').click()`);
await sleep(8000);
console.log('storage:', await cdp.evaluate(swS, `chrome.storage.session.get('active').then(x=>JSON.stringify(x))`));
const off = (await cdp.targets()).find((t) => t.url.startsWith(ORIGIN + '/offscreen.html'));
if (off) {
  const offS = await cdp.attach(off.targetId);
  await cdp.send('Runtime.enable', {}, offS);
  console.log('offscreen relay test:', await cdp.evaluate(offS, `chrome.runtime.sendMessage({ns:'vietdub', type:'relay', tab_id:${tabId}, msg:{ns:'vietdub', type:'overlay.status', text:'probe', level:'info'}}).then(r=>'sent '+JSON.stringify(r)).catch(e=>'ERR '+e.message)`));
}
await sleep(1500);
console.log('direct captions.fetch:', await cdp.evaluate(swS, `chrome.tabs.sendMessage(${tabId}, {ns:'vietdub', type:'captions.fetch'}).then(()=> 'ok').catch(e=>'ERR '+e.message)`));
await sleep(12000);
console.log(logs.filter((l) => /vietdub|EXC/.test(l)).join('\n'));
cdp.close();
proc.kill();
process.exit(0);
