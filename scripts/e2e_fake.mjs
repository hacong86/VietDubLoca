// E2E TẤT ĐỊNH: Chrome thật + extension thật + broker/GPU thật, trên trang YouTube GIẢ LẬP (CDP Fetch chặn www.youtube.com).
// Lý do: YouTube thật chặn phụ đề/luồng video với Chrome tự động hoá (chống bot) → không kiểm được seek/pause lặp lại.
// node scripts/e2e_fake.mjs   → D:\VietDubLocal\e2e\fake-<ts>\report.json + ảnh
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CDP, freshProfile, launchChromePipe, sleep } from './cdp.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const HOME = 'D:/VietDubLocal';
const FIX = join(HOME, 'e2e', 'fixtures');
const EXT_ID = JSON.parse(readFileSync(join(HOME, 'local-config.json'), 'utf8')).allowed_extension_ids[0];
const ORIGIN = `chrome-extension://${EXT_ID}`;
const VID = 'VDfakeTest1';
const VID2 = 'VDfakeTest2';
const video = readFileSync(join(FIX, 'fake.mp4'));
const json3 = readFileSync(join(FIX, 'fake.json3.json'), 'utf8').replace(/^\uFEFF/, '');
const sentences = JSON.parse(readFileSync(join(FIX, 'sentences.json'), 'utf8').replace(/^\uFEFF/, ''));
const html = readFileSync(join(root, 'scripts', 'fake_youtube.html'), 'utf8');
const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
const outDir = join(HOME, 'e2e', `fake-${ts}`);
mkdirSync(outDir, { recursive: true });
const report = { kind: 'fake_youtube_deterministic', started: new Date().toISOString(), steps: [], pass: {} };
const log = (step, data = {}) => { const e = { t: new Date().toISOString().slice(11, 23), step, ...data }; report.steps.push(e); console.log(JSON.stringify(e)); };

async function brokerToken() {
  const st = JSON.parse(readFileSync(join(HOME, 'runtime/broker.json'), 'utf8'));
  const r = await fetch(`http://127.0.0.1:${st.port}/internal/pair`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-VietDub-Pairing': st.pairing_secret },
    body: JSON.stringify({ extension_origin: ORIGIN }) });
  return { base: `http://127.0.0.1:${st.port}`, tok: (await r.json()).session_token };
}
const broker = async (b, path) => (await fetch(b.base + path, { headers: { Authorization: `Bearer ${b.tok}`, Origin: ORIGIN } })).json();

const { proc, info } = await launchChromePipe({ exe: 'C:/Program Files/Google/Chrome/Application/chrome.exe', profile: freshProfile(),
  extension: join(root, 'apps/extension/dist'), extraArgs: ['--disable-audio-output', '--autoplay-policy=no-user-gesture-required'] });
const cdp = await CDP.connect(info.webSocketDebuggerUrl);
let code = 0;
let restoreUserMode = null;   // trả lại chế độ người dùng kể cả khi test lỗi
try {
  let sw = null;
  for (let i = 0; i < 30 && !sw; i++) { sw = (await cdp.targets()).find((t) => t.type === 'service_worker' && t.url.startsWith(ORIGIN)); if (!sw) await sleep(300); }
  const swS = await cdp.attach(sw.targetId);
  // --- trang giả lập qua Fetch
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const page = await cdp.attach(targetId);
  await cdp.send('Runtime.enable', {}, page);
  await cdp.send('Page.enable', {}, page);
  await cdp.send('Fetch.enable', { patterns: [{ urlPattern: 'https://www.youtube.com/*', requestStage: 'Request' }] }, page);
  const b64 = (s) => Buffer.from(s).toString('base64');
  const fakePages = new Set([page]);
  cdp.on(async (m) => {
    if (m.method !== 'Fetch.requestPaused' || !fakePages.has(m.sessionId)) return;
    const pg = m.sessionId;
    const { requestId, request } = m.params;
    const u = new URL(request.url);
    const ok = (body, type, status = 200, extra = []) => cdp.send('Fetch.fulfillRequest', { requestId, responseCode: status,
      responseHeaders: [{ name: 'Content-Type', value: type }, { name: 'Cache-Control', value: 'no-store' }, ...extra], body: Buffer.isBuffer(body) ? body.toString('base64') : b64(body) }, pg).catch(() => {});
    if (u.pathname === '/watch') {
      const vid = u.searchParams.get('v') ?? VID;
      return ok(html.replaceAll('__VID__', vid).replaceAll('__TITLE__', `VietDub fake lesson ${vid}`), 'text/html; charset=utf-8');
    }
    if (u.pathname === '/__vietdub_fake/video.mp4') {
      const range = /bytes=(\d+)-(\d*)/.exec(request.headers.Range ?? request.headers.range ?? '');
      if (range) {
        const start = Number(range[1]);
        const end = range[2] ? Math.min(Number(range[2]), video.length - 1) : Math.min(start + 2 * 1024 * 1024 - 1, video.length - 1);
        return ok(video.subarray(start, end + 1), 'video/mp4', 206, [{ name: 'Content-Range', value: `bytes ${start}-${end}/${video.length}` }, { name: 'Accept-Ranges', value: 'bytes' }]);
      }
      return ok(video, 'video/mp4', 200, [{ name: 'Accept-Ranges', value: 'bytes' }]);
    }
    if (u.pathname === '/api/timedtext') {
      // như YouTube 2026: không có pot → rỗng; có pot (player tự gọi) → json3
      return ok(u.searchParams.get('pot') ? json3 : '', 'application/json; charset=utf-8');
    }
    return ok('', 'text/plain', 404);
  });
  await cdp.send('Page.navigate', { url: `https://www.youtube.com/watch?v=${VID}` }, page);
  const ev = (expr) => cdp.evaluate(page, expr);
  for (let i = 0; i < 30; i++) { if (await ev(`!!document.querySelector('[data-vietdub=toggle]')`).catch(() => false)) break; await sleep(500); }
  report.pass.in_page_button = await ev(`!!document.querySelector('[data-vietdub=toggle]')`);
  let offCache = { id: null, s: null };
  const off = async (expr) => {
    const t = (await cdp.targets()).find((x) => x.url.startsWith(ORIGIN + '/offscreen.html'));
    if (!t) return null;
    if (offCache.id !== t.targetId) {
      if (offCache.id) { report.offscreen_replaced = (report.offscreen_replaced ?? 0) + 1; log('offscreen_replaced', { after_step: report.steps.at(-1)?.step }); }
      offCache = { id: t.targetId, s: await cdp.attach(t.targetId) };
    }
    try { return await cdp.evaluate(offCache.s, expr); } catch { offCache = { id: null, s: null }; return null; }
  };
  const speaking = () => off('globalThis.__vietdub?.speaking()');
  const stats = async () => JSON.parse((await off('JSON.stringify(globalThis.__vietdub?.engine.stats)')) ?? '{}');
  const b = await brokerToken();
  const sess = async () => (await broker(b, '/v1/status')).session;
  // Cài đặt NGƯỜI DÙNG đang lưu (harness dùng chung data root): so sánh theo đó, và trả lại chế độ cũ khi xong
  const userSettings = (await broker(b, '/v1/settings')).value;
  const userGain = Number(userSettings.playback.original_gain ?? 0.15);
  const userMode = String(userSettings.playback.mode ?? 'vod_sync');
  log('user_settings', { original_gain: userGain, mode: userMode, auto_hold_vod: userSettings.playback.auto_hold_vod });
  const putSettings = (value) => fetch(b.base + '/v1/settings', { method: 'PUT', headers: { Authorization: `Bearer ${b.tok}`, Origin: ORIGIN, 'Content-Type': 'application/json' }, body: JSON.stringify({ value }) });
  await putSettings({ playback: { mode: 'vod_sync' } });   // test tất định: luôn bắt đầu ở Đồng bộ
  restoreUserMode = () => putSettings({ playback: { mode: userMode } });

  // T0: bật VI khi video ĐANG CHẠY → "Đang chuẩn bị thuyết minh" (video tạm dừng, có %) → TỰ phát khi đủ, không cần bấm
  await ev(`(()=>{const v=document.querySelector('video'); v.currentTime=0; v.play().catch(()=>{}); return true})()`);
  await sleep(800);
  // mở bảng bên (tab nền) trước khi bật để chụp được thanh chuẩn bị ở cả video và bảng bên
  const { targetId: pt0 } = await cdp.send('Target.createTarget', { url: `${ORIGIN}/sidepanel.html`, background: true });
  const ps0 = await cdp.attach(pt0);
  await cdp.send('Runtime.enable', {}, ps0);
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 400, height: 900, deviceScaleFactor: 1, mobile: false }, ps0);
  await sleep(1500);
  const t0 = Date.now();
  await ev(`document.querySelector('[data-vietdub=toggle]').click()`);
  const pcts = [];
  let sawPreloadPaused = false, autoPlayed = false, shot = false;
  for (let i = 0; i < 400 && !autoPlayed; i++) {
    await sleep(150);
    const pre = await off('JSON.stringify(globalThis.__vietdub?.engine.preload ?? null)');
    const paused = await ev(`document.querySelector('video').paused`);
    if (pre && pre !== 'null') {
      const pj = JSON.parse(pre);
      if (paused) sawPreloadPaused = true;
      if (pj.lastPct >= 0 && pcts.at(-1) !== pj.lastPct) pcts.push(Math.round(pj.lastPct * 100));
      if (!shot) { await Promise.all([cdp.screenshot(page, join(outDir, 'T0-preload.png')), cdp.screenshot(ps0, join(outDir, 'T0-preload-panel.png'))]); shot = true; }
    } else if (sawPreloadPaused && !paused) autoPlayed = true;
  }
  await cdp.send('Target.closeTarget', { targetId: pt0 });
  log('T0_preload', { wait_ms: Date.now() - t0, saw_paused_while_preparing: sawPreloadPaused, auto_played: autoPlayed, pct_steps: pcts.slice(0, 30) });
  report.pass.T0_preload_pauses_and_shows_progress = sawPreloadPaused && pcts.length >= 1;
  report.pass.T0_preload_auto_plays_without_click = autoPlayed;

  // T1: phụ đề tự lấy qua bridge (bắt body XHR của player)
  let s = null;
  for (let i = 0; i < 60; i++) { await sleep(1000); s = await sess(); if (s?.source && s.units > 0 && s.buffer_media_ms > 8000) break; }
  log('T1_captions', { after_ms: Date.now() - t0, source: s?.source, units: s?.units, buffer_ms: s?.buffer_media_ms, state: s?.state });
  report.pass.T1_auto_captions_via_player_capture = s?.source?.source_kind === 'manual' && s.units >= 14;
  const cc = await ev(`document.querySelector('.ytp-subtitles-button').getAttribute('aria-pressed')`);
  report.pass.T1_cc_state_restored = cc === 'false';
  const btnInfo = await ev(`(()=>{const b=document.querySelector('[data-vietdub=toggle]'); return JSON.stringify({src:b.dataset.source, title:b.title, color:b.style.color})})()`);
  log('T1_source_badge', JSON.parse(btnInfo));
  report.pass.T1_source_quality_on_button = JSON.parse(btnInfo).src === 'manual' && JSON.parse(btnInfo).title.includes('Phụ đề của tác giả');

  // T2: phát từ đầu, đo có tiếng Việt + onset/drift + âm lượng gốc
  await ev(`(()=>{const v=document.querySelector('video'); v.currentTime=0; v.play().catch(()=>{}); return true})()`);
  await sleep(1500);
  let spoke = 0;
  for (let i = 0; i < 20; i++) { await sleep(1000); if (await speaking()) spoke++; if (i === 8) await cdp.screenshot(page, join(outDir, 'T2-overlay.png')); }
  const st2 = await stats();
  const vol = await ev(`document.querySelector('video').volume`);
  log('T2_playback', { spoke_seconds: spoke, stats: st2, video_volume: vol, t: await ev(`document.querySelector('video').currentTime`) });
  report.pass.T2_vietnamese_audio = spoke >= 5;
  report.pass.T2_original_volume_as_setting = Math.abs(vol - userGain) < 0.02;

  // Ảnh bảng bên khi có phiên (tab nền để YouTube vẫn là tab đang xem)
  {
    const { targetId: pt } = await cdp.send('Target.createTarget', { url: `${ORIGIN}/sidepanel.html`, background: true });
    const ps = await cdp.attach(pt);
    await cdp.send('Runtime.enable', {}, ps);
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 400, height: 1000, deviceScaleFactor: 1, mobile: false }, ps);
    await sleep(2500);
    await cdp.screenshot(ps, join(outDir, 'P1-watch.png'));
    await cdp.evaluate(ps, `(()=>{[...document.querySelectorAll('nav.tabs button')].find(b=>b.textContent==='Bản dịch')?.click(); return true})()`);
    await sleep(2500);
    await cdp.screenshot(ps, join(outDir, 'P2-transcript.png'));
    await cdp.send('Target.closeTarget', { targetId: pt });
  }

  // T0b: thanh chuẩn bị trong BẢNG BÊN + bấm nút "Xem luôn" thật → hết chuẩn bị, video tự phát
  {
    const { targetId: pt } = await cdp.send('Target.createTarget', { url: `${ORIGIN}/sidepanel.html`, background: true });
    const ps = await cdp.attach(pt);
    await cdp.send('Runtime.enable', {}, ps);
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 400, height: 900, deviceScaleFactor: 1, mobile: false }, ps);
    await sleep(2000);
    // mục tiêu rất lớn để trạng thái chuẩn bị kéo dài đủ lâu cho ảnh chụp + thao tác
    await off(`(()=>{const e=globalThis.__vietdub.engine; e.applySettings({ preload_target_ms: 600000 }); e.sourceComplete=false; e.beginPreload('start'); return true})()`);
    await sleep(2500);
    const pausedDuring = await ev(`document.querySelector('video').paused`);
    await cdp.screenshot(ps, join(outDir, 'T0b-preload-panel.png'));
    const clicked = await cdp.evaluate(ps, `(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='Xem luôn'); b?.click(); return !!b})()`);
    await sleep(1500);
    const preAfter = await off('globalThis.__vietdub.engine.preload === null');
    const playingAfter = !(await ev(`document.querySelector('video').paused`));
    await off(`(()=>{globalThis.__vietdub.engine.applySettings({ preload_target_ms: 30000 }); return true})()`);
    await cdp.send('Target.closeTarget', { targetId: pt });
    log('T0b_panel_skip', { paused_during: pausedDuring, clicked, preload_cleared: preAfter, video_playing_after: playingAfter });
    report.pass.T0b_panel_shows_skip_button = clicked === true && pausedDuring === true;
    report.pass.T0b_skip_resumes_video = preAfter === true && playingAfter === true;
  }

  // T3: pause người dùng → dừng ≤150 ms, không tự play; T4: play → nói tiếp
  await ev(`document.querySelector('video').pause()`);
  await sleep(150);
  const spkP = await speaking();
  await sleep(2500);
  const stillP = await ev(`document.querySelector('video').paused`);
  await ev(`document.querySelector('video').play().then(()=>true)`);
  let resumed = false;
  for (let i = 0; i < 8 && !resumed; i++) { await sleep(700); resumed = !!(await speaking()); }
  log('T3_T4_pause_resume', { speaking_150ms: spkP, still_paused_3s: stillP, resumed_speaking: resumed });
  report.pass.T3_pause_stops_audio_150ms = spkP === false;
  report.pass.T3_user_pause_wins = stillP === true;
  report.pass.T4_resume_speaks = resumed;

  // T5: seek tới câu 8 → stop ≤150 ms, epoch tăng, audio tiếp theo epoch mới
  const ep0 = (await sess()).timeline_epoch;
  const target = sentences[7].start_ms / 1000 - 1.0;
  await ev(`(()=>{document.querySelector('video').currentTime=${target}; return true})()`);
  await sleep(150);
  const spkS = await speaking();
  let s5 = null, spokeAfter = false;
  for (let i = 0; i < 12; i++) { await sleep(700); s5 = await sess(); if (await speaking()) spokeAfter = true; if (s5.timeline_epoch > ep0 && spokeAfter) break; }
  const st5 = await stats();
  log('T5_seek', { speaking_150ms: spkS, epoch_before: ep0, epoch_after: s5.timeline_epoch, spoke_after: spokeAfter, stop_latency_ms: st5.last_stop_latency_ms });
  report.pass.T5_seek_stops_150ms = spkS === false;
  report.pass.T5_seek_bumps_epoch = s5.timeline_epoch > ep0;
  report.pass.T5_speaks_after_seek = spokeAfter;

  // T6: tua nhanh 3 lần (SYS-01) → epoch cuối thắng, không phát audio epoch cũ
  const epA = (await sess()).timeline_epoch;
  for (const sec of [60, 10, 30]) { await ev(`(()=>{document.querySelector('video').currentTime=${sec}; return true})()`); await sleep(120); }
  await sleep(5000);
  const s6 = await sess();
  const engEpoch = await off('globalThis.__vietdub.engine.epoch');
  log('T6_rapid_seeks', { epoch_before: epA, broker_epoch: s6.timeline_epoch, engine_epoch: engEpoch, stale_dropped: (await broker(b, '/v1/diagnostics/preview')).metrics?.stale_dropped });
  report.pass.T6_final_epoch_wins = s6.timeline_epoch >= epA + 3 && engEpoch === s6.timeline_epoch;

  // T7: tốc độ 1.5x → vẫn đọc (WSOLA giữ cao độ)
  await ev(`(()=>{const v=document.querySelector('video'); v.currentTime=${sentences[2].start_ms / 1000 - 0.5}; v.playbackRate=1.5; v.play(); return true})()`);
  let spoke15 = 0;
  for (let i = 0; i < 12; i++) { await sleep(1000); if (await speaking()) spoke15++; }
  log('T7_rate_1_5', { spoke_seconds: spoke15, stats: await stats() });
  report.pass.T7_rate_change_speaks = spoke15 >= 3;
  await ev(`document.querySelector('video').playbackRate=1`);

  // T8: quảng cáo giả (lớp ad-showing) → AD_HOLD, im tiếng Việt, trả âm lượng gốc; hết QC → tiếp tục
  await ev(`document.getElementById('movie_player').classList.add('ad-showing'); true`);
  await sleep(1500);
  const s8 = await sess();
  const spk8 = await speaking();
  const vol8 = await ev(`document.querySelector('video').volume`);
  await ev(`document.getElementById('movie_player').classList.remove('ad-showing'); true`);
  await sleep(2500);
  const s8b = await sess();
  log('T8_ad', { state_during: s8.state, speaking_during: spk8, volume_during_ad: vol8, state_after: s8b.state });
  report.pass.T8_ad_hold = s8.state === 'AD_HOLD' && spk8 === false;
  report.pass.T8_ad_original_volume = vol8 > 0.9;
  report.pass.T8_resumes_after_ad = s8b.state !== 'AD_HOLD';

  // T11: Học kỹ (FR-029) — bấm nút THẬT trong bảng bên; video tự dừng cuối câu để đọc hết rồi tự chạy tiếp
  {
    await sleep(3000);
    const { targetId: pt } = await cdp.send('Target.createTarget', { url: `${ORIGIN}/sidepanel.html`, background: true });
    const ps = await cdp.attach(pt);
    await cdp.send('Runtime.enable', {}, ps);
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 400, height: 1000, deviceScaleFactor: 1, mobile: false }, ps);
    await sleep(2500);
    const clickMode = (label) => cdp.evaluate(ps, `(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()===${JSON.stringify(label)}); b?.click(); return !!b})()`);
    const clicked = await clickMode('Học kỹ');
    await sleep(1500);
    await cdp.screenshot(ps, join(outDir, 'P3-study.png'));
    const modeBroker = (await sess())?.mode;
    const modeEngine = await off('globalThis.__vietdub.engine.mode');
    // T12: sửa cách đọc (override) câu 3 thành câu dài ~3 lần khung thời gian → buộc Học kỹ phải dừng hình
    const api = async (method, path, body, headers = {}) => {
      const r = await fetch(b.base + path, { method, headers: { Authorization: `Bearer ${b.tok}`, Origin: ORIGIN, 'Content-Type': 'application/json', ...headers }, body: body ? JSON.stringify(body) : undefined });
      return { status: r.status, json: await r.json().catch(() => null) };
    };
    const sid = (await sess()).session_id;
    const segs = (await broker(b, `/v1/sessions/${sid}/segments`)).segments;
    const seg0 = segs.find((x) => x.start_ms <= sentences[2].start_ms + 50 && sentences[2].start_ms < x.end_ms);
    // dọn bản sửa còn sót từ lượt test trước (dữ liệu dùng chung) → luôn bắt đầu từ bản máy dịch
    for (let i = 0; i < 20; i++) if ((await api('POST', `/v1/segments/${seg0.segment_id}/undo`)).status !== 200) break;
    const seg = (await broker(b, `/v1/sessions/${sid}/segments`)).segments.find((x) => x.segment_id === seg0.segment_id);
    const longSpoken = `${seg.target_spoken} Nhắc lại một lần nữa cho rõ: mở bảng Inspector, tìm mục Apply Root Motion và bỏ dấu chọn ở ô đó trước khi chạy thử nhân vật của bạn.`;
    const conflict = await api('PATCH', `/v1/segments/${seg.segment_id}`, { target_display: seg.target_display, target_spoken: longSpoken }, { 'If-Match': String(seg.revision + 5) });
    const patched = await api('PATCH', `/v1/segments/${seg.segment_id}`, { target_display: seg.target_display, target_spoken: longSpoken }, { 'If-Match': String(seg.revision) });
    let segAfter = null;
    for (let i = 0; i < 40; i++) { await sleep(500); segAfter = (await broker(b, `/v1/sessions/${sid}/segments`)).segments.find((x) => x.segment_id === seg.segment_id); if (segAfter?.audio === 'ready') break; }
    log('T12_override', { segment: seg.segment_id, rev_before: seg.revision, conflict_status: conflict.status, conflict_code: conflict.json?.code ?? conflict.json?.error?.code,
      patch_status: patched.status, rev_after: segAfter?.revision, override: segAfter?.override, flags: segAfter?.flags, audio: segAfter?.audio });
    report.pass.T12_override_conflict_409 = conflict.status === 409;
    report.pass.T12_override_saved_new_revision = patched.status === 200 && segAfter?.revision > seg.revision && segAfter?.override === true && segAfter?.target_spoken === longSpoken;
    const holds0 = (await stats()).holds ?? 0;
    await ev(`(()=>{const v=document.querySelector('video'); v.currentTime=${sentences[2].start_ms / 1000 - 0.5}; v.play(); return true})()`);
    let sawHold = false, autoResumed = false, pausedSamples = 0, spokeStudy = 0; const trace = [];
    for (let i = 0; i < 100; i++) {
      await sleep(250);
      const h = await off('JSON.stringify(globalThis.__vietdub.engine.hold)');
      const paused = await ev(`document.querySelector('video').paused`);
      if (await speaking()) spokeStudy++;
      if (h && h !== 'null' && JSON.parse(h).reason === 'AUTO_SENTENCE' && paused) { sawHold = true; pausedSamples++; }
      else if (sawHold && !paused) autoResumed = true;
      if (i % 6 === 0) {
        trace.push(JSON.parse(await off(`JSON.stringify((()=>{const e=globalThis.__vietdub.engine; const it=e.items.get(${JSON.stringify(seg.segment_id)}); const sg=e.segments.get(${JSON.stringify(seg.segment_id)});
          return {off:location.href.slice(-6)+":"+(globalThis.__vdBoot ??= Date.now()), hold:e.hold, userPaused:e.userPaused, mode:e.mode, epoch:e.epoch, playing:e.anchor.playing, media:Math.round(e.anchor.mediaMs), holds:e.stats.holds,
            item: it ? {rev:it.revision, complete:it.complete, dur:it.duration_ms, epoch:it.epoch} : null, seg: sg ? {st:sg.status, start:sg.start_ms, end:sg.end_ms} : null, nplaying:e.playing.length}})())`) ?? 'null'));
      }
      if (sawHold && autoResumed && i > 40) break;
    }
    const holds1 = (await stats()).holds ?? 0;
    const segsStudy = (await broker(b, `/v1/sessions/${(await sess()).session_id}/segments`)).segments ?? [];
    log('T11_study_mode', { clicked, mode_broker: modeBroker, mode_engine: modeEngine, holds_before: holds0, holds_after: holds1,
      saw_auto_sentence_hold: sawHold, paused_samples_250ms: pausedSamples, trace, auto_resumed: autoResumed, speaking_samples: spokeStudy, segments: segsStudy.length });
    report.pass.T11_study_mode_set_from_panel = clicked && modeBroker === 'study' && modeEngine === 'study';
    report.pass.T11_study_holds_to_finish_sentence = sawHold && holds1 > holds0;
    report.pass.T11_study_auto_resumes = autoResumed;
    // T11b (AT-029-B): đang giữ hình Học kỹ mà người dùng tự pause → KHÔNG tự chạy lại sau khi đọc xong
    await ev(`(()=>{const v=document.querySelector('video'); v.currentTime=${sentences[2].start_ms / 1000 - 0.5}; v.play(); return true})()`);
    let heldB = false;
    for (let i = 0; i < 60 && !heldB; i++) {
      await sleep(250);
      const h = await off('JSON.stringify(globalThis.__vietdub.engine.hold)');
      heldB = !!h && h !== 'null' && JSON.parse(h).reason === 'AUTO_SENTENCE';
    }
    if (heldB) { await sleep(2000); await ev(`document.querySelector('video').dispatchEvent(new Event('pause')); true`); }   // người dùng bấm tạm dừng (ngoài cửa sổ 1,5 s của lệnh app)
    let quiet = 0;
    for (let i = 0; i < 60 && quiet < 12; i++) { await sleep(500); quiet = (await speaking()) ? 0 : quiet + 1; }
    await sleep(2000);
    const stillPausedB = await ev(`document.querySelector('video').paused`);
    const userPausedB = await off('globalThis.__vietdub.engine.userPaused');
    log('T11b_user_pause_during_hold', { held: heldB, video_still_paused: stillPausedB, engine_user_paused: userPausedB });
    report.pass.T11b_user_pause_beats_study_resume = heldB && stillPausedB === true && userPausedB === true;
    await ev(`document.querySelector('video').play().then(()=>true)`);
    // T15: Đồng bộ + câu tiếng Việt dài hơn khung, câu sau sát ngay → không bao giờ 2 giọng; trễ quá ~3 s → dừng
    //      một nhịp "Đang bắt kịp" rồi TỰ phát lại; không bỏ câu sau.
    await clickMode('Đồng bộ theo phụ đề');
    await sleep(1000);
    await ev(`(()=>{const v=document.querySelector('video'); v.currentTime=${sentences[2].start_ms / 1000 - 0.5}; v.play(); return true})()`);
    let maxConc = 0, spokeB = false, sawCatchup = false, pausedAfterCatchup = 0, holdsOther = new Set(); const tr15 = [];
    for (let i = 0; i < 140; i++) {
      await sleep(100);
      const st = JSON.parse(await off(`JSON.stringify((()=>{const e=globalThis.__vietdub.engine; const t=e.ctx.currentTime; return {c:e.playing.filter(p=>p.when<=t&&t<p.endAt).length, h:e.hold?.reason??null, m:Math.round(e.anchor.mediaMs)}})())`) ?? '{}');
      if (i % 10 === 0) tr15.push(await off(`JSON.stringify((()=>{const e=globalThis.__vietdub.engine; return {m:Math.round(e.anchor.mediaMs), ap:e.anchor.playing, pre:e.preload?Math.round(e.preload.lastPct*100):null, ep:e.epochPending, h:e.hold?.reason??null, up:e.userPaused, ch:e.chained.size, pl:e.playing.length, mode:e.mode}})())`) + ' vpaused=' + (await ev(`document.querySelector('video').paused`)));
      if (st.c > maxConc) maxConc = st.c;
      if (st.h === 'CATCHUP') sawCatchup = true; else if (st.h) holdsOther.add(st.h);
      if (st.m > sentences[3].start_ms && (await speaking())) spokeB = true;
      if (sawCatchup && !st.h && (await ev(`document.querySelector('video').paused`))) pausedAfterCatchup++;
    }
    const pausedEnd = await ev(`document.querySelector('video').paused`);
    const t15 = { trace: tr15, max_concurrent: maxConc, saw_catchup_hold: sawCatchup, other_holds: [...holdsOther], spoke_next_sentence: spokeB, video_paused_at_end: pausedEnd, overlap_prevented: await off('globalThis.__vietdub.engine.stats.overlap_prevented') };
    log('T15_vod_no_overlap_catchup', t15);
    report.pass.T15_never_two_voices = maxConc <= 1;
    report.pass.T15_next_sentence_not_skipped = spokeB;
    report.pass.T15_catchup_auto_resumes_no_click = sawCatchup && pausedEnd === false && pausedAfterCatchup <= 2;
    report.pass.T15_vod_no_per_sentence_hold = holdsOther.size === 0;
    // giọng của bản sửa chỉ tạo khi câu vào vùng sắp phát (không tổng hợp câu đã qua) → kiểm SAU khi phát lại câu đó
    const segPlayed = (await broker(b, `/v1/sessions/${sid}/segments`)).segments.find((x) => x.segment_id === seg.segment_id);
    log('T12_override_audio', { rev: segPlayed?.revision, audio: segPlayed?.audio, audio_ms: segPlayed?.audio_ms });
    report.pass.T12_override_audio_regenerated = segPlayed?.revision === segAfter?.revision && segPlayed?.audio === 'ready' && segPlayed.audio_ms > 6000;
    // T12b: hoàn tác bản sửa → về bản máy dịch, revision tăng tiếp, audio tạo lại
    const undo = await api('POST', `/v1/segments/${seg.segment_id}/undo`);
    const undoMore = await api('POST', `/v1/segments/${seg.segment_id}/undo`);   // hết lịch sử → 404
    let segUndo = null;
    for (let i = 0; i < 40; i++) { await sleep(500); segUndo = (await broker(b, `/v1/sessions/${sid}/segments`)).segments.find((x) => x.segment_id === seg.segment_id); if (segUndo?.status === 'ready' && segUndo?.audio === 'ready') break; }
    log('T12b_undo', { status: undo.status, rev: segUndo?.revision, override: segUndo?.override, spoken_restored: segUndo?.target_spoken !== longSpoken, audio: segUndo?.audio });
    report.pass.T12_undo_restores_machine = undo.status === 200 && undoMore.status === 404 && segUndo?.override === false && segUndo?.target_spoken !== longSpoken && segUndo?.revision > segAfter.revision;
    await clickMode('Đồng bộ theo phụ đề');
    await sleep(1000);
    report.pass.T11_back_to_vod_sync = (await sess())?.mode === 'vod_sync';
    await cdp.send('Target.closeTarget', { targetId: pt });
  }

  // T9: SPA chuyển video → phiên cũ đóng, phiên mới cho video mới, không dùng transcript cũ
  const oldSid = (await sess()).session_id;
  await ev(`(()=>{history.pushState({}, '', '/watch?v=${VID2}'); document.dispatchEvent(new Event('yt-navigate-finish')); return true})()`);
  let s9 = null;
  for (let i = 0; i < 30; i++) { await sleep(1000); s9 = await sess(); if (s9 && s9.session_id !== oldSid && s9.video_id === VID2 && s9.units > 0) break; }
  log('T9_spa_nav', { old: oldSid, new: s9?.session_id, video: s9?.video_id, state: s9?.state, units: s9?.units, source: s9?.source?.source_id });
  report.pass.T9_new_session_for_new_video = !!s9 && s9.session_id !== oldSid && s9.video_id === VID2;
  report.pass.T9_new_video_gets_own_captions = !!s9 && s9.video_id === VID2 && s9.units > 0;

  // T10: tắt → im ≤150 ms, âm lượng trả lại
  await sleep(1000);
  await ev(`(()=>{const v=document.querySelector('video'); v.currentTime=${sentences[1].start_ms / 1000}; v.play(); return true})()`);
  await sleep(4000);
  const volOn = await ev(`document.querySelector('video').volume`);
  await ev(`document.querySelector('[data-vietdub=toggle]').click()`);
  await sleep(150);
  const spk10 = await speaking();
  await sleep(1500);
  const volOff = await ev(`document.querySelector('video').volume`);
  log('T10_off', { speaking_150ms: spk10, volume_on: volOn, volume_off: volOff, session: (await sess())?.state ?? null });
  report.pass.T10_off_stops_150ms = spk10 === false || spk10 === null;
  report.pass.T10_volume_restored = volOff > 0.9;
  await cdp.screenshot(page, join(outDir, 'T10-off.png'));
  // T13 (AT-030): hai tab YouTube — bật ở tab 2 thì tab 1 nhả phiên, không phát chồng
  await ev(`document.querySelector('[data-vietdub=toggle]').click()`);
  for (let i = 0; i < 20; i++) { await sleep(1000); const x = await sess(); if (x?.units > 0) break; }
  await ev(`(()=>{const v=document.querySelector('video'); v.currentTime=${sentences[1].start_ms / 1000}; v.play(); return true})()`);
  await sleep(3000);
  const sid1 = (await sess())?.session_id;
  const { targetId: tab2 } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const page2 = await cdp.attach(tab2);
  fakePages.add(page2);
  await cdp.send('Runtime.enable', {}, page2);
  await cdp.send('Fetch.enable', { patterns: [{ urlPattern: 'https://www.youtube.com/*', requestStage: 'Request' }] }, page2);
  await cdp.send('Page.navigate', { url: 'https://www.youtube.com/watch?v=VDfakeTest3' }, page2);
  const ev2 = (expr) => cdp.evaluate(page2, expr);
  for (let i = 0; i < 30; i++) { if (await ev2(`!!document.querySelector('[data-vietdub=toggle]')`).catch(() => false)) break; await sleep(500); }
  await ev2(`document.querySelector('[data-vietdub=toggle]').click()`);
  let s13 = null;
  for (let i = 0; i < 20; i++) { await sleep(1000); s13 = await sess(); if (s13?.video_id === 'VDfakeTest3') break; }
  await sleep(1500);
  const tab1Pressed = await ev(`document.querySelector('[data-vietdub=toggle]').getAttribute('aria-pressed')`);
  const tab1Vol = await ev(`document.querySelector('video').volume`);
  log('T13_two_tabs', { old_session: sid1, new_session: s13?.session_id, video: s13?.video_id, tab1_pressed: tab1Pressed, tab1_volume: tab1Vol });
  report.pass.T13_second_tab_takes_over = !!s13 && s13.session_id !== sid1 && s13.video_id === 'VDfakeTest3';
  report.pass.T13_first_tab_released = tab1Pressed === 'false' && tab1Vol > 0.9;
  // T14 (AT-031-B): đóng tab đang chạy → phiên đóng, không còn tiếng mồ côi
  await cdp.send('Target.closeTarget', { targetId: tab2 });
  let s14 = s13;
  for (let i = 0; i < 15; i++) { await sleep(1000); s14 = await sess(); if (!s14) break; }
  const spk14 = await speaking();
  log('T14_close_tab', { session_after: s14?.session_id ?? null, speaking: spk14 });
  report.pass.T14_close_tab_stops_session = !s14 && !spk14;
  report.sw_log = await cdp.evaluate(swS, 'globalThis.__vdlog?.slice(-400)').catch(() => null);
} catch (e) {
  code = 1;
  report.error = String(e.stack ?? e);
  console.error(e);
} finally {
  if (restoreUserMode) await restoreUserMode().catch(() => undefined);
  report.finished = new Date().toISOString();
  writeFileSync(join(outDir, 'report.json'), JSON.stringify(report, null, 2));
  const vals = Object.values(report.pass);
  console.log('REPORT', join(outDir, 'report.json'), `${vals.filter((v) => v === true).length}/${vals.length} PASS`, JSON.stringify(report.pass));
  cdp.close();
  proc.kill();
}
process.exit(code);
