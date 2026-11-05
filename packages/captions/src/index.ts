/**
 * Parser phụ đề (docs/05 §3, FR-007): SRT/VTT UTF-8/BOM/CRLF, ≤10 MiB, ≤100.000 cue.
 * Không bao giờ render markup: chỉ trả text đã gỡ thẻ; lỗi có số dòng; overlap giữ nguyên làm metadata.
 * YouTube json3 (timedtext) → cue có mốc thời gian nguồn.
 */

export const MAX_SUBTITLE_BYTES = 10 * 1024 * 1024;
export const MAX_CUES = 100_000;

export interface ParsedCue {
  index: number;
  startMs: number;
  endMs: number;
  text: string;
  line: number;
  voice?: string;
}

export interface ParseIssue {
  line: number;
  reason: string;
}

export interface ParseResult {
  format: 'srt' | 'vtt' | 'unknown';
  cues: ParsedCue[];
  errors: ParseIssue[];
  warnings: ParseIssue[];
}

const TS = /^\s*(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})/;
const TAG = /<\/?[a-zA-Z][^<>]{0,64}>|<\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}>/g;
const VOICE = /<v(?:\.[\w.-]+)?\s+([^>]{1,64})>/i;

const ENTITIES: Record<string, string> = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'", '&nbsp;': ' ', '&lrm;': '', '&rlm;': '' };

export function decodeEntities(s: string): string {
  return s
    .replace(/&(amp|lt|gt|quot|#39|nbsp|lrm|rlm);/g, (m) => ENTITIES[m] ?? m)
    .replace(/&#(\d{1,6});/g, (_m, d: string) => safeCodePoint(Number(d)))
    .replace(/&#x([0-9a-f]{1,6});/gi, (_m, h: string) => safeCodePoint(parseInt(h, 16)));
}

function safeCodePoint(n: number): string {
  if (!Number.isFinite(n) || n <= 0 || n > 0x10ffff || (n >= 0xd800 && n <= 0xdfff)) return '';
  return String.fromCodePoint(n);
}

/** Gỡ markup theo allowlist → text thuần (không bao giờ HTML). */
export function cleanCueText(raw: string): { text: string; voice?: string } {
  const vm = VOICE.exec(raw);
  const noTags = raw.replace(TAG, '');
  const text = decodeEntities(noTags)
    .replace(/[\u200B\uFEFF]/g, '')
    .normalize('NFC')
    .replace(/\s+/g, ' ')
    .trim();
  return vm?.[1] ? { text, voice: vm[1].trim() } : { text };
}

function ms(h: string | undefined, m: string, s: string, f: string): number {
  return ((Number(h ?? 0) * 60 + Number(m)) * 60 + Number(s)) * 1000 + Number(f.padEnd(3, '0').slice(0, 3));
}

export function decodeSubtitleBytes(buf: ArrayBuffer): string {
  if (buf.byteLength > MAX_SUBTITLE_BYTES) throw new Error('FILE_TOO_LARGE');
  const text = new TextDecoder('utf-8', { fatal: false, ignoreBOM: false }).decode(buf);
  return text;
}

export function parseSubtitles(input: string, durationMs?: number): ParseResult {
  const text = input.replace(/^\uFEFF/, '');
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  const format: ParseResult['format'] = lines[0]?.startsWith('WEBVTT') ? 'vtt' : TS.test(lines[1] ?? '') || TS.test(lines[0] ?? '') ? 'srt' : 'unknown';
  const res: ParseResult = { format, cues: [], errors: [], warnings: [] };
  let i = format === 'vtt' ? 1 : 0;
  while (i < lines.length) {
    const line = lines[i] ?? '';
    const m = TS.exec(line);
    if (!m) {
      i++;
      continue;
    }
    const start = ms(m[1], m[2]!, m[3]!, m[4]!);
    const end = ms(m[5], m[6]!, m[7]!, m[8]!);
    const at = i + 1;
    i++;
    const body: string[] = [];
    while (i < lines.length && (lines[i] ?? '').trim() !== '' && !TS.test(lines[i] ?? '')) {
      body.push(lines[i] ?? '');
      i++;
    }
    if (end < start) {
      res.errors.push({ line: at, reason: 'Thời điểm kết thúc nhỏ hơn thời điểm bắt đầu' });
      continue;
    }
    const cleaned = cleanCueText(body.join('\n'));
    if (!cleaned.text) continue;
    if (durationMs !== undefined && end > durationMs + 1000) res.warnings.push({ line: at, reason: 'Mốc thời gian vượt độ dài video' });
    const prev = res.cues[res.cues.length - 1];
    if (prev && start < prev.endMs) res.warnings.push({ line: at, reason: 'Cue chồng thời gian với cue trước (giữ nguyên)' });
    res.cues.push({ index: res.cues.length + 1, startMs: start, endMs: end, text: cleaned.text, line: at, ...(cleaned.voice ? { voice: cleaned.voice } : {}) });
    if (res.cues.length > MAX_CUES) {
      res.errors.push({ line: at, reason: 'Quá 100.000 cue' });
      break;
    }
  }
  if (format === 'unknown' && res.cues.length === 0) res.errors.push({ line: 1, reason: 'Không nhận ra định dạng SRT/VTT' });
  return res;
}

/** YouTube timedtext json3 → cue. Event chỉ có xuống dòng (aAppend) bị bỏ. */
export interface Json3Event {
  tStartMs?: number;
  dDurationMs?: number;
  segs?: { utf8?: string }[];
  aAppend?: number;
}

export function parseJson3(data: unknown): ParsedCue[] {
  if (!data || typeof data !== 'object' || !Array.isArray((data as { events?: unknown }).events)) throw new Error('JSON3_INVALID');
  const out: ParsedCue[] = [];
  for (const ev of (data as { events: Json3Event[] }).events) {
    if (typeof ev.tStartMs !== 'number' || !Array.isArray(ev.segs)) continue;
    const raw = ev.segs.map((s) => (typeof s.utf8 === 'string' ? s.utf8 : '')).join('');
    const { text } = cleanCueText(raw);
    if (!text) continue;
    const start = Math.max(0, Math.round(ev.tStartMs));
    const end = start + Math.max(0, Math.round(ev.dDurationMs ?? 0));
    out.push({ index: out.length + 1, startMs: start, endMs: end, text, line: out.length + 1 });
    if (out.length > MAX_CUES) break;
  }
  // json3 auto: event sau có thể bắt đầu trước khi event trước kết thúc (hiển thị 2 dòng) — cắt end để không chồng.
  for (let k = 0; k + 1 < out.length; k++) {
    const a = out[k]!;
    const b = out[k + 1]!;
    if (a.endMs > b.startMs && b.startMs > a.startMs) a.endMs = b.startMs;
  }
  return out;
}

/** Nội dung timedtext bất kỳ định dạng YouTube hay dùng: json3 hoặc XML srv3 (<p t d>) / srv1 (<text start dur>). */
export function parseTimedtextBody(body: string): ParsedCue[] {
  const t = body.trim();
  if (!t) return [];
  if (t.startsWith('{')) return parseJson3(JSON.parse(t));
  if (!t.startsWith('<')) throw new Error('TIMEDTEXT_UNKNOWN');
  const out: ParsedCue[] = [];
  const srv3 = /<p\b([^>]*)>([\s\S]*?)<\/p>/g;
  const srv1 = /<text\b([^>]*)>([\s\S]*?)<\/text>/g;
  const attr = (a: string, k: string) => {
    const m = new RegExp(`\\b${k}="([\\d.]+)"`).exec(a);
    return m ? Number(m[1]) : null;
  };
  let m: RegExpExecArray | null;
  const push = (startMs: number, durMs: number, inner: string) => {
    const { text } = cleanCueText(decodeEntities(inner.replace(/<br\s*\/?>/g, ' ')));
    if (text) out.push({ index: out.length + 1, startMs: Math.round(startMs), endMs: Math.round(startMs + durMs), text, line: out.length + 1 });
  };
  while ((m = srv3.exec(t))) {
    const s0 = attr(m[1]!, 't');
    if (s0 !== null) push(s0, attr(m[1]!, 'd') ?? 0, m[2]!);
  }
  if (out.length === 0) {
    while ((m = srv1.exec(t))) {
      const s0 = attr(m[1]!, 'start');
      if (s0 !== null) push(s0 * 1000, (attr(m[1]!, 'dur') ?? 0) * 1000, m[2]!);
    }
  }
  return out.slice(0, MAX_CUES);
}

/** "1:02:03" | "12:34" → ms (transcript DOM). */
export function parseClock(ts: string): number | null {
  const parts = ts.trim().split(':').map((x) => Number(x));
  if (parts.length < 2 || parts.length > 3 || parts.some((x) => !Number.isFinite(x) || x < 0)) return null;
  const [h, m, s] = parts.length === 3 ? parts : [0, parts[0]!, parts[1]!];
  return ((h! * 60 + m!) * 60 + s!) * 1000;
}

/** Cue từ danh sách (timestamp, text) của transcript DOM: end = start kế tiếp (cap 8 s). */
export function cuesFromTranscript(rows: { ts: string; text: string }[]): ParsedCue[] {
  const out: ParsedCue[] = [];
  const starts = rows.map((r) => parseClock(r.ts));
  rows.forEach((r, i) => {
    const s = starts[i];
    if (s === null || s === undefined) return;
    const { text } = cleanCueText(r.text);
    if (!text) return;
    const next = starts.slice(i + 1).find((x): x is number => x !== null && x !== undefined);
    const end = next !== undefined && next > s ? Math.min(next, s + 8000) : s + 4000;
    out.push({ index: out.length + 1, startMs: s, endMs: end, text, line: i + 1 });
  });
  return out;
}
