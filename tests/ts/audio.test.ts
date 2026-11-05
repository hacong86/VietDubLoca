import { describe, expect, it } from 'vitest';
import {
  StreamResampler, acceptItem, audioStartFor, catchUpResidual, classifyLate, floatToS16, mediaNow, packFrame, planUnit, preloadProgress,
  preparedAheadMs, resumeHoldInMs, s16ToFloat,
  timeStretch, unpackFrame, zeroCrossFreq,
} from '../../packages/audio/src';

const sine = (f: number, sec: number, sr: number) => Float32Array.from({ length: Math.round(sec * sr) }, (_, i) => 0.5 * Math.sin((2 * Math.PI * f * i) / sr));

describe('audio frame v1', () => {
  it('roundtrips and validates', () => {
    const pcm = floatToS16(sine(440, 0.1, 48000));
    const h = { protocol_version: 1, kind: 'tts_pcm', session_id: 's', timeline_epoch: 2, segment_id: 'u1', revision: 1, seq: 0, sample_rate: 48000, channels: 1, codec: 'pcm_s16le', sample_count: pcm.length, is_last: true } as const;
    const f = packFrame(h, new Uint8Array(pcm.buffer));
    const { header, pcm: back } = unpackFrame(f);
    expect(header.timeline_epoch).toBe(2);
    expect(Array.from(back.slice(0, 5))).toEqual(Array.from(pcm.slice(0, 5)));
    expect(() => packFrame({ ...h, sample_count: 3 }, new Uint8Array(pcm.buffer))).toThrow();
    expect(() => packFrame({ ...h, sample_rate: 16000 }, new Uint8Array(pcm.buffer))).toThrow();
    const bad = new Uint8Array(f.slice(0));
    new DataView(bad.buffer).setUint32(0, 999999, false);
    expect(() => unpackFrame(bad.buffer)).toThrow();
  });
  it('matches python framing (big-endian length)', () => {
    const pcm = new Int16Array([1, -1]);
    const h = { protocol_version: 1, kind: 'tts_pcm', session_id: 's', timeline_epoch: 0, segment_id: 'u', revision: 1, seq: 0, sample_rate: 48000, channels: 1, codec: 'pcm_s16le', sample_count: 2, is_last: false } as const;
    const f = new Uint8Array(packFrame(h, new Uint8Array(pcm.buffer)));
    const n = (f[0]! << 24) | (f[1]! << 16) | (f[2]! << 8) | f[3]!;
    expect(n).toBe(JSON.stringify(h).length);
    expect(s16ToFloat(pcm)[0]).toBeCloseTo(1 / 32768);
  });
});

describe('WSOLA time-stretch keeps pitch (SYS-08)', () => {
  it('2x shorter, same frequency', () => {
    const x = sine(220, 2, 48000);
    const y = timeStretch(x, 2, { sampleRate: 48000 });
    expect(y.length).toBeGreaterThan(48000 * 0.95);
    expect(y.length).toBeLessThan(48000 * 1.05);
    const f = zeroCrossFreq(y.slice(4800, 43200), 48000);
    expect(Math.abs(f - 220)).toBeLessThan(8);
  });
  it('0.75x longer, same frequency', () => {
    const x = sine(300, 1, 48000);
    const y = timeStretch(x, 0.75, { sampleRate: 48000 });
    expect(y.length).toBeCloseTo(64000, -3);
    expect(Math.abs(zeroCrossFreq(y.slice(4800, 56000), 48000) - 300)).toBeLessThan(10);
  });
});

describe('resampler 48k/44.1k → 16k bandlimited', () => {
  it('keeps in-band tone and length', () => {
    for (const sr of [48000, 44100]) {
      const rs = new StreamResampler(sr, 16000);
      const x = sine(1000, 1, sr);
      const parts: Float32Array[] = [];
      for (let i = 0; i < x.length; i += 128) parts.push(rs.process(x.slice(i, i + 128)));
      const y = Float32Array.from(parts.flatMap((p) => Array.from(p)));
      expect(Math.abs(y.length - 16000)).toBeLessThan(40);
      expect(Math.abs(zeroCrossFreq(y.slice(1000, 15000), 16000) - 1000)).toBeLessThan(15);
    }
  });
  it('attenuates above Nyquist (no aliasing 12 kHz → 4 kHz)', () => {
    const rs = new StreamResampler(48000, 16000);
    const y = rs.process(sine(12000, 0.5, 48000));
    const rms = Math.sqrt(y.slice(200).reduce((s, v) => s + v * v, 0) / (y.length - 200));
    expect(rms).toBeLessThan(0.02);
  });
});

describe('scheduling math', () => {
  const a = { mediaMs: 10000, audioTime: 5, rate: 1, playing: true, epoch: 0 };
  it('maps unit start to AudioContext time with rate', () => {
    expect(audioStartFor(12000, a)).toBeCloseTo(7);
    expect(audioStartFor(12000, { ...a, rate: 2 })).toBeCloseTo(6);
    expect(mediaNow(a, 6)).toBeCloseTo(11000);
  });
  it('residual catch-up ≤1.15 then hold, no double speed (FR-025)', () => {
    const fits = planUnit({ startMs: 0, endMs: 3000, nextStartMs: 4000, durationMs: 2500 }, 1);
    expect(fits.tempo).toBe(1);
    expect(fits.holdMs).toBe(0);
    const slightly = planUnit({ startMs: 0, endMs: 3000, nextStartMs: 3000, durationMs: 3300 }, 1);
    expect(slightly.residual).toBeCloseTo(1.1, 2);
    expect(slightly.holdMs).toBe(0);
    const long = planUnit({ startMs: 0, endMs: 3000, nextStartMs: 3000, durationMs: 5000 }, 1);
    expect(long.residual).toBe(1.15);
    expect(long.holdMs).toBeGreaterThan(1000);
    const at2x = planUnit({ startMs: 0, endMs: 3000, nextStartMs: 3000, durationMs: 3000 }, 2);
    expect(at2x.tempo).toBeCloseTo(2);          // chỉ stretch MỘT lần theo rate
    expect(at2x.playedMs).toBeCloseTo(1500);
    const borrow = planUnit({ startMs: 0, endMs: 3000, nextStartMs: 5000, durationMs: 3400 }, 1);
    expect(borrow.budgetMs).toBe(3500);          // mượn tối đa 500 ms lặng
    expect(borrow.tempo).toBe(1);
  });
  it('study mode (FR-029): no residual speed-up, hold video to finish the sentence', () => {
    const study = planUnit({ startMs: 0, endMs: 3000, nextStartMs: 3000, durationMs: 3300 }, 1, 1.15, 'study');
    expect(study.residual).toBe(1);
    expect(study.tempo).toBe(1);
    expect(study.holdMs).toBeCloseTo(300);
    // phát tiếp câu dở ở giây 2 (đã đọc 2 s của 3,3 s): khung 3 s còn 1 s, audio còn 1,3 s → giữ hình sau 1 s
    expect(resumeHoldInMs(study, { startMs: 0, durationMs: 3300 }, 2000, 1, 2, 'study')).toBeCloseTo(1000);
    const fitsResume = planUnit({ startMs: 0, endMs: 3000, nextStartMs: 5000, durationMs: 2000 }, 1, 1.15, 'study');
    expect(resumeHoldInMs(fitsResume, { startMs: 0, durationMs: 2000 }, 1000, 1, 1, 'study')).toBeNull();
    expect(resumeHoldInMs(study, { startMs: 0, durationMs: 3300 }, 2000, 1, 2, 'live_delayed')).toBeNull();
    const live = planUnit({ startMs: 0, endMs: 3000, nextStartMs: 3000, durationMs: 5000 }, 1, 1.15, 'live_delayed');
    expect(live.residual).toBe(1);
    expect(live.holdMs).toBe(0);
  });
  it('late classification and epoch guard', () => {
    expect(classifyLate({ startMs: 1000, endMs: 3000 }, 900)).toBe('on_time');
    expect(classifyLate({ startMs: 1000, endMs: 3000 }, 1200)).toBe('late_small');
    expect(classifyLate({ startMs: 1000, endMs: 3000 }, 2000)).toBe('mid_sentence');
    expect(classifyLate({ startMs: 1000, endMs: 3000 }, 3500)).toBe('passed');
    expect(acceptItem({ epoch: 1, revision: 2 }, { epoch: 2, minRevision: 1 })).toBe(false);
    expect(acceptItem({ epoch: 2, revision: 1 }, { epoch: 2, minRevision: 2 })).toBe(false);
    expect(acceptItem({ epoch: 2, revision: 2 }, { epoch: 2, minRevision: 2 })).toBe(true);
  });
});

describe('preload + catch-up (chuẩn bị trước khi phát, Đồng bộ không dừng video)', () => {
  const seg = (s: number, e: number, ready: boolean) => ({ startMs: s, endMs: e, ready });
  it('preparedAheadMs = vùng có tiếng liên tục tính từ vị trí hiện tại, dừng ở câu đầu tiên chưa có tiếng', () => {
    const segs = [seg(0, 3000, true), seg(3500, 7000, true), seg(8000, 12000, false), seg(13000, 16000, true)];
    expect(preparedAheadMs(segs, 1000)).toBe(6000);            // tới hết câu 2; câu 3 chưa có → dừng
    expect(preparedAheadMs(segs, 7500)).toBe(0);               // câu kế tiếp chưa có tiếng
    expect(preparedAheadMs([], 0)).toBe(0);
  });
  it('preloadProgress: mục tiêu co lại khi video/phụ đề còn ít hơn mục tiêu', () => {
    const segs = [seg(0, 4000, true), seg(4500, 9000, true)];
    expect(preloadProgress(segs, 0, 30000, true)).toBe(1);     // nguồn đủ (complete) và hết câu đều có tiếng
    expect(preloadProgress([seg(0, 4000, true), seg(4500, 60000, false)], 0, 30000, true)).toBeCloseTo(4000 / 30000);
    expect(preloadProgress([], 0, 30000, false)).toBe(0);
  });
  it('catchUpResidual: câu trễ đọc nhanh hơn để đuổi kịp nhưng không quá mức tối đa', () => {
    expect(catchUpResidual(3000, 3000, 0, 1, 1.25)).toBe(1);        // đúng giờ, vừa khung
    expect(catchUpResidual(3000, 3000, 600, 1, 1.25)).toBeCloseTo(1.25);  // trễ 0,6 s: cần 3/2,4 = 1,25
    expect(catchUpResidual(6000, 3000, 2000, 1, 1.25)).toBe(1.25);  // quá dài: chặn ở 1,25
    expect(catchUpResidual(2000, 3000, 500, 2, 1.25)).toBe(1);      // 2x: khung 1,5 s thật còn 1,25 s, audio 1 s → vừa
  });
});

describe('nhận tiếng trong lúc chờ xác nhận tua (race làm câm/kẹt chuẩn bị sau khi tua)', () => {
  it('epoch mới hơn đến TRƯỚC khi xác nhận tua → giữ lại; epoch cũ/bằng khi đang chờ → bỏ', () => {
    expect(acceptItem({ epoch: 3, revision: 1 }, { epoch: 2, minRevision: 1, epochPending: true })).toBe(true);
    expect(acceptItem({ epoch: 2, revision: 1 }, { epoch: 2, minRevision: 1, epochPending: true })).toBe(false);
    expect(acceptItem({ epoch: 1, revision: 1 }, { epoch: 2, minRevision: 1, epochPending: true })).toBe(false);
    expect(acceptItem({ epoch: 3, revision: 1 }, { epoch: 2, minRevision: 1, epochPending: false })).toBe(false);
    expect(acceptItem({ epoch: 2, revision: 1 }, { epoch: 2, minRevision: 1, epochPending: false })).toBe(true);
  });
});
