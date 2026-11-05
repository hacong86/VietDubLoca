/**
 * Time-stretch giữ cao độ bằng WSOLA (Waveform Similarity Overlap-Add). Mã tự viết (không phụ thuộc thư viện
 * DSP ngoài → không vướng license, docs/06 §4). tempo > 1: nhanh hơn/ngắn hơn; tempo < 1: chậm hơn/dài hơn.
 * KHÔNG dùng playbackRate của AudioBufferSourceNode (làm đổi cao độ).
 */

export interface WsolaOptions {
  sampleRate: number;
  frameMs?: number;   // độ dài khung
  searchMs?: number;  // khoảng tìm độ tương đồng
}

function hann(n: number): Float32Array {
  const w = new Float32Array(n);
  for (let i = 0; i < n; i++) w[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1));
  return w;
}

export function timeStretch(input: Float32Array, tempo: number, opt: WsolaOptions): Float32Array {
  if (!(tempo > 0) || !Number.isFinite(tempo)) throw new Error('bad tempo');
  if (Math.abs(tempo - 1) < 1e-3 || input.length === 0) return input.slice();
  const frame = Math.max(64, Math.round(((opt.frameMs ?? 30) * opt.sampleRate) / 1000)) & ~1;
  const hop = frame >> 1;                                   // overlap 50 %
  const search = Math.round(((opt.searchMs ?? 12) * opt.sampleRate) / 1000);
  const win = hann(frame);
  const outLen = Math.ceil(input.length / tempo) + frame;
  const out = new Float32Array(outLen);
  const norm = new Float32Array(outLen);
  let outPos = 0;
  let inPos = 0;                                            // vị trí đọc lý tưởng
  let prevStart = 0;
  const step = 4;                                           // tương quan trên mẫu thưa cho nhanh
  while (true) {
    const ideal = Math.round(inPos);
    if (ideal + frame >= input.length) break;
    let best = ideal;
    if (outPos > 0) {
      // Tìm vị trí gần ideal có dạng sóng khớp nhất với phần tiếp nối tự nhiên của khung trước.
      const natural = prevStart + hop;
      let bestScore = -Infinity;
      const lo = Math.max(0, ideal - search);
      const hi = Math.min(input.length - frame - 1, ideal + search);
      for (let cand = lo; cand <= hi; cand += 2) {
        let s = 0;
        for (let k = 0; k < hop; k += step) {
          const a = input[natural + k] ?? 0;
          s += a * input[cand + k]!;
        }
        if (s > bestScore) {
          bestScore = s;
          best = cand;
        }
      }
    }
    for (let k = 0; k < frame; k++) {
      const o = outPos + k;
      if (o >= outLen) break;
      out[o] = out[o]! + input[best + k]! * win[k]!;
      norm[o] = norm[o]! + win[k]!;
    }
    prevStart = best;
    outPos += hop;
    inPos += hop * tempo;
  }
  // phần đuôi còn lại (ít hơn một khung): nối thẳng để không mất chữ cuối
  const tailStart = Math.round(inPos);
  for (let k = 0; tailStart + k < input.length && outPos + k < outLen; k++) {
    const o = outPos + k;
    out[o] = out[o]! + input[tailStart + k]! * (norm[o]! < 1 ? 1 - norm[o]! : 0);
    norm[o] = Math.max(norm[o]!, 1);
  }
  const finalLen = Math.min(outLen, Math.round(input.length / tempo));
  const res = new Float32Array(finalLen);
  for (let i = 0; i < finalLen; i++) {
    const n = norm[i]!;
    res[i] = n > 1e-3 ? out[i]! / n : out[i]!;
  }
  return res;
}

/** Ước lượng tần số cơ bản bằng zero-crossing trên đoạn tín hiệu tuần hoàn (dùng cho test giữ cao độ). */
export function zeroCrossFreq(x: Float32Array, sampleRate: number): number {
  let zc = 0;
  for (let i = 1; i < x.length; i++) if ((x[i - 1]! < 0 && x[i]! >= 0)) zc++;
  return (zc * sampleRate) / x.length;
}
