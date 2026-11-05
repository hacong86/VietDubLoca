/**
 * Client REST broker cho extension pages tin cậy (SW, offscreen, side panel, options). Token lấy từ
 * chrome.storage.session (mặc định chỉ TRUSTED_CONTEXTS đọc được, content script không đọc được).
 */
import { ProjectError } from '../../../../packages/contracts/src';

export interface Pairing {
  broker_url: string;
  session_token: string;
  expires_at: number;
}

export class ApiError extends Error {
  constructor(public readonly code: string, public readonly messageVi: string, public readonly status: number,
              public readonly details: Record<string, unknown> = {}) {
    super(code);
  }
}

export async function getPairing(): Promise<Pairing | null> {
  const r = await chrome.storage.session.get('pairing');
  const p = r.pairing as Pairing | undefined;
  if (!p || typeof p.broker_url !== 'string' || !/^http:\/\/127\.0\.0\.1:\d{2,5}$/.test(p.broker_url)) return null;
  if (p.expires_at * 1000 < Date.now() + 60_000) return null;
  return p;
}

export async function api<T = unknown>(method: string, path: string, body?: unknown, extraHeaders: Record<string, string> = {}): Promise<T> {
  const p = await getPairing();
  if (!p) throw new ApiError('AUTH_REQUIRED', 'Cần ghép nối lại với chương trình trên máy.', 401);
  if (!path.startsWith('/v1/')) throw new Error('bad path');
  let res: Response;
  try {
    res = await fetch(p.broker_url + path, {
      method,
      headers: { Authorization: `Bearer ${p.session_token}`, ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...extraHeaders },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: 'no-store',
      credentials: 'omit',
      redirect: 'error',
    });
  } catch {
    throw new ApiError('CONNECT_FAILED', 'Không kết nối được chương trình trên máy.', 0);
  }
  if (res.status === 204) return undefined as T;
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const e = ProjectError.safeParse(data);
    if (e.success) throw new ApiError(e.data.code, e.data.message_vi, res.status, e.data.details ?? {});
    throw new ApiError('INTERNAL', 'Có lỗi nội bộ.', res.status);
  }
  return data as T;
}

export function fmtTime(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

export function fmtBytes(n: number): string {
  if (n >= 1e9) return (n / 1e9).toFixed(2).replace('.', ',') + ' GB';
  if (n >= 1e6) return (n / 1e6).toFixed(0) + ' MB';
  return (n / 1e3).toFixed(0) + ' KB';
}
