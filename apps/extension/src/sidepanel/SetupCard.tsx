import { useRef, useState } from 'react';
import { api, ApiError, fmtBytes } from '../shared/api';
import { Card, ErrorBox, useAsync, useInterval } from './ui';

interface SetupModel {
  model_id: string; label_vi: string; repo: string; license: string; size_bytes: number; state: string;
  download: { state: string; bytes_done: number; bytes_total: number } | null;
}
interface SetupStatus {
  state: string; ready: boolean; busy: boolean; current_model: string | null; error: string | null;
  include_asr: boolean; asr_runtime_available: boolean; models: SetupModel[];
}
const STATES: Record<string, string> = {
  idle: 'Chuẩn bị một lần trước khi xem', checking: 'Đang kiểm tra mô hình đã có…',
  downloading: 'Đang tải mô hình…', activating: 'Đang nạp bộ dịch và giọng đọc…',
  ready: 'Sẵn sàng dịch và đọc', paused: 'Đã tạm dừng — có thể tiếp tục', failed: 'Chưa chuẩn bị xong — hãy thử lại',
};

export function SetupCard() {
  const status = useAsync(() => api<SetupStatus>('GET', '/v1/setup'));
  const [includeAsr, setIncludeAsr] = useState(false);
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const inFlight = useRef(false);
  useInterval(() => { if (!inFlight.current) void status.reload(); }, status.data?.busy ? 1500 : 5000);
  const s = status.data;
  const chosen = s?.models.filter((m) => m.model_id !== 'whisper_small_en' || includeAsr) ?? [];
  const bytes = chosen.filter((m) => m.state !== 'verified').reduce((sum, m) => sum + m.size_bytes, 0);
  const active = s?.models.find((m) => m.model_id === s.current_model);
  const dl = active?.download;
  const asrReady = s?.models.find((m) => m.model_id === 'whisper_small_en')?.state === 'verified';
  const ready = s?.ready && (!includeAsr || asrReady) && !s.busy;
  const run = async (pause = false) => {
    if (inFlight.current) return;
    inFlight.current = true; setPending(true); setError(null);
    try {
      const next = await api<SetupStatus>('POST', pause ? '/v1/setup/pause' : '/v1/setup', pause ? {} : {
        consent, include_asr: includeAsr,
        accepted_sizes: Object.fromEntries(chosen.map((m) => [m.model_id, m.size_bytes])),
      });
      status.setData(next);
    } catch (e) { setError(e); }
    finally { inFlight.current = false; setPending(false); }
  };
  return <Card title="Bắt đầu sử dụng">
    <div className="stack">
      <div className={`status ${ready ? 'ok' : 'warn'}`} role="status">{ready ? STATES.ready : STATES[s?.state ?? 'idle']}</div>
      {ready && <p className="small">Mở video YouTube có phụ đề, chuyển sang tab <b>Xem</b> rồi bấm <b>Bật tiếng Việt</b>.</p>}
      <p className="small" style={{ margin: 0 }}>Bộ đề xuất gồm mô hình dịch, giọng Việt và bộ giải mã âm thanh. Tải xong sẽ tự nạp để dùng ngay.</p>
      <ul className="small" style={{ margin: 0, paddingLeft: 20 }}>{chosen.map((m) => <li key={m.model_id}>
        <a href={`https://huggingface.co/${m.repo}`} target="_blank" rel="noreferrer">{m.label_vi || m.model_id}</a>
        {' · '}{fmtBytes(m.size_bytes)}{' · '}{m.license}{m.state === 'verified' ? ' · đã có' : ''}
      </li>)}</ul>
      <label className="row small"><input type="checkbox" checked={includeAsr} disabled={!s?.asr_runtime_available || s.busy || pending}
        onChange={(e) => { setIncludeAsr(e.target.checked); setConsent(false); }} />Thêm nhận dạng âm thanh khi video không có phụ đề</label>
      {s && !s.asr_runtime_available && <p className="small muted" style={{ margin: 0 }}>Muốn nhận dạng âm thanh: chạy lại Setup.cmd, chọn thêm chức năng này vào cùng nơi cài.</p>}
      {!ready && <>
        <p className="small" style={{ margin: 0 }}>Dung lượng bộ chưa xác minh: <b>{fmtBytes(bytes)}</b>. Tải từ Hugging Face; tệp đã tải hợp lệ được dùng lại.</p>
        <label className="row small"><input type="checkbox" checked={consent} disabled={s?.busy || pending} onChange={(e) => setConsent(e.target.checked)} />Tôi đã xem dung lượng, giấy phép và đồng ý tải.</label>
        <button className="btn primary" disabled={!s || !consent || s.busy || pending} onClick={() => void run()}>
          {s?.busy ? 'Đang chuẩn bị…' : s?.state === 'paused' ? 'Tiếp tục chuẩn bị' : s?.state === 'failed' ? 'Thử lại' : 'Chuẩn bị để sử dụng'}
        </button>
      </>}
      {s?.busy && <>
        {active && <div className="small">{active.label_vi || active.model_id}</div>}
        {dl && <><progress style={{ width: '100%' }} max={dl.bytes_total || 1} value={dl.bytes_done} aria-label="Tiến độ tải mô hình" />
          <div className="small muted">{fmtBytes(dl.bytes_done)} / {fmtBytes(dl.bytes_total)}</div></>}
        {s.state !== 'activating' && <button className="btn" disabled={pending} onClick={() => void run(true)}>Tạm dừng sau phần đang kiểm tra</button>}
        <p className="small muted" style={{ margin: 0 }}>Có thể đóng bảng bên; bộ xử lý vẫn tiếp tục. Giữ VietDub đang chạy.</p>
      </>}
      <ErrorBox error={error ?? status.error ?? (s?.error ? new ApiError(s.error, 'Chuẩn bị chưa hoàn tất.', 0) : null)} />
    </div>
  </Card>;
}
