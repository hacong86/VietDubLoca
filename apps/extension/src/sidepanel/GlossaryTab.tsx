import { useState } from 'react';
import { api } from '../shared/api';
import { Card, Confirm, ErrorBox, downloadText, useAsync } from './ui';

interface Entry {
  entry_id?: string | null;
  source: string;
  domain: string;
  policy: 'preserve' | 'translate';
  case_sensitive: boolean;
  whole_phrase: boolean;
  target_display: string | null;
  target_spoken: string | null;
  enabled: boolean;
}

const DOMAINS = ['general', 'unity', 'ai_coding', 'business', 'numbers', 'conversational'];
const blank = (): Entry => ({ source: '', domain: 'general', policy: 'preserve', case_sensitive: true, whole_phrase: true, target_display: null, target_spoken: null, enabled: true });

export function GlossaryTab() {
  const g = useAsync(() => api<{ version: number; value: { version: number; entries: Entry[] } }>('GET', '/v1/glossary'));
  const [edit, setEdit] = useState<{ idx: number | null; e: Entry } | null>(null);
  const [del, setDel] = useState<number | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [note, setNote] = useState('');
  const entries = g.data?.value.entries ?? [];

  const save = async (next: Entry[]) => {
    setErr(null);
    try {
      const r = await api<{ version: number; invalidated_future_units: number }>('PUT', '/v1/glossary', { version: g.data?.version, entries: next }, { 'If-Match': String(g.data?.version ?? '') });
      setNote(`Đã lưu phiên bản ${r.version}. ${r.invalidated_future_units ? `${r.invalidated_future_units} câu sắp tới sẽ được dịch lại.` : ''}`);
      await g.reload();
    } catch (e) {
      setErr(e);
      await g.reload();
    }
  };

  const onImport = async (f: File | undefined) => {
    if (!f) return;
    try {
      if (f.size > 1024 * 1024) throw new Error('Tệp quá lớn');
      const data = JSON.parse(await f.text()) as { entries?: unknown };
      const list = Array.isArray(data) ? data : data.entries;
      if (!Array.isArray(list)) throw new Error('Thiếu mảng entries');
      const r = await api<{ version: number; conflicts_overwritten: string[] }>('POST', '/v1/glossary/import', { entries: list });
      setNote(`Đã nhập. Phiên bản ${r.version}.${r.conflicts_overwritten.length ? ` Ghi đè ${r.conflicts_overwritten.length} mục trùng: ${r.conflicts_overwritten.slice(0, 5).join(', ')}` : ''}`);
      await g.reload();
    } catch (e) {
      setErr(e instanceof Error && !(e as { code?: string }).code ? { code: 'VALIDATION_FAILED', message: e.message } : e);
    }
  };

  return (
    <div className="stack">
      <Card title="Từ điển thuật ngữ" actions={<button className="btn primary" onClick={() => setEdit({ idx: null, e: blank() })}>Thêm</button>}>
        <p className="small muted" style={{ marginTop: 0 }}>
          <b>Giữ nguyên</b>: tên nút/lệnh như "Apply Root Motion" luôn giữ đúng chữ. <b>Dịch</b>: gợi ý thuật ngữ theo lĩnh vực (vd "gross margin" → "biên lợi nhuận gộp" chỉ trong kinh doanh).
          <b> Cách đọc</b> chỉ đổi giọng đọc, không đổi phụ đề.
        </p>
        <div className="row">
          <label className="btn">Nhập JSON<input type="file" accept="application/json,.json" className="sr-only" onChange={(e) => void onImport(e.target.files?.[0])} /></label>
          <button className="btn" onClick={() => downloadText('vietdub-glossary.json', JSON.stringify({ version: g.data?.version, entries }, null, 2), 'application/json')}>Xuất JSON</button>
          <span className="small muted">Phiên bản {g.data?.version ?? '…'} · {entries.length} mục</span>
        </div>
        {note && <div className="status ok small" style={{ marginTop: 8 }}>{note}</div>}
      </Card>
      <ErrorBox error={err ?? g.error} />
      {entries.length === 0 && g.data && (
        <div className="card empty">Chưa có thuật ngữ nào. Bấm <b>Thêm</b> để giữ nguyên tên nút/lệnh (vd "Apply Root Motion"), hoặc <b>Nhập JSON</b> từ tệp có sẵn.</div>
      )}
      <div style={{ overflowX: 'auto' }} hidden={entries.length === 0}>
        <table>
          <thead><tr><th>Cụm từ</th><th>Lĩnh vực</th><th>Kiểu</th><th>Hiển thị / cách đọc</th><th /></tr></thead>
          <tbody>
            {entries.map((e, i) => (
              <tr key={`${e.domain}:${e.source}`} style={{ opacity: e.enabled ? 1 : 0.5 }}>
                <td>{e.source}{e.case_sensitive ? '' : ' (không phân biệt hoa thường)'}</td>
                <td>{e.domain}</td>
                <td>{e.policy === 'preserve' ? 'Giữ nguyên' : 'Dịch'}</td>
                <td>{e.target_display ?? '—'}{e.target_spoken ? ` / đọc: ${e.target_spoken}` : ''}</td>
                <td className="row"><button className="btn" onClick={() => setEdit({ idx: i, e: { ...e } })}>Sửa</button>
                  <button className="btn danger" onClick={() => setDel(i)}>Xóa</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {edit && (
        <div className="modal-bg" role="dialog" aria-modal="true" aria-label="Sửa thuật ngữ">
          <div className="modal stack">
            <label className="field"><span>Cụm từ gốc</span><input type="text" value={edit.e.source} onChange={(x) => setEdit({ ...edit, e: { ...edit.e, source: x.target.value } })} /></label>
            <div className="row">
              <label className="field" style={{ flex: 1 }}><span>Lĩnh vực</span>
                <select value={edit.e.domain} onChange={(x) => setEdit({ ...edit, e: { ...edit.e, domain: x.target.value } })}>{DOMAINS.map((d) => <option key={d}>{d}</option>)}</select></label>
              <label className="field" style={{ flex: 1 }}><span>Kiểu</span>
                <select value={edit.e.policy} onChange={(x) => setEdit({ ...edit, e: { ...edit.e, policy: x.target.value as Entry['policy'] } })}>
                  <option value="preserve">Giữ nguyên</option><option value="translate">Dịch thành…</option></select></label>
            </div>
            {edit.e.policy === 'translate' && <label className="field"><span>Bản Việt</span><input type="text" value={edit.e.target_display ?? ''} onChange={(x) => setEdit({ ...edit, e: { ...edit.e, target_display: x.target.value } })} /></label>}
            <label className="field"><span>Cách đọc (tùy chọn)</span><input type="text" value={edit.e.target_spoken ?? ''} onChange={(x) => setEdit({ ...edit, e: { ...edit.e, target_spoken: x.target.value || null } })} /></label>
            <label className="row small"><input type="checkbox" checked={edit.e.case_sensitive} onChange={(x) => setEdit({ ...edit, e: { ...edit.e, case_sensitive: x.target.checked } })} /> Phân biệt hoa thường</label>
            <label className="row small"><input type="checkbox" checked={edit.e.whole_phrase} onChange={(x) => setEdit({ ...edit, e: { ...edit.e, whole_phrase: x.target.checked } })} /> Chỉ khớp nguyên cụm</label>
            <label className="row small"><input type="checkbox" checked={edit.e.enabled} onChange={(x) => setEdit({ ...edit, e: { ...edit.e, enabled: x.target.checked } })} /> Đang dùng</label>
            <div className="row" style={{ justifyContent: 'flex-end' }}>
              <button className="btn" onClick={() => setEdit(null)}>Hủy</button>
              <button className="btn primary" disabled={!edit.e.source.trim() || (edit.e.policy === 'translate' && !edit.e.target_display?.trim())} onClick={() => {
                const next = [...entries];
                const e = { ...edit.e, source: edit.e.source.trim(), target_display: edit.e.policy === 'preserve' ? edit.e.source.trim() : edit.e.target_display };
                if (edit.idx === null) next.push(e);
                else next[edit.idx] = e;
                setEdit(null);
                void save(next);
              }}>Lưu</button>
            </div>
          </div>
        </div>
      )}
      <Confirm open={del !== null} danger title="Xóa thuật ngữ?" confirmText="Xóa" body={<span>{del !== null ? entries[del]?.source : ''}</span>}
        onCancel={() => setDel(null)} onConfirm={() => { const next = entries.filter((_, i) => i !== del); setDel(null); void save(next); }} />
    </div>
  );
}
