/** Audio protocol v1 (docs/08 §5): 4 byte BE header length + JSON UTF-8 + PCM s16le mono. */

export const MAX_HEADER = 4096;
export const MAX_FRAME = 256 * 1024;

export interface AudioHeader {
  protocol_version: 1;
  kind: 'asr_pcm' | 'tts_pcm';
  session_id: string;
  timeline_epoch: number;
  segment_id: string | null;
  revision: number;
  seq: number;
  sample_rate: 16000 | 48000;
  channels: 1;
  codec: 'pcm_s16le';
  sample_count: number;
  is_last: boolean;
  capture_monotonic_ms?: number | null;
  source_media_ms?: number | null;
}

const REQUIRED = ['protocol_version', 'kind', 'session_id', 'timeline_epoch', 'segment_id', 'revision', 'seq', 'sample_rate', 'channels', 'codec', 'sample_count', 'is_last'];
const ALLOWED = new Set([...REQUIRED, 'capture_monotonic_ms', 'source_media_ms']);

const isUInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 0;

export function validateHeader(h: Record<string, unknown>, pcmBytes: number): asserts h is AudioHeader & Record<string, unknown> {
  const keys = Object.keys(h);
  if (!REQUIRED.every((k) => k in h) || keys.some((k) => !ALLOWED.has(k))) throw new Error('bad header keys');
  if (h.protocol_version !== 1 || h.channels !== 1 || h.codec !== 'pcm_s16le') throw new Error('bad format');
  for (const k of ['timeline_epoch', 'revision', 'seq', 'sample_count']) if (!isUInt(h[k])) throw new Error('bad ' + k);
  if (typeof h.is_last !== 'boolean') throw new Error('bad is_last');
  if (typeof h.session_id !== 'string' || h.session_id.length < 1 || h.session_id.length > 128) throw new Error('bad session');
  if (h.kind === 'tts_pcm') {
    if (h.sample_rate !== 48000 || typeof h.segment_id !== 'string' || !h.segment_id) throw new Error('tts needs 48k + segment');
  } else if (h.kind === 'asr_pcm') {
    if (h.sample_rate !== 16000 || h.segment_id !== null) throw new Error('asr needs 16k + null segment');
    if (typeof h.capture_monotonic_ms !== 'number' || !Number.isFinite(h.capture_monotonic_ms) || h.capture_monotonic_ms < 0) throw new Error('asr clock');
    if (!isUInt(h.source_media_ms)) throw new Error('asr media clock');
  } else throw new Error('bad kind');
  if (pcmBytes !== (h.sample_count as number) * 2) throw new Error('pcm length mismatch');
}

const enc = new TextEncoder();
const dec = new TextDecoder('utf-8', { fatal: true });

export function packFrame(h: AudioHeader, pcm: Uint8Array): ArrayBuffer {
  validateHeader(h as unknown as Record<string, unknown>, pcm.byteLength);
  const raw = enc.encode(JSON.stringify(h));
  if (raw.byteLength > MAX_HEADER || 4 + raw.byteLength + pcm.byteLength > MAX_FRAME) throw new Error('frame too large');
  const out = new Uint8Array(4 + raw.byteLength + pcm.byteLength);
  new DataView(out.buffer).setUint32(0, raw.byteLength, false);
  out.set(raw, 4);
  out.set(pcm, 4 + raw.byteLength);
  return out.buffer;
}

export function unpackFrame(buf: ArrayBuffer): { header: AudioHeader; pcm: Int16Array } {
  if (buf.byteLength < 4 || buf.byteLength > MAX_FRAME) throw new Error('bad frame length');
  const n = new DataView(buf).getUint32(0, false);
  if (n < 1 || n > MAX_HEADER || 4 + n > buf.byteLength) throw new Error('bad header length');
  const h = JSON.parse(dec.decode(new Uint8Array(buf, 4, n))) as Record<string, unknown>;
  const pcmBytes = buf.byteLength - 4 - n;
  validateHeader(h, pcmBytes);
  // copy để căn 2 byte
  const pcm = new Int16Array(buf.slice(4 + n));
  return { header: h as unknown as AudioHeader, pcm };
}

export function s16ToFloat(pcm: Int16Array): Float32Array {
  const out = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) out[i] = pcm[i]! / 32768;
  return out;
}

export function floatToS16(x: Float32Array): Int16Array {
  const out = new Int16Array(x.length);
  for (let i = 0; i < x.length; i++) {
    const v = Math.max(-1, Math.min(1, Number.isFinite(x[i]!) ? x[i]! : 0));
    out[i] = Math.round(v * 32767);
  }
  return out;
}
