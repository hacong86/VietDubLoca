/**
 * Resampler streaming bandlimited → 16 kHz mono cho ASR (docs/05 §4). Lọc thông thấp FIR windowed-sinc
 * trước khi nội suy, KHÔNG "bỏ bớt mẫu mỗi 3 sample". Chạy trong AudioWorklet hoặc offscreen.
 */

export class StreamResampler {
  private readonly ratio: number;
  private readonly taps: Float32Array;
  private history: Float32Array;
  private pos = 0; // vị trí phân số trong luồng đã lọc (theo mẫu input)

  constructor(readonly inRate: number, readonly outRate = 16000, numTaps = 63) {
    if (inRate <= 0 || outRate <= 0) throw new Error('bad rate');
    this.ratio = inRate / outRate;
    const cutoff = (0.45 * outRate) / inRate; // chuẩn hóa theo inRate, chừa dải chuyển tiếp
    const n = numTaps | 1;
    const taps = new Float32Array(n);
    const m = (n - 1) / 2;
    let sum = 0;
    for (let i = 0; i < n; i++) {
      const x = i - m;
      const sinc = x === 0 ? 2 * cutoff : Math.sin(2 * Math.PI * cutoff * x) / (Math.PI * x);
      const w = 0.42 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1)) + 0.08 * Math.cos((4 * Math.PI * i) / (n - 1));
      taps[i] = sinc * w;
      sum += taps[i]!;
    }
    for (let i = 0; i < n; i++) taps[i] = taps[i]! / sum;
    this.taps = taps;
    this.history = new Float32Array(n - 1);
  }

  /** Nhận khối input mono (Float32 [-1,1]) → trả khối output 16 kHz. */
  process(input: Float32Array): Float32Array {
    const hist = this.history.length;
    const buf = new Float32Array(hist + input.length);
    buf.set(this.history, 0);
    buf.set(input, hist);
    // lọc FIR tại điểm cần lấy mẫu rồi nội suy tuyến tính giữa 2 điểm đã lọc
    const out: number[] = [];
    const filt = (idx: number): number => {
      let s = 0;
      const base = idx - (this.taps.length - 1);
      for (let k = 0; k < this.taps.length; k++) s += (buf[base + k] ?? 0) * this.taps[k]!;
      return s;
    };
    while (this.pos + 1 < input.length) {
      const i0 = Math.floor(this.pos);
      const frac = this.pos - i0;
      const a = filt(i0 + hist);
      const b = filt(i0 + 1 + hist);
      out.push(a + (b - a) * frac);
      this.pos += this.ratio;
    }
    this.pos -= input.length;
    this.history = buf.slice(buf.length - hist);
    return Float32Array.from(out);
  }
}

export function downmix(channels: Float32Array[]): Float32Array {
  if (channels.length === 1) return channels[0]!.slice();
  const n = channels[0]!.length;
  const out = new Float32Array(n);
  for (const ch of channels) for (let i = 0; i < n; i++) out[i] = out[i]! + ch[i]! / channels.length;
  return out;
}
