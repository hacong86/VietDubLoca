// E2E trên Chrome THẬT (hồ sơ riêng D:\VietDubLocal\e2e-profile, tắt tiếng) + YouTube thật + broker/GPU thật.
// node scripts/e2e_chrome.mjs [videoId] [--keep]
// Ghi báo cáo + ảnh chụp vào D:\VietDubLocal\e2e\<ts>\. Không đụng hồ sơ Chrome chính.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CDP, freshProfile, launchChromePipe, sleep } from './cdp.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const HOME = 'D:/VietDubLocal';
const EXT_ID = JSON.parse(readFileSync(join(HOME, 'local-config.json'), 'utf8')).allowed_extension_ids[0];
const ORIGIN = `chrome-extension://${EXT_ID}`;
const videoId = process.argv.find((a) => /^[A-Za-z0-9_-]{11}$/.test(a)) ?? 'aircAruvnKk';
const keep = process.argv.includes('--keep');
const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
const outDir = join(HOME, 'e2e', ts);
mkdirSync(outDir, { recursive: true });
const report = { video_id: videoId, started: new Date().toISOString(), chrome: null, steps: [], pass: {}, notes: [] };
const log = (step, data = {}) => {
  const e = { t: new Date().toISOString().slice(11, 23), step, ...data };
  report.steps.push(e);
  console.log(JSON.stringify(e));
};

// token riêng cho harness để đọc trạng thái broker (cùng origin extension; chỉ đọc)
async function brokerToken() {
  const st = JSON.parse(readFileSync(join(HOME, 'runtime/broker.json'), 'utf8'));
  const r = await fetch(`http://127.0.0.1:${st.port}/internal/pair`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-VietDub-Pairing': st.pairing_secret },
    body: JSON.stringify({ extension_origin: ORIGIN }) });
  const j = await r.json();
  return { base: `http://127.0.0.1:${st.port}`, tok: j.session_token };
}
async function broker(b, path) {
  const r = await fetch(b.base + path, { headers: { Authorization: `Bearer ${b.tok}`, Origin: ORIGIN } });
  return r.status === 204 ? null : r.json();
}

const { proc, info, loaded } = await launchChromePipe({ exe: 'C:/Program Files/Google/Chrome/Application/chrome.exe', profile: freshProfile(),
  extension: join(root, 'apps/extension/dist'), extraArgs: ['--disable-audio-output', '--autoplay-policy=no-user-gesture-required'] });
report.chrome = info.Browser;
log('load_unpacked', { result: loaded });
log('chrome', { browser: info.Browser });
const cdp = await CDP.connect(info.webSocketDebuggerUrl);
let exitCode = 0;
try {
  // 1. extension đã nạp?
  let sw = null;
  for (let i = 0; i < 20 && !sw; i++) {
    sw = (await cdp.targets()).find((t) => t.type === 'service_worker' && t.url.startsWith(ORIGIN));
    if (!sw) await sleep(500);
  }
  report.pass.extension_loaded = !!sw;
  report.sw_logs = [];
  if (sw) {
    const swLog = await cdp.attach(sw.targetId);
    cdp.on((m) => {
      if (m.sessionId !== swLog) return;
      if (m.method === 'Runtime.consoleAPICalled') report.sw_logs.push(m.params.args.map((a) => a.value ?? a.description).join(' ').slice(0, 300));
      if (m.method === 'Runtime.exceptionThrown') report.sw_logs.push('EXC ' + (m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text).slice(0, 300));
    });
    await cdp.send('Runtime.enable', {}, swLog);
  }
  log('extension', { loaded: !!sw, url: sw?.url });
  if (!sw) throw new Error('Extension không nạp được (Chrome có thể chặn --load-extension)');

  // 2. mở video
  const { targetId } = await cdp.send('Target.createTarget', { url: `https://www.youtube.com/watch?v=${videoId}` });
  const page = await cdp.attach(targetId);
  await cdp.send('Page.enable', {}, page);
  await cdp.send('Runtime.enable', {}, page);
  let ok = false;
  for (let i = 0; i < 60 && !ok; i++) {
    await sleep(1000);
    ok = await cdp.evaluate(page, `!!document.querySelector('video.html5-main-video') && !!document.querySelector('[data-vietdub=toggle]')`).catch(() => false);
  }
  log('page', { video_and_button: ok, url: await cdp.evaluate(page, 'location.href') });
  await cdp.screenshot(page, join(outDir, '01-page.png'));
  report.pass.in_page_button = ok;
  if (!ok) throw new Error('Không thấy video hoặc nút VI');
  await cdp.evaluate(page, `(async()=>{const v=document.querySelector('video.html5-main-video'); v.muted=false; try{await v.play()}catch(e){}; return v.paused})()`);
  // chờ quảng cáo (nếu có) kết thúc; không bấm bỏ qua
  for (let i = 0; i < 90; i++) {
    const ad = await cdp.evaluate(page, `document.getElementById('movie_player')?.classList.contains('ad-showing')`);
    if (!ad) break;
    if (i === 0) log('ad', { showing: true });
    await sleep(1000);
  }

  // 3. Bật tiếng Việt bằng nút trên player (luồng người dùng thật)
  const b = await brokerToken();
  const t0 = Date.now();
  await cdp.evaluate(page, `document.querySelector('[data-vietdub=toggle]').click()`);
  let snap = null;
  // Chờ nguồn phụ đề tự động; Chrome tự động hoá bị YouTube trả timedtext rỗng → dùng luồng "Nhập SRT/VTT" từ trang bảng bên.
  for (let i = 0; i < 25; i++) {
    await sleep(1000);
    snap = (await broker(b, '/v1/status')).session;
    if (snap?.source) break;
  }
  report.pass.youtube_captions_auto = !!snap?.source;
  log('auto_captions', { found: !!snap?.source, source: snap?.source ?? null });
  if (!snap?.source) {
    const cuesFile = join(HOME, 'e2e', 'subs', videoId, 'cues.json');
    const cues = JSON.parse(readFileSync(cuesFile, 'utf8'));
    const tabId = await cdp.evaluate(await cdp.attach(sw.targetId), `chrome.tabs.query({url:'https://www.youtube.com/*'}).then(t=>t[0]?.id)`);
    const { targetId: panelT } = await cdp.send('Target.createTarget', { url: `${ORIGIN}/sidepanel.html`, background: true });
    const panel = await cdp.attach(panelT);
    await sleep(1500);
    const payload = { source_id: 'import-e2e', source_kind: 'import', language: 'en', coverage: 'full',
      available_until_ms: cues.reduce((m, c) => Math.max(m, c.end_ms), 0), cues, offset_ms: 0, label: 'Tệp nhập: subs.en.vtt', tried: [] };
    const r = await cdp.evaluate(panel, `chrome.runtime.sendMessage({ ns: 'vietdub', type: 'panel.import_captions', tab_id: ${tabId}, payload: ${JSON.stringify(payload)} }).then(r => JSON.stringify(r))`);
    log('import', { cues: cues.length, result: r });
    await cdp.send('Target.activateTarget', { targetId });
  }
  for (let i = 0; i < 90; i++) {
    await sleep(1000);
    const st = await broker(b, '/v1/status');
    snap = st.session;
    if (snap && snap.video_id === videoId && snap.units > 0 && ['PLAYING', 'BUFFERING'].includes(snap.state) && snap.buffer_media_ms > 0) break;
  }
  log('sw_logs', { lines: report.sw_logs.slice(-15) });
  log('session', { after_ms: Date.now() - t0, state: snap?.state, units: snap?.units, source: snap?.source, buffer_ms: snap?.buffer_media_ms, consumer: snap?.audio_consumer });
  report.pass.session_started = !!snap && snap.units > 0;
  if (!snap) throw new Error('Không có phiên');
  report.pass.captions_found = !!snap?.source;

  // offscreen
  // offscreen có thể bị Chrome đóng khi im lặng rồi được dựng lại → luôn tìm target hiện tại
  let offCache = { id: null, s: null };
  const offEval = async (expr) => {
    const off = (await cdp.targets()).find((t) => t.url.startsWith(ORIGIN + '/offscreen.html'));
    if (!off) return null;
    if (offCache.id !== off.targetId) offCache = { id: off.targetId, s: await cdp.attach(off.targetId) };
    try { return await cdp.evaluate(offCache.s, expr); } catch { offCache = { id: null, s: null }; return null; }
  };
  report.pass.offscreen_created = (await offEval('1')) === 1;

  // 4. phát 25 s, đo: có tiếng Việt, drift
  await cdp.evaluate(page, `(()=>{document.querySelector('video.html5-main-video').play().catch(()=>{}); return true})()`);
  let spoke = false;
  for (let i = 0; i < 25; i++) {
    await sleep(1000);
    spoke = spoke || !!(await offEval('globalThis.__vietdub?.speaking()'));
    if (i === 8) await cdp.screenshot(page, join(outDir, '02-playing.png'));
  }
  const stats1 = await offEval('JSON.stringify(globalThis.__vietdub?.engine.stats)');
  const segs = await broker(b, `/v1/sessions/${snap.session_id}/segments`);
  const ready = segs.segments.filter((s) => s.status === 'ready');
  log('playback', { spoke, stats: stats1 && JSON.parse(stats1), ready: ready.length, blocked: segs.segments.filter((s) => s.status === 'blocked').length,
    sample: ready.slice(0, 4).map((s) => ({ en: s.source_text, vi: s.target_display, audio: s.audio })) });
  report.pass.vietnamese_audio_played = spoke;

  const volPlaying = await cdp.evaluate(page, `document.querySelector('video.html5-main-video').volume`);
  log('volume', { during_playback: volPlaying, expected: 0.15 });
  report.pass.original_volume_lowered = Math.abs(volPlaying - 0.15) < 0.02;

  // 5. PAUSE người dùng: dừng audio, không tự play
  await cdp.evaluate(page, `document.querySelector('video.html5-main-video').pause()`);
  await sleep(150);
  const spkPause = await offEval('globalThis.__vietdub?.speaking()');
  await sleep(3000);
  const stillPaused = await cdp.evaluate(page, `document.querySelector('video.html5-main-video').paused`);
  log('pause', { speaking_150ms_after: spkPause, video_still_paused_after_3s: stillPaused });
  report.pass.user_pause_stops_audio = spkPause === false;
  report.pass.user_pause_wins = stillPaused === true;

  // 6. tốc độ 1.5x (không tua) — tiếp tục đọc, giữ cao độ bằng WSOLA
  await cdp.evaluate(page, `(()=>{const v=document.querySelector('video.html5-main-video'); v.playbackRate=1.5; v.play().catch(()=>{}); return true})()`);
  let spoke15 = false;
  for (let i = 0; i < 15; i++) {
    await sleep(1000);
    spoke15 = spoke15 || !!(await offEval('globalThis.__vietdub?.speaking()'));
  }
  const stats15 = JSON.parse((await offEval('JSON.stringify(globalThis.__vietdub?.engine.stats)')) ?? '{}');
  log('rate', { rate: 1.5, spoke: spoke15, scheduled: stats15.scheduled, holds: stats15.holds });
  report.pass.rate_change_continues = spoke15;
  await cdp.evaluate(page, `document.querySelector('video.html5-main-video').playbackRate=1`);

  // 7. SEEK (cuối cùng: YouTube tự động hoá có thể báo lỗi phát sau khi tua)
  const epochBefore = (await broker(b, '/v1/status')).session.timeline_epoch;
  await cdp.evaluate(page, `(()=>{const v=document.querySelector('video.html5-main-video'); v.currentTime = v.currentTime + 45; return true})()`);
  await sleep(150);
  const speakingAfterSeek = await offEval('globalThis.__vietdub?.speaking()');
  await sleep(4000);
  const afterSeek = (await broker(b, '/v1/status')).session;
  const stats2 = JSON.parse((await offEval('JSON.stringify(globalThis.__vietdub?.engine.stats)')) ?? '{}');
  const ytError = await cdp.evaluate(page, `!!document.querySelector('.ytp-error')`);
  log('seek', { speaking_150ms_after: speakingAfterSeek, epoch_before: epochBefore, epoch_after: afterSeek.timeline_epoch, stop_latency_ms: stats2.last_stop_latency_ms, state: afterSeek.state, youtube_error: ytError });
  report.pass.seek_stops_audio = speakingAfterSeek === false;
  report.pass.seek_bumps_epoch = afterSeek.timeline_epoch > epochBefore;
  await sleep(8000);
  report.pass.speaks_after_seek = ytError ? 'NOT_TESTABLE_YT_ERROR' : !!(await offEval('globalThis.__vietdub?.engine.stats.scheduled')) ;
  await cdp.screenshot(page, join(outDir, '03-after-seek.png'));

  // 8. TẮT: không còn tiếng sau 150 ms, âm lượng gốc trả lại
  const volBefore = volPlaying;
  await cdp.evaluate(page, `document.querySelector('[data-vietdub=toggle]').click()`);
  await sleep(150);
  const spkOff = await offEval('globalThis.__vietdub?.speaking()');
  await sleep(1500);
  const volAfter = await cdp.evaluate(page, `document.querySelector('video.html5-main-video').volume`);
  const stOff = await broker(b, '/v1/status');
  log('toggle_off', { speaking_150ms_after: spkOff, volume_during: volBefore, volume_after: volAfter, session: stOff.session?.state ?? null });
  report.pass.off_stops_audio = spkOff === false || spkOff === null;
  report.pass.volume_restored = volAfter > volBefore;
  await cdp.screenshot(page, join(outDir, '04-off.png'));
} catch (e) {
  exitCode = 1;
  report.error = String(e.stack ?? e);
  console.error(e);
} finally {
  report.finished = new Date().toISOString();
  writeFileSync(join(outDir, 'report.json'), JSON.stringify(report, null, 2));
  console.log('REPORT', join(outDir, 'report.json'), JSON.stringify(report.pass));
  cdp.close();
  if (!keep) proc.kill();
}
process.exit(exitCode);
