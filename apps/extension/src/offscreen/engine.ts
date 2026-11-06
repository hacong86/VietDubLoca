/**
 * Audio engine trong offscreen (ADR-004, docs/06). Sở hữu AudioContext; lập lịch audio theo video clock.
 * - Mỗi item giữ (session_id, timeline_epoch, segment_id, revision); từ chối item cũ lúc nhận VÀ lúc phát.
 * - Horizon lập lịch 2 s để hủy nhanh; stop tất cả node ngay khi pause/seek/tắt (không chờ broker).
 * - Time-stretch WSOLA giữ cao độ theo playbackRate. Đồng bộ: KHÔNG dừng video giữa chừng — câu dài đọc nhanh ≤ max,
 *   câu sau xếp hàng (không bao giờ 2 giọng cùng lúc), câu trễ đọc nhanh để đuổi kịp. Học kỹ: dừng hình để đọc hết câu.
 * - Chuẩn bị trước khi phát (preload): tạm dừng video tới khi có sẵn N giây tiếng Việt, có tiến độ %.
 */
import { acceptItem, audioStartFor, catchUpResidual, classifyLate, mediaNow, planUnit, preloadProgress, resumeHoldInMs, s16ToFloat, timeStretch, type Anchor } from '../../../../packages/audio/src';
import type { Mode, PauseReason } from '../shared/messages';

export interface ItemMeta {
  segment_id: string;
  revision: number;
  epoch: number;
  start_ms: number;
  end_ms: number;
  next_start_ms: number | null;
  duration_ms: number;
  preview?: boolean;
  ready_at_media?: number;                          // vị trí video khi tiếng về đủ (để biết câu tới muộn)
}

interface Item extends ItemMeta {
  chunks: Int16Array[];
  complete: boolean;
  native: Float32Array | null;
  stretched: Map<string, AudioBuffer>;
}

interface Playing {
  key: string;
  source: AudioBufferSourceNode;
  when: number;
  bufDur: number;
  tempo: number;
  offset: number;
  holdAt: number | null;
  endAt: number;
}

export interface EngineHooks {
  pauseVideo(reason: PauseReason): void;
  playVideo(reason: PauseReason): void;
  status(): void;
  stopped(epoch: number, reason: string, latencyMs: number): void;
  replayPrompt(segmentId: string): void;
  progress(pct: number | null): void;               // tiến độ chuẩn bị (null = ẩn)
  notice(text: string): void;
}

export interface SegmentInfo {
  segment_id: string;
  revision: number;
  start_ms: number;
  end_ms: number;
  status: string;
}

export interface EngineSettings {
  vietnamese_gain: number;
  original_gain: number;
  auto_hold_vod: boolean;
  residual_stretch_max: number;
  seek_mid_sentence: 'replay_prompt' | 'skip_current';
  preload_enabled: boolean;
  preload_target_ms: number;
}

const HORIZON_S = 2.0;
const CATCHUP_LAG_MS = 3000;         // Đồng bộ: tiếng Việt trễ quá mức này → dừng video, đọc bắt kịp rồi TỰ phát tiếp (không bỏ câu)
const HOLD_MAX_MS = 20000;           // mọi lần giữ hình đều có hạn — không để video đứng mãi
const SEEK_PRELOAD_MS = 8000;        // sau khi tua chỉ chuẩn bị ngắn
const PRELOAD_TIMEOUT_MS = 60000;

export class AudioEngine {
  readonly ctx: AudioContext;
  readonly viGain: GainNode;
  readonly srcGain: GainNode;
  mode: Mode = 'vod_sync';
  epoch = 0;
  sessionId = '';
  epochPending = false;
  settings: EngineSettings = { vietnamese_gain: 1, original_gain: 0.15, auto_hold_vod: true, residual_stretch_max: 1.25, seek_mid_sentence: 'replay_prompt',
    preload_enabled: true, preload_target_ms: 30000 };
  sourceComplete = false;                            // phụ đề phủ tới cuối video (coverage full)
  anchor: Anchor = { mediaMs: 0, audioTime: 0, rate: 1, playing: false, epoch: 0 };
  adState: 'content' | 'ad' | 'unknown' = 'content';
  segments = new Map<string, SegmentInfo>();
  private items = new Map<string, Item>();         // key = segment_id (revision mới nhất)
  private minRevision = new Map<string, number>();
  private playing: Playing[] = [];
  private done = new Set<string>();                // `${seg}@${rev}@${epoch}` đã phát/bỏ qua
  private resume: { key: string; nativeOffsetS: number } | null = null;
  hold: { reason: PauseReason; seg: string | null; since: number } | null = null;
  preload: { targetMs: number; since: number; pausedByUs: boolean; lastPct: number; timeoutMs: number } | null = null;
  userPaused = false;
  private liveTail = 0;
  private epochStartMedia: number | null = null;    // vị trí video khi epoch bắt đầu (điểm tua/bật)
  private chained = new Set<string>();             // câu phải chờ câu trước đọc xong (không bao giờ 2 giọng cùng lúc)
  stats = { scheduled: 0, underruns: 0, holds: 0, stops: 0, overlap_prevented: 0, last_stop_latency_ms: null as number | null, drift_ms: [] as number[] };

  constructor(private hooks: EngineHooks) {
    this.ctx = new AudioContext({ latencyHint: 'interactive' });
    this.viGain = this.ctx.createGain();
    this.srcGain = this.ctx.createGain();
    this.viGain.connect(this.ctx.destination);
    this.srcGain.connect(this.ctx.destination);
    setInterval(() => this.tick(), 50);
  }

  applySettings(s: Partial<EngineSettings>): void {
    this.settings = { ...this.settings, ...s };
    this.viGain.gain.setTargetAtTime(this.settings.vietnamese_gain, this.ctx.currentTime, 0.02);
    this.srcGain.gain.setTargetAtTime(this.settings.original_gain, this.ctx.currentTime, 0.02);
  }

  // ---------------------------------------------------------------- nhận audio
  begin(meta: ItemMeta): void {
    // Đang chờ xác nhận tua mà broker đã gửi tiếng epoch MỚI → giữ lại (bỏ đi là câu câm / kẹt chuẩn bị)
    if (!meta.preview && !acceptItem({ epoch: meta.epoch, revision: meta.revision },
      { epoch: this.epoch, minRevision: this.minRevision.get(meta.segment_id) ?? 0, epochPending: this.epochPending })) return;
    const old = this.items.get(meta.segment_id);
    if (old && old.revision > meta.revision && old.epoch === meta.epoch) return;
    this.items.set(meta.segment_id, { ...meta, chunks: [], complete: false, native: null, stretched: new Map() });
  }

  chunk(h: { segment_id: string; revision: number; timeline_epoch: number; session_id: string }, pcm: Int16Array): void {
    const it = this.items.get(h.segment_id);
    const preview = h.session_id === 'preview';
    if (!it || it.revision !== h.revision || (!preview && (h.timeline_epoch !== it.epoch || h.session_id !== this.sessionId))) return;
    it.chunks.push(pcm);
  }

  end(segmentId: string, revision: number, complete: boolean): void {
    const it = this.items.get(segmentId);
    if (!it || it.revision !== revision || !complete) return;
    const total = it.chunks.reduce((n, c) => n + c.length, 0);
    const all = new Int16Array(total);
    let o = 0;
    for (const c of it.chunks) {
      all.set(c, o);
      o += c.length;
    }
    it.chunks = [];
    it.native = s16ToFloat(all);
    it.duration_ms = Math.round((total / 48000) * 1000);
    it.complete = true;
    it.ready_at_media = mediaNow(this.anchor, this.ctx.currentTime);
    if (it.preview) this.playPreview(it);
    if (this.hold?.reason === 'AUTO_BUFFER' && this.hold.seg === segmentId) this.releaseHold();
    this.tick();
  }

  hasAudio(segmentId: string): boolean {
    const it = this.items.get(segmentId);
    return !!it && it.complete && it.epoch === this.epoch;
  }

  // ---------------------------------------------------------------- điều khiển
  /** Dừng mọi node ngay (seek/tắt/quảng cáo/pause người dùng). Không chờ broker. */
  stopAll(reason: string, sentEpochMs?: number, keepResume = false): void {
    const t0 = performance.timeOrigin + performance.now();
    if (keepResume) {
      const cur = this.playing.find((p) => p.when <= this.ctx.currentTime && this.ctx.currentTime < p.endAt);
      if (cur) this.resume = { key: cur.key, nativeOffsetS: (this.ctx.currentTime - cur.when + cur.offset) * cur.tempo };
    } else {
      this.resume = null;
    }
    for (const p of this.playing) {
      try {
        p.source.onended = null;
        p.source.stop();
        p.source.disconnect();
      } catch {
        /* đã dừng */
      }
      if (!keepResume) this.done.add(p.key + '@' + this.epoch);
    }
    if (keepResume) for (const p of this.playing) this.done.delete(p.key + '@' + this.epoch);
    this.playing = [];
    this.stats.stops++;
    const lat = sentEpochMs ? Math.max(0, t0 - sentEpochMs) : null;
    this.stats.last_stop_latency_ms = lat !== null ? Math.round(lat * 10) / 10 : null;
    this.hooks.stopped(this.epoch, reason, lat ?? 0);
  }

  /** Epoch chỉ TĂNG (Codex #8): phản hồi/sự kiện cũ không được kéo lùi hay mở khóa pending. */
  setEpoch(epoch: number): void {
    if (epoch > this.epoch) {
      this.stopAll('epoch_changed');
      for (const [k, it] of this.items) if (it.epoch < epoch && !it.preview) this.items.delete(k);
      this.epoch = epoch;
      this.epochPending = false;
      this.anchor = { ...this.anchor, epoch };
      this.done.clear();
      this.chained.clear();
      this.epochStartMedia = null;
      this.liveTail = 0;
    }
  }

  invalidateRevision(segmentId: string, minRevision: number): void {
    this.minRevision.set(segmentId, minRevision);
    const it = this.items.get(segmentId);
    if (it && it.revision < minRevision) {
      this.items.delete(segmentId);
      const p = this.playing.find((x) => x.key.startsWith(segmentId + '@'));
      if (p) {
        try {
          p.source.stop();
        } catch {
          /* bỏ qua */
        }
        this.playing = this.playing.filter((x) => x !== p);
      }
    }
  }

  onClock(c: { media_ms: number; playback_rate: number; paused: boolean; seeking: boolean; stalled: boolean; ad_state: 'content' | 'ad' | 'unknown'; sent_epoch_ms: number }): void {
    const transit = Math.max(0, Math.min(500, performance.timeOrigin + performance.now() - c.sent_epoch_ms)) / 1000;
    const playing = !c.paused && !c.seeking && !c.stalled && c.ad_state === 'content';
    const media = c.media_ms + (playing ? transit * 1000 * c.playback_rate : 0);
    const prev = this.anchor;
    const rateChanged = Math.abs(prev.rate - c.playback_rate) > 1e-3;
    this.adState = c.ad_state;
    if (prev.playing) {
      const predicted = mediaNow(prev, this.ctx.currentTime);
      const drift = media - predicted;
      if (playing && !rateChanged && Math.abs(drift) < 2000) {
        this.stats.drift_ms.push(Math.round(drift));
        if (this.stats.drift_ms.length > 200) this.stats.drift_ms.shift();
      }
    }
    this.anchor = { mediaMs: media, audioTime: this.ctx.currentTime, rate: c.playback_rate, playing, epoch: this.epoch };
    if (!playing && prev.playing) {
      // App đang giữ hình để đọc hết câu → giữ audio; còn lại (người dùng/quảng cáo/buffer video) → dừng, nhớ offset.
      if (!(this.hold && (this.hold.reason === 'AUTO_SENTENCE' || this.hold.reason === 'CATCHUP'))) this.stopAll(c.ad_state !== 'content' ? 'ad' : 'paused', c.sent_epoch_ms, c.ad_state === 'content');
    } else if (playing && rateChanged && this.playing.length) {
      this.stopAll('rate_changed', c.sent_epoch_ms, true);       // re-stretch theo rate mới, tránh double-speed
    }
    if (playing && (this.hold?.reason === 'AUTO_SENTENCE' || this.hold?.reason === 'CATCHUP')) this.hold = null;   // người dùng bấm play trong lúc giữ: nhường
    this.tick();
  }

  // ---------------------------------------------------------------- lập lịch
  private stretchedBuffer(it: Item, tempo: number): AudioBuffer {
    const k = tempo.toFixed(3);
    let b = it.stretched.get(k);
    if (!b) {
      const data = Math.abs(tempo - 1) < 1e-3 ? it.native! : timeStretch(it.native!, tempo, { sampleRate: 48000 });
      b = this.ctx.createBuffer(1, Math.max(1, data.length), 48000);
      b.copyToChannel(data as Float32Array<ArrayBuffer>, 0);
      it.stretched.set(k, b);
      if (it.stretched.size > 3) it.stretched.delete(it.stretched.keys().next().value as string);
    }
    return b;
  }

  private schedule(it: Item, when: number, tempo: number, nativeOffsetS: number, holdAtWall: number | null): void {
    const buf = this.stretchedBuffer(it, tempo);
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.viGain);
    const offset = Math.min(buf.duration, nativeOffsetS / tempo);
    const startAt = Math.max(this.ctx.currentTime + 0.005, when);
    src.start(startAt, offset);
    const key = `${it.segment_id}@${it.revision}`;
    const p: Playing = { key, source: src, when: startAt, bufDur: buf.duration, tempo, offset, holdAt: holdAtWall, endAt: startAt + buf.duration - offset };
    src.onended = () => {
      this.playing = this.playing.filter((x) => x !== p);
      if (this.hold?.reason === 'AUTO_SENTENCE' && this.hold.seg === it.segment_id) this.releaseHold();
      this.hooks.status();
    };
    this.playing.push(p);
    this.done.add(key + '@' + this.epoch);
    this.stats.scheduled++;
  }

  private releaseHold(): void {
    const h = this.hold;
    this.hold = null;
    if (h && !this.userPaused) this.hooks.playVideo(h.reason);
    this.hooks.status();
  }

  private requestHold(reason: PauseReason, seg: string | null): void {
    if (this.hold || this.userPaused) return;
    this.hold = { reason, seg, since: performance.now() };
    this.stats.holds++;
    this.hooks.pauseVideo(reason);
    this.hooks.status();
  }

  private playPreview(it: Item): void {
    const src = this.ctx.createBufferSource();
    src.buffer = this.stretchedBuffer(it, 1);
    src.connect(this.viGain);
    src.start();
    src.onended = () => this.items.delete(it.segment_id);
  }

  // ---------------------------------------------------------------- chuẩn bị trước khi phát
  /** Bắt đầu chuẩn bị: nếu video đang chạy thì tạm dừng tới khi có đủ tiếng Việt phía trước (hoặc người dùng bỏ qua). */
  beginPreload(kind: 'start' | 'seek'): void {
    if (!this.settings.preload_enabled || this.mode === 'live_delayed') return;
    const targetMs = kind === 'start' ? this.settings.preload_target_ms : Math.min(SEEK_PRELOAD_MS, this.settings.preload_target_ms);
    this.preload = { targetMs, since: performance.now(), pausedByUs: false, lastPct: -1, timeoutMs: kind === 'start' ? PRELOAD_TIMEOUT_MS : 20000 };
    this.hooks.progress(0);
  }

  /** Kết thúc chuẩn bị (đủ tiếng / hết giờ / người dùng bấm "Xem luôn" hoặc tự bấm play). */
  endPreload(playVideo: boolean): void {
    const p = this.preload;
    if (!p) return;
    this.preload = null;
    this.hooks.progress(null);
    if (playVideo && p.pausedByUs && !this.userPaused) this.hooks.playVideo('PRELOAD');
    this.hooks.status();
  }

  preloadPct(): number {
    const now = mediaNow(this.anchor, this.ctx.currentTime);
    const spans = Array.from(this.segments.values()).map((s) => {
      const it = this.items.get(s.segment_id);
      const ready = s.status === 'blocked' || s.status === 'skipped_by_user' || s.status === 'silent' || (!!it && it.complete && it.epoch === this.epoch);
      return { startMs: s.start_ms, endMs: s.end_ms, ready };
    });
    return preloadProgress(spans, now, this.preload?.targetMs ?? 0, this.sourceComplete);
  }

  private tickPreload(): void {
    const p = this.preload!;
    if (this.anchor.playing && !p.pausedByUs && !this.userPaused) {
      p.pausedByUs = true;
      this.hooks.pauseVideo('PRELOAD');
    }
    const pct = this.epochPending ? 0 : this.preloadPct();
    if (Math.abs(pct - p.lastPct) >= 0.01) {
      p.lastPct = pct;
      this.hooks.progress(pct);
    }
    if (pct >= 1) this.endPreload(true);
    else if (performance.now() - p.since > p.timeoutMs) {
      this.hooks.notice('Máy đang bận — phát luôn, tiếng Việt có thể đến chậm vài câu đầu');
      this.endPreload(true);
    }
  }

  /**
   * Bắt kịp xong khi: phần tiếng Việt còn lại ≤ thời gian video cần để tới câu kế tiếp đang chờ.
   * Phát lại video SỚM nhất có thể (đuôi câu trước đọc nốt trong lúc video chạy tới câu sau) → dừng hình ngắn nhất.
   */
  private catchupDone(acNow: number): boolean {
    const busyLeftMs = Math.max(0, ...this.playing.map((p) => p.endAt - acNow)) * 1000;
    if (busyLeftMs <= 50) return true;
    const media = this.anchor.mediaMs;                          // video đang dừng
    let nextStart = Infinity;
    for (const k of this.chained) {
      const s = this.segments.get(k.split('@')[0] ?? '');
      if (s && s.start_ms >= media) nextStart = Math.min(nextStart, s.start_ms);
    }
    if (nextStart === Infinity) return false;                   // câu chờ đã trễ sẵn → đợi đọc xong phần đang phát
    return busyLeftMs <= (nextStart - media) / Math.max(0.25, this.anchor.rate) + 200;
  }

  tick(): void {
    if (this.ctx.state === 'suspended') void this.ctx.resume();
    if (this.preload) {
      this.tickPreload();
      if (this.preload) return;                       // đang chuẩn bị: chưa phát gì
    }
    if (this.hold && performance.now() - this.hold.since > HOLD_MAX_MS) {
      this.hooks.notice('Chờ quá lâu — tiếp tục phát video');
      this.releaseHold();
    }
    if (this.epochPending || this.adState !== 'content') return;
    const acNow = this.ctx.currentTime;
    // giữ hình ở cuối câu khi audio còn dài hơn khung
    for (const p of this.playing) {
      if (p.holdAt !== null && acNow >= p.holdAt && acNow < p.endAt && this.anchor.playing) {
        p.holdAt = null;
        this.requestHold('AUTO_SENTENCE', p.key.split('@')[0] ?? null);
      }
    }
    if (this.hold?.reason === 'CATCHUP' && this.catchupDone(acNow)) this.releaseHold();   // đã bắt kịp → TỰ phát, không cần bấm
    if (!this.anchor.playing) return;                     // pause/seek/stall: không lập lịch (cả live)
    if (this.mode === 'live_delayed') return this.tickLive(acNow);
    const now = mediaNow(this.anchor, acNow);
    if (this.epochStartMedia === null) this.epochStartMedia = now;
    // Giọng Việt đang phát (kể cả đã hẹn giờ) kéo dài tới đâu: câu sau không được bắt đầu trước mốc này.
    const busyUntil = () => this.playing.reduce((m, p) => Math.max(m, p.endAt), 0);
    const ordered = Array.from(this.segments.values()).sort((a, b) => a.start_ms - b.start_ms);
    const isChained = (segId: string) => { for (const k of this.chained) if (k.startsWith(segId + '@')) return true; return false; };
    for (const seg of ordered) {
      if (seg.status === 'silent') continue;
      if (seg.end_ms < now - 1000 && !isChained(seg.segment_id)) continue;   // câu đang xếp hàng thì không bỏ dù đã trễ
      if (seg.start_ms > now + HORIZON_S * 1000 * this.anchor.rate + 400) break;
      const it = this.items.get(seg.segment_id);
      const key = it ? `${it.segment_id}@${it.revision}@${this.epoch}` : '';
      if (it && this.done.has(key)) continue;
      const cls = classifyLate({ startMs: seg.start_ms, endMs: seg.end_ms }, now);
      if (!it || !it.complete || it.epoch !== this.epoch) {
        // chưa có audio: VOD auto-hold trước khi câu bắt đầu (không bỏ câu âm thầm)
        const ahead = seg.start_ms - now;
        if (ahead <= 300 && ahead > -250 && this.mode === 'study') {   // Đồng bộ: không dừng video (user chốt 2026-09-24)
          if (seg.status === 'blocked') this.requestHold('BLOCKED', seg.segment_id);
          else if (seg.status !== 'skipped_by_user') this.requestHold('AUTO_BUFFER', seg.segment_id);
          this.stats.underruns++;
        }
        continue;
      }
      if (this.resume && this.resume.key === `${it.segment_id}@${it.revision}`) {
        const plan = planUnit({ startMs: it.start_ms, endMs: it.end_ms, nextStartMs: it.next_start_ms, durationMs: it.duration_ms }, this.anchor.rate, this.settings.residual_stretch_max, this.mode);
        const off = this.resume.nativeOffsetS;
        this.resume = null;
        const holdIn = resumeHoldInMs(plan, { startMs: it.start_ms, durationMs: it.duration_ms }, now, this.anchor.rate, off, this.mode);
        this.schedule(it, acNow, plan.tempo, off, holdIn === null ? null : acNow + holdIn / 1000);
        continue;
      }
      // Câu trễ VÌ câu trước đọc dài hoặc tiếng về muộn (không phải do tua) → vẫn đọc, đọc nhanh để đuổi kịp.
      // chỉ câu bắt đầu SAU điểm tua/bật mới tính là 'tới muộn'; câu đang dở tại điểm tua theo seek_mid_sentence
      const arrivedLate = this.mode !== 'study' && it.ready_at_media !== undefined && it.ready_at_media > seg.start_ms - 50
        && seg.start_ms >= (this.epochStartMedia ?? 0) - 50;
      const chainedLate = this.chained.has(key) || (arrivedLate && now > seg.start_ms + 250);
      if (cls === 'passed' && !chainedLate) {
        this.done.add(key);
        continue;
      }
      if (cls === 'mid_sentence' && !chainedLate) {
        this.done.add(key);
        if (this.settings.seek_mid_sentence === 'replay_prompt') this.hooks.replayPrompt(seg.segment_id);
        continue;
      }
      const plan = planUnit({ startMs: it.start_ms, endMs: it.end_ms, nextStartMs: it.next_start_ms, durationMs: it.duration_ms }, this.anchor.rate, this.settings.residual_stretch_max, this.mode);
      const when = audioStartFor(it.start_ms, this.anchor);
      if (busyUntil() > when + 0.02) {
        // Câu trước chưa đọc xong: xếp hàng, phát ngay khi câu trước kết thúc (tick sau). Không phát chồng.
        if (!chainedLate) {
          this.chained.add(key);
          this.stats.overlap_prevented++;
        }
        if (this.mode !== 'study' && (busyUntil() - when) * 1000 > CATCHUP_LAG_MS) this.requestHold('CATCHUP', seg.segment_id);
        continue;
      }
      if (chainedLate) {
        this.chained.delete(key);
        const startAt = Math.max(acNow, when);
        if (this.mode === 'study') {
          const holdIn = resumeHoldInMs(plan, { startMs: it.start_ms, durationMs: it.duration_ms }, Math.max(now, it.start_ms), this.anchor.rate, 0, this.mode);
          this.schedule(it, startAt, plan.tempo, 0, holdIn === null ? null : startAt + holdIn / 1000);
        } else {
          const lateMs = Math.max(0, now - it.start_ms);
          const residual = catchUpResidual(it.duration_ms, plan.budgetMs * this.anchor.rate, lateMs, this.anchor.rate, this.settings.residual_stretch_max);
          this.schedule(it, startAt, this.anchor.rate * residual, 0, null);
          if (lateMs > CATCHUP_LAG_MS) this.requestHold('CATCHUP', seg.segment_id);   // trễ quá: dừng video tới khi đọc xong câu này
        }
      } else {
        const needHold = this.mode === 'study' && plan.playedMs > plan.budgetMs;   // Đồng bộ: không giữ hình
        this.schedule(it, when, plan.tempo, 0, needHold ? when + plan.budgetMs / 1000 : null);
      }
    }
  }

  private tickLive(acNow: number): void {
    // Live: phát tuần tự theo thứ tự nguồn, ngay khi có (đi sau nguồn — có độ trễ, không đồng bộ khuôn miệng).
    const ordered = Array.from(this.items.values()).filter((i) => i.complete && i.epoch === this.epoch && !i.preview)
      .sort((a, b) => a.start_ms - b.start_ms);
    for (const it of ordered) {
      const key = `${it.segment_id}@${it.revision}@${this.epoch}`;
      if (this.done.has(key)) continue;
      const when = Math.max(acNow + 0.02, this.liveTail);
      if (when - acNow > HORIZON_S) break;
      this.schedule(it, when, 1, 0, null);
      this.liveTail = when + it.duration_ms / 1000;
    }
  }

  queuedMs(): number {
    const acNow = this.ctx.currentTime;
    let ms = 0;
    for (const p of this.playing) ms += Math.max(0, p.endAt - acNow) * 1000;
    for (const it of this.items.values()) if (it.complete && !this.done.has(`${it.segment_id}@${it.revision}@${this.epoch}`)) ms += it.duration_ms;
    return Math.round(ms);
  }

  isSpeaking(): boolean {
    const t = this.ctx.currentTime;
    return this.playing.some((p) => p.when <= t && t < p.endAt);
  }

  reset(): void {
    this.stopAll('reset');
    this.items.clear();
    this.segments.clear();
    this.done.clear();
    this.chained.clear();
    this.minRevision.clear();
    this.hold = null;
    this.preload = null;
    this.epochStartMedia = null;
    this.userPaused = false;
    this.resume = null;
  }
}
