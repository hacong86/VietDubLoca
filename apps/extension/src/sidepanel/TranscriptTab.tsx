import { useEffect, useMemo, useRef, useState } from 'react';
import type { Segment } from '../../../../packages/contracts/src';
import { api, fmtTime } from '../shared/api';
import type { PanelStatus } from '../shared/messages';
import { T } from '../shared/strings';
import { Card, Confirm, ErrorBox, downloadText, sendBg, useInterval } from './ui';

const FLAG_VI: Record<string, string> = {
  USER_OVERRIDE: 'Do bạn sửa', REPAIRED: 'Đã thử dịch lại', LANG_SUSPECT: 'Nghi sai ngôn ngữ', WRONG_TARGET_SCRIPT: 'Bản dịch chưa phải tiếng Việt — bấm Sửa rồi Dịch lại', EMPTY: 'Rỗng',
  TRUNCATED: 'Bị cắt ngắn', MISSING_ID: 'Thiếu câu', JSON_INVALID: 'Sai định dạng',
};
const flagVi = (f: string) => FLAG_VI[f] ?? (f.startsWith('LENGTH_RATIO') ? 'Độ dài bất thường' : f.startsWith('PLACEHOLDER') ? 'Mất tên/mã được bảo vệ' : f);

export function TranscriptTab({ status, tabId }: { status: PanelStatus | null; tabId: number | null }) {
  const s = status?.session;
  const [segs, setSegs] = useState<Segment[]>([]);
  const [q, setQ] = useState('');
  const [follow, setFollow] = useState(true);
  const [edit, setEdit] = useState<Segment | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [exp, setExp] = useState<{ format: 'srt' | 'vtt'; kind: 'vi' | 'bilingual' } | null>(null);
  const [ack, setAck] = useState(false);
  const listRef = useRef<HTMLUListElement>(null);

  const load = async () => {
    if (!s) return;
    try {
      const r = await api<{ segments: Segment[] }>('GET', `/v1/sessions/${s.session_id}/segments`);
      setSegs(r.segments);
    } catch (e) {
      setErr(e);
    }
  };
  useEffect(() => void load(), [s?.session_id]);
  useInterval(load, s ? 2000 : null);

  const now = status?.media_ms ?? s?.media_ms ?? 0;
  const current = useMemo(() => segs.find((x) => x.start_ms <= now && now < x.end_ms + 400)?.segment_id, [segs, now]);
  const shown = useMemo(() => {
    const k = q.trim().toLowerCase();
    return k ? segs.filter((x) => x.source_text.toLowerCase().includes(k) || x.target_display.toLowerCase().includes(k)) : segs;
  }, [segs, q]);
  useEffect(() => {
    if (!follow || !current || q) return;
    const el = listRef.current?.querySelector(`[data-seg="${current}"]`);
    el?.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }, [current, follow, q]);

  const seek = (ms: number) => {
    if (tabId != null) void chrome.tabs.sendMessage(tabId, { ns: 'vietdub', type: 'video.seek', media_ms: ms }).catch(() => undefined);
  };

  const doExport = async () => {
    if (!s || !exp) return;
    try {
      const r = await api<{ file_name: string; content: string }>('POST', '/v1/export/subtitles', { session_id: s.session_id, ...exp, ack_rights: true });
      downloadText(r.file_name, r.content, exp.format === 'vtt' ? 'text/vtt;charset=utf-8' : 'application/x-subrip;charset=utf-8');
      setExp(null);
      setAck(false);
    } catch (e) {
      setErr(e);
    }
  };

  if (!s) return <Card title="Bản dịch"><p className="muted">Bật tiếng Việt trên một video để xem bản dịch theo câu.</p></Card>;

  return (
    <div className="stack">
      <Card>
        <div className="row">
          <input type="search" placeholder="Tìm trong bản dịch…" aria-label="Tìm trong bản dịch" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1 }} />
          <label className="row small"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Cuộn theo video</label>
        </div>
        <div className="row small" style={{ marginTop: 8 }}>
          <span className="muted">Xuất phụ đề:</span>
          <button className="btn" onClick={() => setExp({ format: 'srt', kind: 'vi' })}>SRT Việt</button>
          <button className="btn" onClick={() => setExp({ format: 'srt', kind: 'bilingual' })}>SRT song ngữ</button>
          <button className="btn" onClick={() => setExp({ format: 'vtt', kind: 'vi' })}>VTT Việt</button>
        </div>
      </Card>
      <ErrorBox error={err} />
      <ul className="list" ref={listRef} aria-label="Danh sách câu">
        {shown.map((x) => (
          <li key={x.segment_id} data-seg={x.segment_id} className={`seg-item ${x.segment_id === current ? 'current' : ''}`}
            tabIndex={0} onClick={() => seek(x.start_ms)} onKeyDown={(e) => e.key === 'Enter' && seek(x.start_ms)}
            aria-label={`Câu lúc ${fmtTime(x.start_ms)}. Bấm Enter để tua tới.`}>
            <div className="row between">
              <span className="t">{fmtTime(x.start_ms)}{x.speaker ? ` · ${x.speaker}` : ''}</span>
              <span className="row" onClick={(e) => e.stopPropagation()}>
                <button className="btn small" onClick={() => { seek(x.start_ms); }} aria-label="Nghe lại câu này">Nghe lại</button>
                <button className="btn small" onClick={() => setEdit(x)} aria-label="Sửa bản dịch câu này">Sửa</button>
              </span>
            </div>
            <div className="en">{x.source_text}</div>
            <div className="vi" lang="vi">{x.status === 'blocked' ? `${T.blocked}.` : x.status === 'pending' || x.status === 'translating' ? '…' : x.target_display}</div>
            {(x.flags.length > 0 || x.audio === 'failed') && (
              <div className="flags"><span className="badge warn">{[...x.flags.map(flagVi), ...(x.audio === 'failed' ? ['Chưa tạo được giọng'] : [])].join(' · ')}</span></div>
            )}
          </li>
        ))}
      </ul>
      {edit && <EditModal seg={edit} onClose={() => { setEdit(null); void load(); }} />}
      <Confirm open={!!exp} title="Xuất phụ đề" confirmText="Xuất tệp" onCancel={() => { setExp(null); setAck(false); }} onConfirm={() => ack && void doExport()}
        body={<span className="small">Mốc thời gian theo video gốc (không tính các lần tạm dừng tự động). Không kèm video/âm thanh.</span>}>
        <label className="row small"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> Tôi chỉ dùng phụ đề này cho nội dung mình có quyền sử dụng.</label>
      </Confirm>
    </div>
  );
}

function EditModal({ seg, onClose }: { seg: Segment; onClose: () => void }) {
  const [display, setDisplay] = useState(seg.target_display);
  const [spoken, setSpoken] = useState(seg.target_spoken);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      onClose();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);
  return (
    <div className="modal-bg" role="dialog" aria-modal="true" aria-label="Sửa bản dịch">
      <div className="modal stack">
        <h2 style={{ margin: 0, fontSize: 16 }}>Sửa bản dịch — {fmtTime(seg.start_ms)}</h2>
        <label className="field"><span>Câu gốc (chỉ đọc)</span><textarea readOnly value={seg.source_text} /></label>
        <label className="field"><span>Chữ hiển thị (phụ đề, giữ nguyên tên nút/code)</span><textarea value={display} onChange={(e) => setDisplay(e.target.value)} lang="vi" /></label>
        <label className="field"><span>Cách đọc (chỉ đổi giọng đọc, không đổi phụ đề)</span><textarea value={spoken} onChange={(e) => setSpoken(e.target.value)} lang="vi" /></label>
        <ErrorBox error={err} />
        <div className="row">
          <button className="btn" disabled={busy} onClick={() => void sendBg({ type: 'panel.preview', text: spoken || display })}>Nghe thử</button>
          <button className="btn primary" disabled={busy || !display.trim()} onClick={() => act(() => api('PATCH', `/v1/segments/${seg.segment_id}`,
            { target_display: display, target_spoken: spoken }, { 'If-Match': String(seg.revision) }))}>Lưu bản sửa</button>
          <button className="btn" disabled={busy} onClick={() => act(() => api('POST', `/v1/segments/${seg.segment_id}/retranslate`))}>Dịch lại</button>
          {seg.override && <button className="btn" disabled={busy} onClick={() => act(() => api('POST', `/v1/segments/${seg.segment_id}/undo`))}>Hoàn tác bản sửa</button>}
          <button className="btn" onClick={onClose}>Đóng</button>
        </div>
        <p className="small muted" style={{ margin: 0 }}>Lưu sẽ tạo phiên bản mới; âm thanh cũ của câu bị hủy và tạo lại.</p>
      </div>
    </div>
  );
}
