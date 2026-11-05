// Client CDP tối giản (Node 22 có WebSocket toàn cục) — không thêm dependency cho E2E.
import { spawn } from 'node:child_process';
import { mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.handlers = [];
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) {
        const { resolve, reject, timer } = this.pending.get(m.id);
        clearTimeout(timer);
        this.pending.delete(m.id);
        if (m.error) reject(new Error(m.error.message));
        else resolve(m.result);
      } else if (m.method) {
        for (const h of this.handlers) h(m);
      }
    };
  }
  static async connect(url) {
    const ws = new WebSocket(url);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    return new CDP(ws);
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); reject(new Error('CDP timeout ' + method)); } }, 60000);
      this.pending.set(id, { resolve, reject, timer });
    });
  }
  on(h) { this.handlers.push(h); }
  async attach(targetId) {
    const { sessionId } = await this.send('Target.attachToTarget', { targetId, flatten: true });
    return sessionId;
  }
  async evaluate(sessionId, expression, awaitPromise = true) {
    const r = await this.send('Runtime.evaluate', { expression, awaitPromise, returnByValue: true }, sessionId);
    if (r.exceptionDetails) throw new Error('eval: ' + (r.exceptionDetails.exception?.description ?? r.exceptionDetails.text));
    return r.result.value;
  }
  async screenshot(sessionId, file) {
    const r = await this.send('Page.captureScreenshot', { format: 'png' }, sessionId);
    mkdirSync(file.replace(/[\\/][^\\/]+$/, ''), { recursive: true });
    writeFileSync(file, Buffer.from(r.data, 'base64'));
    return file;
  }
  async targets() {
    return (await this.send('Target.getTargets')).targetInfos;
  }
  close() { try { this.ws.close(); } catch { /* */ } }
}

export async function launchChrome({ exe, profile, extension, port = 9333, extraArgs = [] }) {
  const args = [`--user-data-dir=${profile}`, `--remote-debugging-port=${port}`, '--no-first-run', '--no-default-browser-check',
    '--disable-features=DisableLoadExtensionCommandLineSwitch', `--load-extension=${extension}`, '--window-size=1400,900', ...extraArgs, 'about:blank'];
  const proc = spawn(exe, args, { stdio: 'ignore', detached: false });
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (r.ok) return { proc, info: await r.json() };
    } catch { /* chờ */ }
    await sleep(500);
  }
  throw new Error('Chrome không mở cổng debug');
}

/** Chrome ≥137 bỏ --load-extension: nạp extension qua CDP pipe (Extensions.loadUnpacked). */
export async function launchChromePipe({ exe, profile, extension, port = 9333, extraArgs = [] }) {
  const args = [`--user-data-dir=${profile}`, '--remote-debugging-pipe', `--remote-debugging-port=${port}`, '--enable-unsafe-extension-debugging',
    '--no-first-run', '--no-default-browser-check', '--window-size=1400,900', ...extraArgs, 'about:blank'];
  const proc = spawn(exe, args, { stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'] });
  const toChrome = proc.stdio[3];
  const fromChrome = proc.stdio[4];
  let buf = '';
  const waiters = new Map();
  let id = 0;
  fromChrome.on('data', (d) => {
    buf += d.toString('utf8');
    let i;
    while ((i = buf.indexOf('\0')) >= 0) {
      const msg = JSON.parse(buf.slice(0, i));
      buf = buf.slice(i + 1);
      if (msg.id && waiters.has(msg.id)) { waiters.get(msg.id)(msg); waiters.delete(msg.id); }
    }
  });
  const pipeSend = (method, params = {}) => new Promise((res) => {
    const mid = ++id;
    waiters.set(mid, res);
    toChrome.write(JSON.stringify({ id: mid, method, params }) + '\0');
  });
  const loaded = await pipeSend('Extensions.loadUnpacked', { path: extension });
  let info = null;
  for (let i = 0; i < 60 && !info; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (r.ok) info = await r.json();
    } catch { /* chờ */ }
    if (!info) await sleep(500);
  }
  return { proc, info, loaded, pipeSend };
}

/** Hồ sơ Chrome thử nghiệm MỚI mỗi lần chạy (tránh service worker cũ bị cache); chỉ dọn thư mục do harness tạo. */
export function freshProfile(base = 'D:/VietDubLocal/e2e/profiles') {
  mkdirSync(base, { recursive: true });
  for (const d of readdirSync(base)) if (/^p-\d+$/.test(d)) { try { rmSync(`${base}/${d}`, { recursive: true, force: true }); } catch { /* đang bị khóa */ } }
  const dir = `${base}/p-${Date.now()}`;
  mkdirSync(dir, { recursive: true });
  return dir;
}
