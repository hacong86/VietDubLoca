import { useState } from 'react';
import { api } from '../shared/api';
import type { PanelStatus } from '../shared/messages';
import { Card, ErrorBox, useAsync, useInterval } from './ui';

interface Stats { scheduled: number; underruns: number; holds: number; stops: number; last_stop_latency_ms: number | null; drift_ms: number[] }

function pct(a: number[], q: number) {
  if (!a.length) return null;
  const s = [...a].map(Math.abs).sort((x, y) => x - y);
  return s[Math.min(s.length - 1, Math.floor((s.length - 1) * q))];
}

export function DiagTab({ status, stats }: { status: PanelStatus | null; stats: Stats | null }) {
  const st = useAsync(() => api<Record<string, unknown>>('GET', '/v1/status'));
  const about = useAsync(() => api<{ app_version: string; runtime_build: string; tts: string; models: { model_id: string; repo: string; revision: string; license: string }[]; notices_md: string | null }>('GET', '/v1/about'));
  const [bench, setBench] = useState<{ job_id: string } | null>(null);
  const [benchRes, setBenchRes] = useState<Record<string, unknown> | null>(null);
  const [limit, setLimit] = useState(20);
  const [withTts, setWithTts] = useState(true);
  const [includePayload, setIncludePayload] = useState(false);
  const [preview, setPreview] = useState<unknown>(null);
  const [exported, setExported] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useInterval(() => void st.reload(), 3000);
  useInterval(async () => {
    if (!bench) return;
    const j = await api<Record<string, unknown>>('GET', `/v1/jobs/${bench.job_id}`);
    setBenchRes(j);
    if (j.state !== 'running') setBench(null);
  }, bench ? 1000 : null);

  const rt = st.data?.runtime as Record<string, Record<string, unknown>> | undefined;
  const RS: Record<string, string> = { ready: 'Sẵn sàng', loading: 'Đang nạp', stopped: 'Chưa chạy', failed: 'Lỗi' };
  const rs = (v: unknown) => RS[String(v)] ?? String(v ?? '—');
  const backendVi = (v: unknown) => (v === 'pytorch' ? 'GPU (PyTorch)' : v === 'onnx' ? 'CPU (ONNX)' : String(v ?? ''));
  const connVi: Record<string, string> = { connected: 'Đã kết nối', reconnecting: 'Đang kết nối lại', connecting: 'Đang kết nối', unpaired: 'Chưa có phiên', error: 'Lỗi' };
  const gpu = st.data?.gpu as Record<string, unknown> | undefined;
  const result = benchRes?.result as Record<string, unknown> | undefined;

  return (
    <div className="stack">
      <Card title="Trạng thái hệ thống">
        <ErrorBox error={st.error} />
        {rt && (
          <dl className="kv">
            <dt>Dịch</dt><dd>{rs(rt.translation?.state)} · {String(rt.translation?.model_id ?? '—')} · ngữ cảnh {String(rt.translation?.ctx)} token · llama.cpp {String(rt.translation?.runtime_build ?? '')}</dd>
            <dt>Giọng đọc</dt><dd>{rs(rt.tts?.state)} · {backendVi(rt.tts?.backend)} · SDK {String(rt.tts?.sdk_version ?? '')} · {String(rt.tts?.voices ?? 0)} giọng</dd>
            <dt>Nhận dạng</dt><dd>{rs(rt.asr?.state)} {rt.asr?.device ? `· ${rt.asr.device === 'cpu' ? 'CPU' : 'GPU'} ${String(rt.asr.compute_type)}` : '(bật khi dùng Dịch âm thanh tab)'}</dd>
            <dt>GPU</dt><dd>{gpu?.available ? `${String(gpu.name)} · đang dùng ${String(gpu.vram_used_mb)}/${String(gpu.vram_total_mb)} MB · tải ${String(gpu.utilization_pct)}%` : 'không đo được'}</dd>
            <dt>Phiên</dt><dd>{connVi[status?.connection ?? 'unpaired'] ?? status?.connection}</dd>
          </dl>
        )}
      </Card>

      {stats && (
        <Card title="Đồng bộ âm thanh (đo trong phiên)">
          <dl className="kv">
            <dt>Câu đã lên lịch</dt><dd>{stats.scheduled}</dd>
            <dt>Thiếu audio đúng lúc</dt><dd>{stats.underruns}</dd>
            <dt>Số lần tạm dừng tự động</dt><dd>{stats.holds}</dd>
            <dt>Độ trễ dừng gần nhất</dt><dd>{stats.last_stop_latency_ms !== null ? `${stats.last_stop_latency_ms} ms` : '—'}</dd>
            <dt>Lệch đồng hồ p50/p95</dt><dd>{pct(stats.drift_ms, 0.5) ?? '—'} / {pct(stats.drift_ms, 0.95) ?? '—'} ms ({stats.drift_ms.length} mẫu)</dd>
          </dl>
        </Card>
      )}

      <Card title="Đo A/B mô hình dịch trên máy">
        <p className="small muted" style={{ marginTop: 0 }}>Đo độ trễ, lỗi cấu trúc trên bộ câu mẫu với mô hình đang dùng (tắt bộ nhớ đệm). KHÔNG tự chấm đúng nghĩa — cần người chấm mù.</p>
        <div className="row">
          <label className="field" style={{ width: 110 }}><span>Số câu</span><input type="number" min={5} max={80} value={limit} onChange={(e) => setLimit(Number(e.target.value))} /></label>
          <label className="row small"><input type="checkbox" checked={withTts} onChange={(e) => setWithTts(e.target.checked)} /> Chạy kèm VieNeu (tải đồng thời)</label>
          <button className="btn primary" disabled={!!bench} onClick={() => void api<{ job_id: string }>('POST', '/v1/benchmark', { limit, split: 'all', with_tts: withTts }).then(setBench).catch(setErr)}>Chạy đo</button>
        </div>
        {benchRes && (
          <div style={{ marginTop: 8 }}>
            {benchRes.state === 'running' && <div className="progress"><div style={{ width: `${Math.round(Number(benchRes.progress ?? 0) * 100)}%` }} /></div>}
            {result && (
              <>
                <dl className="kv" style={{ marginTop: 6 }}>
                  <dt>Mô hình</dt><dd>{String(result.model_id)} ({String(result.runtime_build)})</dd>
                  <dt>Hợp lệ</dt><dd>{String(result.valid)}/{String(result.n)}</dd>
                  <dt>Độ trễ p50 / p95</dt><dd>{String(result.translate_p50_ms)} / {String(result.translate_p95_ms)} ms</dd>
                  <dt>VieNeu đồng thời</dt><dd>{result.concurrent_tts ? `${String(result.tts_calls)} lượt, p50 ${String(result.tts_p50_ms)} ms` : 'không'}</dd>
                  <dt>Chất lượng</dt><dd>{String(result.semantic_quality)}</dd>
                  <dt>Tệp kết quả</dt><dd>diagnostics/{String(result.file_name)}</dd>
                </dl>
                <table style={{ marginTop: 6 }}><tbody>
                  {(result.sample as { source: string; output: string; ms: number }[] | undefined)?.map((r, i) => (
                    <tr key={i}><td className="muted">{r.source}</td><td>{r.output}</td><td>{Math.round(r.ms)} ms</td></tr>
                  ))}
                </tbody></table>
              </>
            )}
            {benchRes.state === 'failed' && <div className="status err">Đo thất bại: {String(benchRes.error)}</div>}
          </div>
        )}
      </Card>

      <Card title="Gói chẩn đoán (lưu trên máy)">
        <label className="row small"><input type="checkbox" checked={includePayload} onChange={(e) => setIncludePayload(e.target.checked)} /> Kèm 20 câu mẫu của phiên (mặc định không kèm nội dung)</label>
        <div className="row" style={{ marginTop: 6 }}>
          <button className="btn" onClick={() => void api('GET', `/v1/diagnostics/preview?include_payload=${includePayload}`).then(setPreview).catch(setErr)}>Xem trước</button>
          <button className="btn primary" onClick={() => void api<{ file_name: string }>('POST', '/v1/diagnostics/export', { include_payload: includePayload }).then((r) => setExported(r.file_name)).catch(setErr)}>Xuất gói</button>
        </div>
        {exported && <div className="status ok small" style={{ marginTop: 6 }}>Đã lưu diagnostics/{exported} trong thư mục dữ liệu VietDub. Không tự gửi đi đâu.</div>}
        {preview !== null && <pre className="small" style={{ maxHeight: 220, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{JSON.stringify(preview, null, 1)}</pre>}
        <ErrorBox error={err} />
      </Card>

      <Card title="Giới thiệu và giấy phép">
        {about.data && (
          <div className="small stack">
            <div>VietDub Local {about.data.app_version} · llama.cpp {about.data.runtime_build} · VieNeu SDK {about.data.tts ?? '—'}</div>
            <div className="muted">Không liên kết hay được bảo trợ bởi YouTube, Google, Qwen hoặc VieNeu. Chỉ dùng với nội dung bạn có quyền xem/dùng.</div>
            <table><tbody>{about.data.models.map((m) => <tr key={m.model_id}><td>{m.model_id}</td><td>{m.repo}@{m.revision.slice(0, 8)}</td><td>{m.license}</td></tr>)}</tbody></table>
            {about.data.notices_md && <details><summary>Thông báo bên thứ ba</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{about.data.notices_md}</pre></details>}
          </div>
        )}
      </Card>
    </div>
  );
}
