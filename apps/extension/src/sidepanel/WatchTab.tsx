import { useEffect, useState } from 'react';
import { decodeSubtitleBytes, parseSubtitles, type ParseResult } from '../../../../packages/captions/src';
import { api, fmtTime } from '../shared/api';
import type { Mode, PanelStatus } from '../shared/messages';
import { ERROR_ACTION_VI, MODE_VI, SOURCE_QUALITY, STATE_VI, T, type SourceKind } from '../shared/strings';
import { Card, Confirm, ErrorBox, sendBg } from './ui';

interface ActiveInfo {
  active: { tab_id: number; video_id: string; session_id: string; mode: Mode; capture: boolean } | null;
  tab_id: number | null;
  tab: { video_id: string | null; title: string; is_live: boolean; is_shorts: boolean } | null;
  paired: boolean;
  youtube: boolean;
}

interface Props {
  status: PanelStatus | null;
  info: ActiveInfo | null;
  refreshInfo: () => void;
  settings: Record<string, Record<string, unknown>> | null;
  saveSettings: (patch: Record<string, Record<string, unknown>>) => Promise<void>;
}

export function WatchTab({ status, info, refreshInfo, settings, saveSettings }: Props) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [importRes, setImportRes] = useState<(ParseResult & { name: string }) | null>(null);
  const [offsetS, setOffsetS] = useState(0);
  const [confirmOffset, setConfirmOffset] = useState(false);
  const on = !!info?.active && info.active.tab_id === info.tab_id;
  const s = status?.session;
  const pb = (settings?.playback ?? {}) as Record<string, number | string | boolean>;

  const run = async (fn: () => Promise<{ ok: boolean; code?: string; message?: string } | void>) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fn();
      if (r && !r.ok) setErr({ code: r.code, message: r.message });
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
      refreshInfo();
    }
  };

  const toggle = () => run(() => sendBg({ type: 'panel.toggle', tab_id: info?.tab_id }));
  const setMode = async (mode: Mode) => {
    await saveSettings({ playback: { mode } });
    if (on && s) {
      await run(async () => {
        await api('POST', `/v1/sessions/${s.session_id}/control`, { op: 'mode', mode });
        await sendBg({ type: 'offscreen.mode', mode });
      });
    }
  };
  const capture = () => run(async () => {
    // quyền tabCapture chỉ xin khi người dùng bấm (FR-008); không micro
    const ok = await chrome.permissions.request({ permissions: ['tabCapture'] });
    if (!ok) return { ok: false, code: 'PERMISSION_DENIED' };
    return sendBg({ type: 'panel.capture_start', tab_id: info?.tab_id });
  });
  const stopCapture = () => run(() => sendBg({ type: 'panel.capture_stop' }));
  const retry = async () => {
    if (info?.tab_id != null) await chrome.tabs.sendMessage(info.tab_id, { ns: 'vietdub', type: 'captions.fetch', force: true }).catch(() => undefined);
  };
  const onFile = async (f: File | undefined) => {
    if (!f) return;
    try {
      const text = decodeSubtitleBytes(await f.arrayBuffer());
      setImportRes({ ...parseSubtitles(text), name: f.name });
    } catch {
      setImportRes({ format: 'unknown', cues: [], errors: [{ line: 0, reason: 'Tệp quá lớn (tối đa 10 MB) hoặc không đọc được' }], warnings: [], name: f.name });
    }
  };
  const applyImport = () => run(async () => {
    if (!importRes) return;
    setConfirmOffset(false);
    const cues = importRes.cues.map((c, i) => ({ cue_id: `i${i + 1}`, start_ms: c.startMs, end_ms: c.endMs, text: c.text, committed: true }));
    const last = cues.reduce((m, c) => Math.max(m, c.end_ms), 0);
    const r = await sendBg<{ ok: boolean; code?: string }>({ type: 'panel.import_captions', tab_id: info?.tab_id, payload: {
      source_id: `import-${Date.now()}`, source_kind: 'import', language: 'en', coverage: 'full', available_until_ms: last, cues,
      offset_ms: Math.round(offsetS * 1000), label: `Tệp nhập: ${importRes.name}`, tried: [] } });
    setImportRes(null);
    return r;
  });

  if (!info?.youtube) {
    return <Card title="Mở một video YouTube"><p className="muted">Bảng này điều khiển thuyết minh cho tab YouTube đang xem. Hãy mở một video rồi quay lại đây.</p></Card>;
  }

  const stateText = s ? STATE_VI[s.state] ?? s.state : on ? T.connecting : 'Chưa bật';
  const holdText = status?.preload ? 'Đang chuẩn bị thuyết minh…' : status?.hold?.text;   // chuẩn bị ưu tiên hiển thị
  const level = status?.connection === 'reconnecting' || s?.state === 'ERROR' ? 'err' : holdText || s?.state === 'BUFFERING' || s?.state === 'WARMING' ? 'warn' : on && s?.state === 'PLAYING' ? 'ok' : '';
  const srcKind = (status?.capture ? 'asr' : s?.source?.source_kind) as SourceKind | undefined;
  const srcQ = on && srcKind && srcKind in SOURCE_QUALITY ? SOURCE_QUALITY[srcKind] : null;
  const sourceLine = status?.capture ? `Âm thanh tab • Có độ trễ` : status?.source_label ? `${status.source_label} • ${s?.source?.coverage === 'full' ? 'Có thể chuẩn bị trước' : 'Một phần'}` : '';

  return (
    <div className="stack">
      <Card>
        <div className="stack">
          <button className={`btn big ${on ? '' : 'primary'}`} onClick={toggle} disabled={busy || !info.tab?.video_id} aria-pressed={on}>
            {on ? T.disable : T.enable}
          </button>
          {srcQ && (
            <div className="row small" title={srcQ.hint}>
              <span className={`badge ${srcQ.level}`} data-vietdub="source-quality">{srcQ.label}</span>
              <span className="muted">{srcQ.hint}</span>
            </div>
          )}
          {sourceLine && <div className="small muted">Nguồn: {sourceLine}</div>}
          <div className={`status ${level}`} role="status" aria-live="polite">
            <div><span className={`dot ${level}`} aria-hidden />{status?.connection === 'reconnecting' ? T.reconnecting : holdText ?? stateText}</div>
            {on && s && (
              <div className="small muted">
                Chế độ: {MODE_VI[s.mode]} · Đã chuẩn bị trước: {Math.round(s.buffer_media_ms / 1000)} s · Câu: {s.units}
                {s.blocked ? ` · ${s.blocked} câu chưa đạt kiểm tra` : ''}
              </div>
            )}
            {s?.last_error && <div className="small">Lỗi gần nhất: {s.last_error}{ERROR_ACTION_VI[s.last_error] ? ` — ${ERROR_ACTION_VI[s.last_error]}` : ''}</div>}
          </div>
          <ErrorBox error={err ? Object.assign(new Error(), err) : null} />
          {status?.preload && (
            <div className="stack" role="status" aria-live="polite" data-vietdub="preload">
              <div className="small">Đang chuẩn bị thuyết minh tiếng Việt… {Math.round(status.preload.pct * 100)}%</div>
              <progress max={100} value={Math.round(status.preload.pct * 100)} aria-label="Tiến độ chuẩn bị" style={{ width: '100%' }} />
              <div className="row"><button className="btn" onClick={() => void sendBg({ type: 'offscreen.preload_skip' })}>Xem luôn</button>
                <span className="small muted">Video tự phát khi đủ tiếng Việt.</span></div>
            </div>
          )}
          {status?.autoplay_blocked && <button className="btn primary" onClick={() => sendBg({ type: 'offscreen.resume_audio' })}>{T.click_to_resume_audio}</button>}
          {status?.replay_prompt && (
            <button className="btn" onClick={() => sendBg({ type: 'offscreen.replay', segment_id: status.replay_prompt?.segment_id })}>{T.replay_current}</button>
          )}
          {status?.hold?.reason === 'BLOCKED' && (
            <div className="row">
              <span className="small">{T.blocked}.</span>
              <button className="btn" onClick={() => sendBg({ type: 'offscreen.skip_blocked' })}>Bỏ qua câu này</button>
              <span className="small muted">hoặc sửa/dịch lại ở tab Bản dịch</span>
            </div>
          )}
        </div>
      </Card>

      <Card title="Chế độ">
        <div className="seg" role="group" aria-label="Chế độ thuyết minh">
          {(['vod_sync', 'live_delayed', 'study'] as Mode[]).map((m) => (
            <button key={m} aria-pressed={(s?.mode ?? pb.mode ?? 'vod_sync') === m} onClick={() => void setMode(m)}>{MODE_VI[m]}</button>
          ))}
        </div>
        <p className="small muted" style={{ marginBottom: 0 }}>
          {(s?.mode ?? pb.mode) === 'live_delayed' ? 'Tiếng Việt đi sau lời gốc; hiển thị độ trễ. Không đồng bộ khuôn miệng.'
            : (s?.mode ?? pb.mode) === 'study' ? 'Dừng hình khi cần để nghe hết từng câu; có Nghe lại và song ngữ.'
              : 'Đọc theo phụ đề, không dừng video. Nếu tiếng Việt trễ quá ~3 giây thì dừng một nhịp để bắt kịp rồi tự phát tiếp.'}
        </p>
      </Card>

      <Card title="Âm lượng">
        <label className="field"><span>{T.target_volume}: {Math.round(Number(pb.vietnamese_gain ?? 1) * 100)}%</span>
          <input type="range" min={0} max={2} step={0.05} value={Number(pb.vietnamese_gain ?? 1)} aria-label={T.target_volume}
            onChange={(e) => void saveSettings({ playback: { vietnamese_gain: Number(e.target.value) } })} /></label>
        <label className="field"><span>{T.source_volume}: {Math.round(Number(pb.original_gain ?? 0.15) * 100)}%</span>
          <input type="range" min={0} max={1} step={0.05} value={Number(pb.original_gain ?? 0.15)} aria-label={T.source_volume}
            onChange={(e) => void saveSettings({ playback: { original_gain: Number(e.target.value) } })} /></label>
        <div className="seg" role="group" aria-label="Phụ đề trên video">
          {(['off', 'vi', 'bilingual'] as const).map((m) => (
            <button key={m} aria-pressed={(pb.subtitle_mode ?? 'bilingual') === m} onClick={() => void saveSettings({ playback: { subtitle_mode: m } })}>
              {m === 'off' ? 'Ẩn phụ đề' : m === 'vi' ? 'Phụ đề Việt' : 'Song ngữ'}
            </button>
          ))}
        </div>
      </Card>

      {(s?.mode === 'study' || pb.mode === 'study') && on && (
        <Card title="Học kỹ">
          <div className="row">
            <button className="btn" onClick={() => status?.replay_prompt ? sendBg({ type: 'offscreen.replay', segment_id: status.replay_prompt.segment_id }) : sendBg({ type: 'offscreen.replay_current' })}>Nghe lại câu</button>
          </div>
        </Card>
      )}

      {(s?.mode === 'live_delayed' || status?.capture) && on && (
        <Card title="Trực tiếp có độ trễ">
          <div className="kv">
            <dt>Độ trễ</dt><dd>{status?.lag_ms != null ? `${(status.lag_ms / 1000).toFixed(1)} s` : '—'}</dd>
            <dt>Hàng chờ</dt><dd>{Math.round((s?.live_queue_ms ?? 0) / 1000)} s / tối đa {Math.round(Number(pb.live_queue_hard_cap_ms ?? 30000) / 1000)} s</dd>
            <dt>Đang nghe</dt><dd>{status?.draft ? <i>(nháp) {status.draft}</i> : '—'}</dd>
          </div>
          {s?.last_error === 'LIVE_QUEUE_OVERFLOW' && (
            <div className="stack">
              <div className="status err">{T.overflow}</div>
              <button className="btn primary" onClick={() => void api('POST', `/v1/sessions/${s.session_id}/control`, { op: 'resume_live' })}>{T.resume_here}</button>
            </div>
          )}
          {status?.capture && <button className="btn" onClick={stopCapture}>Dừng thu âm thanh tab</button>}
        </Card>
      )}

      {(status?.source_failed || (on && !status?.source_label && !status?.capture)) && (
        <Card title={status?.source_failed ? T.source_missing : 'Nguồn phụ đề'}>
          {status?.source_failed && (
            <div className="stack">
              <div className="small">{status.source_failed.reason}. Đã thử:</div>
              <ul className="small muted" style={{ margin: 0, paddingLeft: 18 }}>{status.source_failed.tried.map((t, i) => <li key={i}>{t}</li>)}</ul>
            </div>
          )}
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn" onClick={() => void retry()}>Thử lại</button>
            <label className="btn" style={{ display: 'inline-flex', alignItems: 'center' }}>
              {T.import_subtitle}<input type="file" accept=".srt,.vtt,text/vtt" className="sr-only" onChange={(e) => void onFile(e.target.files?.[0])} />
            </label>
            <button className="btn" onClick={capture} disabled={busy}>{T.capture_tab}</button>
          </div>
          <p className="small muted">{T.tab_audio_delay}. Chrome sẽ hỏi quyền thu âm thanh của tab này (không dùng micro).</p>
        </Card>
      )}

      {importRes && (
        <Card title={`Nhập phụ đề: ${importRes.name}`}>
          <div className="small">Định dạng: {importRes.format.toUpperCase()} · {importRes.cues.length} dòng · {importRes.errors.length} lỗi · {importRes.warnings.length} cảnh báo</div>
          {[...importRes.errors, ...importRes.warnings].slice(0, 8).map((e, i) => <div key={i} className="small muted">Dòng {e.line}: {e.reason}</div>)}
          <label className="field" style={{ marginTop: 8 }}><span>Lệch thời gian (giây, −600 đến 600)</span>
            <input type="number" min={-600} max={600} step={0.1} value={offsetS} onChange={(e) => setOffsetS(Math.max(-600, Math.min(600, Number(e.target.value))))} /></label>
          <p className="small muted">Chỉ dùng phụ đề bạn có quyền sử dụng.</p>
          <div className="row">
            <button className="btn primary" disabled={importRes.cues.length === 0} onClick={() => (offsetS !== 0 ? setConfirmOffset(true) : void applyImport())}>Dùng phụ đề này</button>
            <button className="btn" onClick={() => setImportRes(null)}>Hủy</button>
          </div>
        </Card>
      )}
      <Confirm open={confirmOffset} title="Áp dụng lệch thời gian?" confirmText="Áp dụng"
        body={<span>Mọi dòng phụ đề sẽ dịch {offsetS > 0 ? 'muộn' : 'sớm'} {Math.abs(offsetS)} giây. Tệp gốc không bị sửa.</span>}
        onCancel={() => setConfirmOffset(false)} onConfirm={() => void applyImport()} />

      {s && (
        <p className="small muted">Vị trí video: {fmtTime(status?.media_ms ?? s.media_ms)}{status?.queue_ms ? ` · tiếng Việt đã sẵn ${Math.round(status.queue_ms / 1000)} s` : ''}</p>
      )}
    </div>
  );
}

export function useActiveInfo() {
  const [info, setInfo] = useState<ActiveInfo | null>(null);
  const refresh = () => void sendBg<ActiveInfo>({ type: 'panel.get_active' }).then(setInfo).catch(() => undefined);
  useEffect(() => {
    refresh();
    const onAct = () => refresh();
    chrome.tabs.onActivated.addListener(onAct);
    chrome.tabs.onUpdated.addListener(onAct);
    const id = setInterval(refresh, 2000);
    return () => {
      chrome.tabs.onActivated.removeListener(onAct);
      chrome.tabs.onUpdated.removeListener(onAct);
      clearInterval(id);
    };
  }, []);
  return { info, refresh };
}
export type { ActiveInfo };
