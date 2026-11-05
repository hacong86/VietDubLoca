import { useState } from 'react';
import { api, fmtBytes } from '../shared/api';
import { Card, Confirm, ErrorBox, useAsync, useInterval } from './ui';
import { SetupCard } from './SetupCard';

interface ModelRow {
  model_id: string; kind: string; label_vi: string | null; quant: string | null; repo: string; revision: string; size_bytes: number;
  license: string | null; role: string | null; state: string; active: boolean;
  download: { job_id: string; state: string; bytes_done: number; bytes_total: number } | null;
}
interface EnvItem { key: string; ok: boolean; value: unknown; source: string; action_vi: string | null }

const STATE_VI: Record<string, string> = {
  verified: 'Đã kiểm tra mã (SHA-256)', present_unverified: 'Có tệp, chưa kiểm tra', not_downloaded: 'Chưa tải', partial: 'Tải dở (.part — không được nạp)',
  running: 'Đang tải', queued: 'Chờ tải', paused: 'Tạm dừng', verifying: 'Đang kiểm tra mã', failed: 'Lỗi', done: 'Xong',
};
const ENV_VI: Record<string, string> = { os: 'Hệ điều hành', ram: 'RAM', disk: 'Ổ đĩa dữ liệu', gpu: 'GPU / VRAM (đo thật)', llama_runtime: 'Bộ chạy dịch (llama.cpp)',
  tts_runtime: 'Môi trường giọng đọc', asr_runtime: 'Môi trường nhận dạng giọng nói', gpu_processes: 'Ứng dụng khác đang dùng GPU' };

function envValue(i: EnvItem): string {
  const v = i.value as Record<string, unknown> | string | boolean | unknown[] | null;
  if (i.key === 'gpu' && v && typeof v === 'object' && !Array.isArray(v)) return `${v.name ?? ''} · trống ${v.vram_free_mb ?? '?'}/${v.vram_total_mb ?? '?'} MB · driver ${v.driver ?? '?'}`;
  if (i.key === 'ram' && v && typeof v === 'object') return `${(v as Record<string, number>).total_gb} GB (trống ${(v as Record<string, number>).free_gb} GB)`;
  if (i.key === 'disk' && v && typeof v === 'object') return `${(v as Record<string, string>).path} trống ${(v as Record<string, number>).free_gb} GB`;
  if (i.key === 'gpu_processes' && Array.isArray(v)) {
    const known = (v as { name: string; used_mb: number | null }[]).filter((p) => typeof p.used_mb === 'number' && p.used_mb >= 50);
    const rest = v.length - known.length;
    const parts = known.map((p) => `${p.name} ${p.used_mb} MB`);
    if (rest > 0) parts.push(`${rest} ứng dụng khác (Windows không báo dung lượng riêng)`);
    return parts.length ? parts.join(', ') : 'không có';
  }
  if (typeof v === 'boolean') return v ? 'có' : 'thiếu';
  return typeof v === 'string' ? v : i.key.startsWith('model:') ? String(STATE_VI[String(v)] ?? v) : JSON.stringify(v);
}

export function ModelsTab() {
  const env = useAsync(() => api<{ ready: boolean; items: EnvItem[] }>('GET', '/v1/env'));
  const models = useAsync(() => api<{ models: ModelRow[]; active_translation: string | null; translation_state: string }>('GET', '/v1/models'));
  const [consent, setConsent] = useState<ModelRow | null>(null);
  const [agree, setAgree] = useState(false);
  const [del, setDel] = useState<ModelRow | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const downloading = models.data?.models.some((m) => m.download && ['running', 'queued', 'verifying'].includes(m.download.state)) || models.data?.translation_state === 'loading';
  useInterval(() => void models.reload(), downloading ? 1000 : 5000);

  const act = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr(e);
    }
    await models.reload();
  };

  return (
    <div className="stack">
      <SetupCard />
      <details onToggle={(e) => { if (e.currentTarget.open) { void env.reload(); void models.reload(); } }}>
      <summary className="small" style={{ cursor: 'pointer', padding: '8px 0' }}>Nâng cao: kiểm tra máy và quản lý từng mô hình</summary>
      <Card title="Kiểm tra máy" actions={<button className="btn" onClick={() => void env.reload()}>Kiểm tra lại</button>}>
        {env.data && (
          <div className={`status ${env.data.ready ? 'ok' : 'warn'}`} style={{ marginBottom: 8 }}>
            <span className={`dot ${env.data.ready ? 'ok' : 'warn'}`} aria-hidden />{env.data.ready ? 'Sẵn sàng: đủ thành phần để dịch và đọc trên máy' : 'Chưa sẵn sàng — xem mục thiếu bên dưới'}
          </div>
        )}
        <ul className="list small">
          {env.data?.items.filter((i) => !i.key.startsWith('model:')).map((i) => (
            <li key={i.key} style={{ marginBottom: 4 }}>
              <span className={`dot ${i.ok ? 'ok' : 'err'}`} aria-hidden /><b>{ENV_VI[i.key] ?? i.key}</b>: {envValue(i)}
              <span className="muted"> ({i.source})</span>{!i.ok && i.action_vi && <div>→ {i.action_vi}</div>}
            </li>
          ))}
        </ul>
        <ErrorBox error={env.error} />
      </Card>

      <Card title="Mô hình">
        <p className="small muted" style={{ marginTop: 0 }}>Chỉ một mô hình dịch được nạp một lúc. Không tải mmproj (không cần cho dịch chữ). Tệp tải dở không bao giờ được nạp.</p>
        <ErrorBox error={err ?? models.error} />
        {models.data?.models.map((m) => {
          const dl = m.download;
          const pct = dl && dl.bytes_total ? Math.round((dl.bytes_done / dl.bytes_total) * 100) : 0;
          return (
            <div key={m.model_id} className="card" style={{ marginBottom: 8 }}>
              <div className="row between">
                <b>{m.label_vi ?? m.model_id}</b>
                {m.active ? <span className="badge ok">Đang dùng</span> : <span className={`badge ${m.state === 'verified' ? 'ok' : m.state === 'failed' ? 'err' : ''}`}>{STATE_VI[m.state] ?? m.state}</span>}
              </div>
              <div className="small muted">{m.repo} @ {m.revision.slice(0, 10)} · {fmtBytes(m.size_bytes)} · giấy phép {m.license ?? '—'} · {m.kind === 'translation' ? 'dịch' : m.kind === 'asr' ? 'nhận dạng giọng nói' : 'giọng đọc'}</div>
              {dl && ['running', 'queued', 'verifying', 'paused'].includes(dl.state) && (
                <div style={{ marginTop: 6 }}>
                  <div className="progress" aria-label={`Tiến độ tải ${pct}%`}><div style={{ width: `${pct}%` }} /></div>
                  <div className="small muted">{STATE_VI[dl.state]} · {fmtBytes(dl.bytes_done)} / {fmtBytes(dl.bytes_total)}</div>
                </div>
              )}
              <div className="row" style={{ marginTop: 6 }}>
                {m.state !== 'verified' && !(dl && ['running', 'queued', 'verifying'].includes(dl.state)) && <button className="btn primary" onClick={() => { setAgree(false); setConsent(m); }}>{m.state === 'partial' || dl?.state === 'paused' ? 'Tải tiếp' : 'Tải'}</button>}
                {dl && dl.state === 'running' && <button className="btn" onClick={() => act(() => api('POST', `/v1/models/${m.model_id}/pause`))}>Tạm dừng</button>}
                {m.state === 'present_unverified' && <button className="btn" onClick={() => act(() => api('POST', `/v1/models/${m.model_id}/verify`))}>Kiểm tra mã</button>}
                {m.kind === 'translation' && m.state === 'verified' && !m.active && <button className="btn primary" onClick={() => act(() => api('POST', `/v1/models/${m.model_id}/activate`))}>Dùng mô hình này</button>}
                {m.kind === 'translation' && m.state !== 'verified' && <button className="btn" onClick={() => act(() => api('POST', `/v1/models/${m.model_id}/import`))}>Nhập tệp có sẵn…</button>}
                {m.state !== 'not_downloaded' && !m.active && <button className="btn danger" onClick={() => setDel(m)}>Xóa</button>}
              </div>
            </div>
          );
        })}
        {models.data?.translation_state === 'loading' && <div className="status warn">Đang nạp mô hình dịch…</div>}
      </Card>

      </details>
      <Confirm open={!!consent} title="Tải mô hình?" confirmText="Đồng ý tải" onCancel={() => setConsent(null)}
        onConfirm={() => { if (!agree || !consent) return; const m = consent; setConsent(null); void act(() => api('POST', `/v1/models/${m.model_id}/download`, { consent: true, accepted_size_bytes: m.size_bytes })); }}
        body={consent && (
          <div className="small stack">
            <div><b>{consent.label_vi}</b> — {fmtBytes(consent.size_bytes)} từ huggingface.co/{consent.repo} (revision {consent.revision.slice(0, 10)}).</div>
            <div>Giấy phép: {consent.license}. Tệp được kiểm tra mã trước khi dùng. Lưu tại nơi dữ liệu bạn chọn khi cài VietDub.</div>
          </div>
        )}>
        <label className="row small"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> Tôi đã đọc dung lượng và giấy phép, đồng ý tải.</label>
      </Confirm>
      <Confirm open={!!del} danger title="Xóa tệp mô hình?" confirmText="Xóa" onCancel={() => setDel(null)}
        onConfirm={() => { const m = del; setDel(null); if (m) void act(() => api('DELETE', `/v1/models/${m.model_id}`)); }}
        body={<span>{del?.label_vi} ({del ? fmtBytes(del.size_bytes) : ''}). Có thể tải lại sau.</span>} />
    </div>
  );
}
