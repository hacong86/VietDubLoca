/**
 * Toán lập lịch audio theo video clock (docs/06 §2–§4). Hàm thuần để test được.
 *
 * audio_start = anchor_audio + ((unit_start_ms - anchor_media_ms) / 1000) / playback_rate
 * Ngân sách B = (end + mượn lặng ≤ 500 ms, không lấn câu kế) / rate; audio native D stretch theo rate;
 * phần dư bù tối đa ×1,15 (giữ cao độ); vẫn dài hơn → giữ hình ở cuối câu ("Đang đọc hết câu").
 */

export interface Anchor {
  mediaMs: number;     // currentTime video lúc lấy mẫu
  audioTime: number;   // AudioContext.currentTime tương ứng (giây)
  rate: number;        // playbackRate
  playing: boolean;
  epoch: number;
}

export interface UnitTiming {
  startMs: number;
  endMs: number;
  nextStartMs: number | null;
  durationMs: number;  // độ dài audio native (1x)
}

export interface PlayPlan {
  tempo: number;          // hệ số time-stretch áp lên audio native (= rate × residual)
  residual: number;       // 1.0–residualMax
  playedMs: number;       // độ dài thực phát (wall)
  budgetMs: number;       // khung cho phép (wall)
  holdMs: number;         // cần giữ hình ở cuối câu bao lâu (wall), 0 nếu không
}

export const BORROW_MAX_MS = 500;

export function mediaNow(a: Anchor, acNow: number): number {
  if (!a.playing) return a.mediaMs;
  return a.mediaMs + (acNow - a.audioTime) * 1000 * a.rate;
}

export function audioStartFor(unitStartMs: number, a: Anchor): number {
  return a.audioTime + (unitStartMs - a.mediaMs) / 1000 / a.rate;
}

export function planUnit(u: UnitTiming, rate: number, residualMax = 1.15, mode: 'vod_sync' | 'study' | 'live_delayed' = 'vod_sync'): PlayPlan {
  const r = Math.max(0.25, Math.min(4, rate));
  const nextLimit = u.nextStartMs ?? Number.POSITIVE_INFINITY;
  const borrowEnd = Math.min(u.endMs + BORROW_MAX_MS, nextLimit);
  const spanMs = Math.max(u.endMs, borrowEnd) - u.startMs;
  const budgetMs = Math.max(1, spanMs) / r;
  const atRate = u.durationMs / r;
  let residual = 1;
  // Học kỹ (FR-029): đọc đúng tốc độ, dừng hình ở cuối câu thay vì nói nhanh hơn.
  if (mode === 'vod_sync' && atRate > budgetMs) residual = Math.min(residualMax, atRate / budgetMs);
  const tempo = r * residual;
  const playedMs = u.durationMs / tempo;
  const holdMs = mode === 'live_delayed' ? 0 : Math.max(0, playedMs - budgetMs);
  return { tempo, residual, playedMs, budgetMs, holdMs };
}

/**
 * Phát tiếp câu dở (sau pause/mất kết nối): còn bao nhiêu ms (đồng hồ thật) trước khi phải giữ hình để đọc hết.
 * null = không cần giữ. Không có hàm này thì câu phát tiếp mất mốc giữ hình (lỗi Học kỹ E2E T11).
 */
export function resumeHoldInMs(plan: PlayPlan, u: { startMs: number; durationMs: number }, nowMedia: number, rate: number,
  nativeOffsetS: number, mode: 'vod_sync' | 'study' | 'live_delayed'): number | null {
  if (mode === 'live_delayed') return null;
  const r = Math.max(0.25, Math.min(4, rate));
  const budgetLeft = plan.budgetMs - Math.max(0, nowMedia - u.startMs) / r;
  const audioLeft = Math.max(0, u.durationMs - nativeOffsetS * 1000) / plan.tempo;
  if (audioLeft <= Math.max(0, budgetLeft) + 1) return null;
  return Math.max(0, budgetLeft);
}

export interface ReadySpan { startMs: number; endMs: number; ready: boolean }

/** Thời lượng (ms video) đã có tiếng Việt LIÊN TỤC tính từ vị trí hiện tại; dừng ở câu đầu tiên chưa có tiếng. */
export function preparedAheadMs(segs: ReadySpan[], nowMs: number): number {
  let cover = nowMs;
  for (const s of [...segs].sort((a, b) => a.startMs - b.startMs)) {
    if (s.endMs <= nowMs) continue;
    if (!s.ready) break;
    cover = Math.max(cover, s.endMs);
  }
  return Math.max(0, cover - nowMs);
}

/**
 * Tiến độ "Đang chuẩn bị thuyết minh" (0..1). Mục tiêu co lại khi phần phụ đề còn lại ngắn hơn mục tiêu:
 * nguồn đủ tới cuối (complete) và mọi câu còn lại đã có tiếng → 1.
 */
export function preloadProgress(segs: ReadySpan[], nowMs: number, targetMs: number, complete: boolean): number {
  const ahead = segs.filter((s) => s.endMs > nowMs);
  if (!ahead.length) return complete ? 1 : 0;
  const lastEnd = Math.max(...ahead.map((s) => s.endMs));
  const target = complete ? Math.min(targetMs, lastEnd - nowMs) : targetMs;
  if (target <= 0) return 1;
  return Math.min(1, preparedAheadMs(segs, nowMs) / target);
}

/**
 * Hệ số đọc nhanh cho câu bị trễ (do câu trước dài hoặc tiếng tới muộn) ở chế độ Đồng bộ — KHÔNG dừng video:
 * cần đọc hết `durationMs` trong phần khung còn lại (budget − trễ); chặn trong [1, max].
 */
export function catchUpResidual(durationMs: number, budgetMs: number, lateMs: number, _rate: number, max: number): number {
  const left = budgetMs - Math.max(0, lateMs);
  if (left <= 0) return max;
  return Math.min(max, Math.max(1, durationMs / left));
}

/** Giây trước khi câu bắt đầu mà chưa có audio → cần giữ hình chờ (VOD auto-hold, không bỏ câu). */
export function needsBufferHold(unitStartMs: number, now: number, leadMs = 300): boolean {
  return unitStartMs - now <= leadMs;
}

/** Seek vào giữa câu: không phát nửa câu tiếng Việt theo phần trăm ký tự — trả 'replay_prompt'. */
export function classifyLate(u: { startMs: number; endMs: number }, now: number, toleranceMs = 250): 'on_time' | 'late_small' | 'mid_sentence' | 'passed' {
  if (now <= u.startMs) return 'on_time';
  if (now - u.startMs <= toleranceMs) return 'late_small';
  if (now < u.endMs) return 'mid_sentence';
  return 'passed';
}

/** Chuyển epoch: item cũ bị từ chối cả lúc nhận lẫn lúc chuẩn bị phát. */
/**
 * Nhận item âm thanh? Bình thường chỉ đúng epoch hiện tại. Trong lúc chờ broker xác nhận tua (epochPending),
 * broker có thể đã gửi tiếng của epoch MỚI trước khi client biết → giữ lại (nếu bỏ, broker coi là đã giao và
 * không gửi lại → câu câm / kẹt chuẩn bị). Epoch cũ hoặc bằng khi đang chờ → bỏ.
 */
export function acceptItem(item: { epoch: number; revision: number }, current: { epoch: number; minRevision: number; epochPending?: boolean }): boolean {
  if (item.revision < current.minRevision) return false;
  return current.epochPending ? item.epoch > current.epoch : item.epoch === current.epoch;
}
