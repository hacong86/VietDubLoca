/**
 * CaptionProvider cho YouTube (docs/05 §1–§2, FR-005/FR-006). Thứ tự: caption thủ công EN → auto EN →
 * transcript UI (coverage kiểm chứng) → (ngoài content) nhập SRT/VTT → ASR tab.
 * Mỗi bước có timeout, tối đa 2 lần thử; ghi "đã thử nguồn nào" để UI hiển thị.
 */
import { BridgePlayerInfo } from '../../../../packages/contracts/src';
import { cuesFromTranscript, parseJson3, parseTimedtextBody, type ParsedCue } from '../../../../packages/captions/src';
import type { CaptionPayload } from '../shared/messages';
import { readTranscriptDom } from './youtube';

const EN = ['en', 'en-US', 'en-GB'] as const;

function askBridge(type: 'get_player_info' | 'trigger_captions', extra: Record<string, unknown> = {}, timeoutMs = 4000): Promise<BridgePlayerInfo | null> {
  return new Promise((resolve) => {
    const nonce = crypto.getRandomValues(new Uint32Array(2)).join('-');
    const onMsg = (ev: MessageEvent) => {
      if (ev.source !== window || ev.data?.ns !== 'vietdub-bridge' || ev.data?.nonce !== nonce) return;
      window.removeEventListener('message', onMsg);
      clearTimeout(t);
      const parsed = BridgePlayerInfo.safeParse(ev.data);
      resolve(parsed.success ? parsed.data : null);
    };
    const t = setTimeout(() => {
      window.removeEventListener('message', onMsg);
      resolve(null);
    }, timeoutMs);
    window.addEventListener('message', onMsg);
    window.postMessage({ ns: 'vietdub-content', type, nonce, ...extra }, location.origin);
  });
}

/** Chỉ fetch URL timedtext của youtube.com; không nhận URL bất kỳ từ trang. */
export function safeTimedtextUrl(raw: string, videoId: string): URL | null {
  try {
    const u = new URL(raw, location.origin);
    if (u.protocol !== 'https:' || !/(^|\.)youtube\.com$/.test(u.hostname) || u.pathname !== '/api/timedtext') return null;
    if (u.searchParams.get('v') && u.searchParams.get('v') !== videoId) return null;
    u.searchParams.set('fmt', 'json3');
    return u;
  } catch {
    return null;
  }
}

async function fetchJson3(url: URL): Promise<ParsedCue[]> {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 8000);
  try {
    const r = await fetch(url.toString(), { credentials: 'include', signal: ctl.signal });
    if (!r.ok) return [];
    const txt = await r.text();
    if (!txt.trim() || txt.length > 20 * 1024 * 1024) return [];
    return parseJson3(JSON.parse(txt));
  } catch {
    return [];
  } finally {
    clearTimeout(t);
  }
}

function pickTracks(info: BridgePlayerInfo) {
  const en = info.tracks.filter((t) => EN.some((l) => t.language_code === l || t.language_code.startsWith('en')));
  const manual = en.filter((t) => t.kind !== 'asr').sort((a, b) => EN.indexOf(a.language_code as never) - EN.indexOf(b.language_code as never));
  const auto = en.filter((t) => t.kind === 'asr');
  return [...manual.map((t) => ({ t, auto: false })), ...auto.map((t) => ({ t, auto: true }))];
}

function toPayload(videoId: string, cues: ParsedCue[], kind: 'manual' | 'auto', lang: string, label: string, coverage: CaptionPayload['coverage'], tried: string[], sourceId: string): CaptionPayload {
  const language = (EN as readonly string[]).includes(lang) ? (lang as CaptionPayload['language']) : 'en';
  return {
    video_id: videoId, source_id: sourceId.slice(0, 128), source_kind: kind, language, coverage, label, tried,
    available_until_ms: cues.reduce((m, c) => Math.max(m, c.endMs), 0),
    cues: cues.map((c, i) => ({ cue_id: `c${i + 1}`, start_ms: c.startMs, end_ms: c.endMs, text: c.text, committed: true })),
  };
}

export async function discoverCaptions(videoId: string, durationMs: number | undefined): Promise<{ ok: true; payload: CaptionPayload } | { ok: false; reason: string; tried: string[] }> {
  const tried: string[] = [];
  let info = await askBridge('get_player_info');
  if (!info || info.video_id !== videoId) {
    await new Promise((r) => setTimeout(r, 1200));
    info = await askBridge('get_player_info');
  }
  if (info && info.video_id === videoId) {
    const tracks = pickTracks(info);
    if (tracks.length === 0) tried.push('Dữ liệu trang: video không có phụ đề tiếng Anh');
    for (const { t, auto } of tracks) {
      const label = `${auto ? 'Phụ đề tự động' : 'Phụ đề'} tiếng Anh (${t.language_code})`;
      const kind = auto ? 'asr' : '';
      const fromBody = (inf: BridgePlayerInfo | null): ParsedCue[] => {
        const b = inf?.captured_bodies?.find((x) => x.video_id === videoId && x.lang === t.language_code && x.kind === kind);
        if (!b) return [];
        try {
          return parseTimedtextBody(b.body);
        } catch {
          return [];
        }
      };
      // 1) nội dung player đã tự tải; 2) tải baseUrl; 3) bật caption tạm để player tải rồi đọc nội dung.
      let cues = fromBody(info);
      if (cues.length === 0) {
        const url = safeTimedtextUrl(t.base_url, videoId);
        cues = url ? await fetchJson3(url) : [];
      }
      for (let attempt = 0; attempt < 2 && cues.length === 0; attempt++) {
        const fresh = await askBridge('trigger_captions', { lang: t.language_code, kind }, 9000);
        cues = fromBody(fresh);
      }
      tried.push(`${label}: ${cues.length ? `${cues.length} dòng` : 'không tải được'}`);
      if (cues.length) {
        const last = cues[cues.length - 1]!.endMs;
        const coverage = durationMs && last < durationMs - 120_000 ? 'partial' : 'full';
        return { ok: true, payload: toPayload(videoId, cues, auto ? 'auto' : 'manual', t.language_code, label, coverage, tried,
          `yt-${videoId}-${auto ? 'asr' : 'man'}-${t.language_code}`) };
      }
    }
  } else {
    tried.push('Dữ liệu trang: không đọc được thông tin player');
  }
  // Transcript UI: chỉ gọi full khi danh sách ổn định VÀ phủ tới gần cuối video.
  const dom = await readTranscriptDom();
  if (dom) {
    const cues = cuesFromTranscript(dom.rows);
    const last = cues.length ? cues[cues.length - 1]!.endMs : 0;
    const coverage: CaptionPayload['coverage'] = dom.stable && (!durationMs || last >= durationMs - 60_000) ? 'full' : 'partial';
    tried.push(`Bản chép lời trên trang: ${cues.length} dòng (${coverage === 'full' ? 'đủ' : 'một phần'})`);
    if (cues.length) return { ok: true, payload: toPayload(videoId, cues, 'manual', 'en', 'Bản chép lời trên trang', coverage, tried, `yt-${videoId}-transcript`) };
  } else {
    tried.push('Bản chép lời trên trang: không có');
  }
  return { ok: false, reason: 'Không lấy được phụ đề tiếng Anh cho video này', tried };
}
