import { useMemo, useState } from 'react';
import { api, fmtBytes } from '../shared/api';
import { Card, Confirm, ErrorBox, sendBg, useAsync } from './ui';

type S = Record<string, Record<string, unknown>>;

export function SettingsTab({ settings, saveSettings, videoId }: { settings: S | null; saveSettings: (p: S) => Promise<void>; videoId: string | null }) {
  const voices = useAsync(() => api<{ voices: { voice_id: string; label: string }[]; selected: string }>('GET', '/v1/voices'));
  const cache = useAsync(() => api<{ usage_bytes: number; limit_bytes: number; disk_full: boolean; private_mode: boolean }>('GET', '/v1/cache'));
  const history = useAsync(() => api<{ enabled: boolean; items: { video_id: string; title: string | null; last_opened_at: string }[] }>('GET', '/v1/history'));
  const [vq, setVq] = useState('');
  const [err, setErr] = useState<unknown>(null);
  const [clear, setClear] = useState<null | 'video' | 'all'>(null);
  const [keepOverrides, setKeepOverrides] = useState(true);
  const [reset, setReset] = useState(false);
  const [resetGlossary, setResetGlossary] = useState(false);
  const pb = settings?.playback ?? {};
  const st = settings?.storage ?? {};
  const pr = settings?.privacy ?? {};
  const tts = settings?.tts ?? {};
  const tr = settings?.translation ?? {};
  const shownVoices = useMemo(() => (voices.data?.voices ?? []).filter((v) => v.label.toLowerCase().includes(vq.toLowerCase())), [voices.data, vq]);

  const save = async (p: S) => {
    setErr(null);
    try {
      await saveSettings(p);
    } catch (e) {
      setErr(e);
    }
  };

  const doClear = async () => {
    const scope = clear;
    setClear(null);
    try {
      await api('POST', '/v1/cache/clear', { confirm: true, scope, video_id: scope === 'video' ? videoId : undefined, keep_overrides: keepOverrides });
      await cache.reload();
      await history.reload();
    } catch (e) {
      setErr(e);
    }
  };

  return (
    <div className="stack">
      <ErrorBox error={err} />
      <Card title="Giọng đọc (VieNeu trên máy)">
        <input type="search" placeholder="Tìm giọng…" aria-label="Tìm giọng" value={vq} onChange={(e) => setVq(e.target.value)} />
        <ErrorBox error={voices.error} />
        <ul className="list" style={{ maxHeight: 260, overflowY: 'auto', marginTop: 8 }}>
          {shownVoices.map((v) => (
            <li key={v.voice_id} className="row between" style={{ padding: '4px 0', borderBottom: '1px solid var(--line)' }}>
              <label className="row small" style={{ flex: 1 }}>
                <input type="radio" name="voice" checked={(tts.voice_id ?? voices.data?.selected) === v.voice_id} onChange={() => void save({ tts: { voice_id: v.voice_id } })} />
                {v.label.replace(/^⭐\s*/, '')}
              </label>
              <button className="btn small" onClick={() => void sendBg({ type: 'panel.preview', voice_id: v.voice_id })}>Nghe thử</button>
            </li>
          ))}
        </ul>
        <p className="small muted">Danh sách lấy từ bộ giọng đã cài; không có giọng nào là giọng thật của người trong video. Không nhân bản giọng.</p>
        <label className="row small" style={{ marginTop: 8 }}>
          <input type="checkbox" checked={tts.alternate_speakers !== false} onChange={(e) => void save({ tts: { alternate_speakers: e.target.checked } })} />
          Đổi giọng khi đổi người nói (phụ đề có dấu “&gt;&gt;” hoặc tên người nói)
        </label>
        {tts.alternate_speakers !== false && (
          <label className="field"><span>Giọng cho người nói thứ hai</span>
            <select value={tts.voice_alt_id && tts.voice_alt_id !== (tts.voice_id ?? voices.data?.selected) ? String(tts.voice_alt_id) : ''} onChange={(e) => void save({ tts: { voice_alt_id: e.target.value } })}>
              <option value="">Tự chọn (khác giới với giọng chính)</option>
              {(voices.data?.voices ?? []).filter((v) => v.voice_id !== (tts.voice_id ?? voices.data?.selected)).map((v) => (
                <option key={v.voice_id} value={v.voice_id}>{v.label.replace(/^⭐\s*/, '')}</option>
              ))}
            </select></label>
        )}
      </Card>

      <Card title="Dịch">
        <label className="field"><span>Chủ đề (giúp chọn thuật ngữ)</span>
          <select value={String(tr.topic ?? 'general')} onChange={(e) => void save({ translation: { topic: e.target.value } })}>
            <option value="general">Chung</option><option value="unity">Unity / làm game</option><option value="ai_coding">AI / lập trình</option>
            <option value="business">Kinh doanh</option><option value="conversational">Trò chuyện</option>
          </select></label>
      </Card>

      <Card title="Phụ đề trên video">
        <div className="row">
          <label className="field" style={{ flex: 1 }}><span>Cỡ chữ: {String(pb.subtitle_size ?? 22)} px</span>
            <input type="range" min={14} max={48} value={Number(pb.subtitle_size ?? 22)} onChange={(e) => void save({ playback: { subtitle_size: Number(e.target.value) } })} /></label>
          <label className="field" style={{ flex: 1 }}><span>Vị trí</span>
            <select value={String(pb.subtitle_position ?? 'bottom')} onChange={(e) => void save({ playback: { subtitle_position: e.target.value } })}>
              <option value="bottom">Dưới</option><option value="top">Trên</option></select></label>
        </div>
      </Card>

      <Card title="Đồng bộ và bộ đệm">
        <label className="row small"><input type="checkbox" checked={pb.preload_enabled !== false} onChange={(e) => void save({ playback: { preload_enabled: e.target.checked } })} /> Chuẩn bị trước khi phát (tạm dừng lúc bật, tự phát khi đủ tiếng Việt)</label>
        {pb.preload_enabled !== false && (
          <label className="field"><span>Chuẩn bị bao nhiêu trước khi phát</span>
            <select value={String(pb.preload_target_s ?? 30)} onChange={(e) => void save({ playback: { preload_target_s: Number(e.target.value) } })}>
              <option value="10">10 giây (chờ ít)</option><option value="20">20 giây</option><option value="30">30 giây (khuyên dùng)</option>
            </select></label>
        )}
        <p className="small muted" style={{ margin: '4px 0 8px' }}>Chế độ Đồng bộ không dừng video giữa chừng; chỉ khi tiếng Việt trễ quá khoảng 3 giây mới dừng một nhịp để bắt kịp rồi tự phát tiếp.</p>
        <label className="field"><span>Khi tua vào giữa câu</span>
          <select value={String(pb.seek_mid_sentence ?? 'replay_prompt')} onChange={(e) => void save({ playback: { seek_mid_sentence: e.target.value } })}>
            <option value="replay_prompt">Hỏi "Đọc lại câu hiện tại"</option><option value="skip_current">Bỏ qua câu đang dở (có thông báo)</option></select></label>
        <label className="field"><span>Tạo giọng trước trong lúc xem: {Math.round(Number(pb.prefetch_target_ms ?? 30000) / 1000)} giây</span>
          <input type="range" min={10000} max={90000} step={5000} value={Number(pb.prefetch_target_ms ?? 30000)} onChange={(e) => void save({ playback: { prefetch_target_ms: Number(e.target.value) } })} /></label>
      </Card>

      <Card title="Riêng tư và bộ nhớ đệm">
        <label className="row small"><input type="checkbox" checked={st.private_mode === true} onChange={(e) => void save({ storage: { private_mode: e.target.checked } })} /> Không lưu nội dung (chế độ riêng tư: không ghi phụ đề/bản dịch/âm thanh xuống đĩa)</label>
        <label className="row small"><input type="checkbox" checked={st.history_opt_in === true} onChange={(e) => void save({ storage: { history_opt_in: e.target.checked } })} /> Lưu lịch sử video đã xem (mặc định tắt)</label>
        <div className="small muted" style={{ marginTop: 6 }}>
          Bộ nhớ đệm: {cache.data ? `${fmtBytes(cache.data.usage_bytes)} / ${fmtBytes(cache.data.limit_bytes)}` : '…'} · giữ {String(st.cache_ttl_days ?? 14)} ngày
          {cache.data?.disk_full ? ' · Ổ đĩa gần đầy: đã ngừng lưu mới' : ''}
        </div>
        <div className="row" style={{ marginTop: 6 }}>
          <button className="btn" disabled={!videoId} onClick={() => setClear('video')}>Xóa dữ liệu video này</button>
          <button className="btn danger" onClick={() => setClear('all')}>Xóa bộ nhớ đệm</button>
        </div>
      </Card>

      {history.data?.enabled && (
        <Card title="Lịch sử">
          {history.data.items.length === 0 ? <p className="small muted">Chưa có.</p> : (
            <ul className="list small">{history.data.items.map((h) => (
              <li key={h.video_id} className="row between" style={{ padding: '3px 0' }}>
                <span>{h.title ?? h.video_id} <span className="muted">· {new Date(h.last_opened_at).toLocaleString('vi-VN')}</span></span>
                <button className="btn small" onClick={() => void api('POST', '/v1/cache/clear', { confirm: true, scope: 'video', video_id: h.video_id }).then(() => history.reload())}>Xóa</button>
              </li>))}
            </ul>
          )}
        </Card>
      )}

      <Card title="Khởi động và phím tắt">
        <label className="row small"><input type="checkbox" checked={pr.start_with_windows === true} onChange={(e) => void save({ privacy: { start_with_windows: e.target.checked } })} /> Chạy VietDub Local cùng Windows (mặc định tắt)</label>
        <div className="row small" style={{ marginTop: 6 }}>
          <span className="muted">Bật/tắt: Alt+Shift+V · Nghe lại câu: Alt+Shift+R · Dịch âm thanh tab: Alt+Shift+A</span>
          <button className="btn small" onClick={() => void chrome.tabs.create({ url: 'chrome://extensions/shortcuts' })}>Đổi phím tắt</button>
        </div>
      </Card>

      <Card title="Khôi phục mặc định">
        <button className="btn danger" onClick={() => setReset(true)}>Đặt lại cài đặt…</button>
      </Card>

      <Confirm open={clear !== null} danger title={clear === 'all' ? 'Xóa toàn bộ bộ nhớ đệm?' : 'Xóa dữ liệu video này?'} confirmText="Xóa"
        onCancel={() => setClear(null)} onConfirm={() => void doClear()}
        body={<span className="small">{clear === 'all' ? 'Xóa bản dịch và âm thanh đã lưu. Mô hình không bị xóa.' : 'Xóa phụ đề, bản dịch, bản sửa và âm thanh của video đang mở.'}</span>}>
        {clear === 'all' && <label className="row small"><input type="checkbox" checked={keepOverrides} onChange={(e) => setKeepOverrides(e.target.checked)} /> Giữ các câu tôi đã sửa</label>}
      </Confirm>
      <Confirm open={reset} danger title="Đặt lại cài đặt?" confirmText="Đặt lại" onCancel={() => setReset(false)}
        onConfirm={() => { setReset(false); void api('POST', '/v1/settings/reset', { confirm: true, scope: resetGlossary ? 'settings+glossary' : 'settings' }).then(() => save({})).catch(setErr); }}
        body={<span className="small">Mô hình, bộ nhớ đệm và các câu bạn đã sửa được giữ nguyên.</span>}>
        <label className="row small"><input type="checkbox" checked={resetGlossary} onChange={(e) => setResetGlossary(e.target.checked)} /> Xóa cả từ điển thuật ngữ</label>
      </Confirm>
    </div>
  );
}
