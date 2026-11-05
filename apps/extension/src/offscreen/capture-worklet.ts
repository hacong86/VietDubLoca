/**
 * AudioWorklet thu âm tab cho ASR: nhánh ASR lấy TRƯỚC gain nghe (docs/03 §4). Gửi khối Float32 mono
 * (downmix) theo sample rate thực của AudioContext; resample 16 kHz làm ở offscreen (bandlimited).
 */
declare const sampleRate: number;
declare function registerProcessor(name: string, ctor: unknown): void;
declare class AudioWorkletProcessor {
  readonly port: MessagePort;
}

class VietdubCapture extends AudioWorkletProcessor {
  private buf: Float32Array = new Float32Array(4096);
  private n = 0;
  process(inputs: Float32Array[][]): boolean {
    const input = inputs[0];
    if (!input || input.length === 0 || !input[0]) return true;
    const len = input[0].length;
    for (let i = 0; i < len; i++) {
      let s = 0;
      for (let c = 0; c < input.length; c++) s += input[c]![i]!;
      this.buf[this.n++] = s / input.length;
      if (this.n === this.buf.length) {
        this.port.postMessage({ samples: this.buf, rate: sampleRate }, [this.buf.buffer]);
        this.buf = new Float32Array(4096);
        this.n = 0;
      }
    }
    return true;
  }
}
registerProcessor('vietdub-capture', VietdubCapture);
