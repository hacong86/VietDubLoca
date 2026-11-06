import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError } from '../shared/api';
import { ERROR_ACTION_VI } from '../shared/strings';

export function Card({ title, children, actions }: { title?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="row between">
          {title && <h2>{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error instanceof ApiError ? error : null;
  const code = e?.code ?? (error as { code?: string })?.code ?? 'INTERNAL';
  const msg = e?.messageVi || (typeof error === 'string' ? error : (error as { message?: string })?.message || 'Có lỗi xảy ra.');
  const action = (e?.details?.action_vi as string | undefined) ?? ERROR_ACTION_VI[code];
  return (
    <div className="status err" role="alert">
      <div><span className="dot err" aria-hidden />{msg}</div>
      {action && <div className="small">Cách xử lý: {action}</div>}
      <div className="small muted">Mã lỗi: {code}</div>
    </div>
  );
}

export function Confirm({ open, title, body, confirmText, danger, onCancel, onConfirm, children }: {
  open: boolean; title: string; body?: ReactNode; confirmText: string; danger?: boolean; onCancel: () => void; onConfirm: () => void; children?: ReactNode;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onCancel();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [open, onCancel]);
  if (!open) return null;
  return (
    <div className="modal-bg" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal stack">
        <h2 style={{ margin: 0, fontSize: 16 }}>{title}</h2>
        {body && <div>{body}</div>}
        {children}
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onCancel} ref={ref}>Hủy</button>
          <button className={`btn ${danger ? 'danger' : 'primary'}`} onClick={onConfirm}>{confirmText}</button>
        </div>
      </div>
    </div>
  );
}

export function useInterval(fn: () => void, ms: number | null) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    if (ms === null) return;
    const id = setInterval(() => saved.current(), ms);
    return () => clearInterval(id);
  }, [ms]);
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const reload = async () => {
    setLoading(true);
    try {
      setData(await fn());
      setError(null);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, loading, reload, setData };
}

/** Tải tệp do chính trang extension tạo (blob) — người dùng bấm nút. */
export function downloadText(name: string, text: string, mime = 'text/plain;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export function sendBg<T = unknown>(msg: Record<string, unknown>): Promise<T> {
  return chrome.runtime.sendMessage({ ns: 'vietdub', ...msg }) as Promise<T>;
}
