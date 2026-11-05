import { readFileSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CDP, freshProfile, launchChromePipe, sleep } from './cdp.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const HOME = 'D:/VietDubLocal';
const EXT_ID = JSON.parse(readFileSync(join(HOME, 'local-config.json'), 'utf8')).allowed_extension_ids[0];
const ORIGIN = `chrome-extension://${EXT_ID}`;
const { proc, info } = await launchChromePipe({ exe: 'C:/Program Files/Google/Chrome/Application/chrome.exe', profile: freshProfile(),
  extension: join(root, 'apps/extension/dist'), extraArgs: ['--disable-audio-output', '--autoplay-policy=no-user-gesture-required'] });
const cdp = await CDP.connect(info.webSocketDebuggerUrl);
const logs = [];
cdp.on((m) => {
  if (m.method === 'Runtime.consoleAPICalled') logs.push(`[${m.sessionId?.slice(0, 4)}] ${m.params.args.map((a) => a.value ?? a.description).join(' ').slice(0, 300)}`);
  if (m.method === 'Runtime.exceptionThrown') logs.push(`[${m.sessionId?.slice(0, 4)}] EXC ${(m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text).slice(0, 400)}`);
});
let sw = null;
for (let i = 0; i < 30 && !sw; i++) { sw = (await cdp.targets()).find((t) => t.type === 'service_worker' && t.url.startsWith(ORIGIN)); if (!sw) await sleep(300); }
const swS = await cdp.attach(sw.targetId);
await cdp.send('Runtime.enable', {}, swS);
for (let i = 0; i < 30; i++) { if (await cdp.evaluate(swS, 'typeof chrome !== "undefined" && !!chrome.runtime').catch(() => false)) break; await sleep(300); }
console.log('SW has fromExtensionPage code:', await cdp.evaluate(swS, `fetch(chrome.runtime.getURL('background.js')).then(r=>r.text()).then(t=>t.includes('startsWith(chrome.runtime.getURL(""))') + ' len=' + t.length)`));
const { targetId } = await cdp.send('Target.createTarget', { url: 'https://www.youtube.com/watch?v=aircAruvnKk' });
const page = await cdp.attach(targetId);
await cdp.send('Runtime.enable', {}, page);
for (let i = 0; i < 40; i++) { if (await cdp.evaluate(page, `!!document.querySelector('[data-vietdub=toggle]')`).catch(() => false)) break; await sleep(1000); }
const { targetId: pt } = await cdp.send('Target.createTarget', { url: `${ORIGIN}/sidepanel.html`, background: true });
const panel = await cdp.attach(pt);
await cdp.send('Runtime.enable', {}, panel);
await sleep(2000);
console.log('get_active:', await cdp.evaluate(panel, `chrome.runtime.sendMessage({ns:'vietdub', type:'panel.get_active'}).then(r=>JSON.stringify(r)).catch(e=>'ERR '+e.message)`));
await cdp.evaluate(page, `document.querySelector('[data-vietdub=toggle]').click()`);
await sleep(6000);
console.log('after toggle storage:', await cdp.evaluate(swS, `chrome.storage.session.get('active').then(x=>JSON.stringify(x))`));
console.log('contexts:', await cdp.evaluate(swS, `chrome.runtime.getContexts({}).then(c=>JSON.stringify(c.map(x=>x.contextType+':'+(x.documentUrl||'').slice(0,60))))`));
await sleep(35000);
console.log('after 35s contexts:', await cdp.evaluate(swS, `chrome.runtime.getContexts({}).then(c=>JSON.stringify(c.map(x=>x.contextType)))`));
console.log('storage:', await cdp.evaluate(swS, `chrome.storage.session.get('active').then(x=>JSON.stringify(x))`));
console.log('VDLOG:', (await cdp.evaluate(swS, `globalThis.__vdlog.join(' || ')`)));
console.log(logs.filter((l) => /vietdub|EXC/.test(l)).slice(-30).join('\n'));
cdp.close();
proc.kill();
process.exit(0);
