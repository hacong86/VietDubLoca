/**
 * Tin nhắn runtime nội bộ extension. Mọi tin có ns='vietdub'. Nơi nhận LUÔN kiểm sender (tab id/extension page)
 * và chỉ chấp nhận type trong allowlist của mình. Content script không bao giờ nhận token/URL broker.
 */

export const NS = 'vietdub' as const;

export type Mode = 'vod_sync' | 'live_delayed' | 'study';
export type PauseReason = 'USER' | 'AUTO_BUFFER' | 'AUTO_SENTENCE' | 'AD' | 'STALL' | 'BLOCKED' | 'PRELOAD' | 'CATCHUP';

export interface ClockSnap {
  video_id: string;
  media_ms: number;
  playback_rate: number;
  paused: boolean;
  seeking: boolean;
  stalled: boolean;
  ad_state: 'content' | 'ad' | 'unknown';
  visibility: 'visible' | 'hidden';
  sent_epoch_ms: number; // performance.timeOrigin + performance.now() (so sánh chéo context)
  duration_ms?: number;
  volume?: number;
  muted?: boolean;
}

export interface CueOut {
  cue_id: string;
  start_ms: number;
  end_ms: number;
  text: string;
  committed: boolean;
}

export interface CaptionPayload {
  video_id: string;
  source_id: string;
  source_kind: 'manual' | 'auto' | 'import';
  language: 'en' | 'en-US' | 'en-GB';
  coverage: 'full' | 'partial' | 'current_only';
  available_until_ms: number;
  cues: CueOut[];
  offset_ms?: number;
  label: string;
  tried: string[];
}

export interface OverlaySeg {
  segment_id: string;
  revision: number;
  start_ms: number;
  end_ms: number;
  source_text: string;
  target_display: string;
  status: string;
}

export interface OverlayPrefs {
  subtitle_mode: 'off' | 'vi' | 'bilingual';
  subtitle_size: number;
  subtitle_position: 'bottom' | 'top';
}

/** content → extension (SW/offscreen/panel nghe) */
export type FromContent =
  | { ns: typeof NS; type: 'content.hello'; video_id: string | null; title: string; is_live: boolean; is_shorts: boolean }
  | { ns: typeof NS; type: 'content.nav'; video_id: string | null; title: string; is_live: boolean; is_shorts: boolean }
  | { ns: typeof NS; type: 'content.clock'; clock: ClockSnap }
  | { ns: typeof NS; type: 'content.seek'; video_id: string; media_ms: number }
  | { ns: typeof NS; type: 'content.user_pause'; paused: boolean }
  | { ns: typeof NS; type: 'content.captions'; payload: CaptionPayload }
  | { ns: typeof NS; type: 'content.source_failed'; video_id: string; reason: string; tried: string[] }
  | { ns: typeof NS; type: 'content.toggle' }
  | { ns: typeof NS; type: 'content.open_panel' }
  | { ns: typeof NS; type: 'content.ended'; video_id: string }
  | { ns: typeof NS; type: 'content.autoplay_blocked' }
  | { ns: typeof NS; type: 'content.preload_skip' };

/** extension → content (qua chrome.tabs.sendMessage; chỉ SW gửi) */
export type ToContent =
  | { ns: typeof NS; type: 'session.started'; mode: Mode; prefs: OverlayPrefs; capture: boolean; original_gain: number }
  | { ns: typeof NS; type: 'session.stopped'; reason: string }
  | { ns: typeof NS; type: 'overlay.segments'; segments: OverlaySeg[] }
  | { ns: typeof NS; type: 'overlay.draft'; text: string }
  | { ns: typeof NS; type: 'overlay.prefs'; prefs: OverlayPrefs }
  | { ns: typeof NS; type: 'overlay.status'; text: string; level: 'info' | 'warn' | 'error' }
  | { ns: typeof NS; type: 'overlay.progress'; pct: number | null }
  | { ns: typeof NS; type: 'video.pause'; reason: PauseReason }
  | { ns: typeof NS; type: 'video.play'; reason: PauseReason }
  | { ns: typeof NS; type: 'video.seek'; media_ms: number }
  | { ns: typeof NS; type: 'volume.apply'; original_gain: number }
  | { ns: typeof NS; type: 'volume.restore' }
  | { ns: typeof NS; type: 'captions.fetch'; force?: boolean }
  | { ns: typeof NS; type: 'ping' };

export const TO_CONTENT_TYPES = new Set<ToContent['type']>(['session.started', 'session.stopped', 'overlay.segments', 'overlay.draft',
  'overlay.prefs', 'overlay.status', 'overlay.progress', 'video.pause', 'video.play', 'video.seek', 'volume.apply', 'volume.restore', 'captions.fetch', 'ping']);

export interface PanelStatus {
  connection: 'unpaired' | 'connecting' | 'connected' | 'reconnecting' | 'error';
  error_code?: string | null;
  session?: import('../../../../packages/contracts/src').SessionSnapshot | null;
  hold?: { reason: PauseReason; text: string } | null;
  preload?: { pct: number } | null;                 // đang chuẩn bị thuyết minh (0..1)
  replay_prompt?: { segment_id: string } | null;
  queue_ms?: number;
  lag_ms?: number | null;
  draft?: string;
  capture?: boolean;
  video?: { video_id: string | null; title: string; tab_id: number | null; is_live: boolean; is_shorts: boolean } | null;
  source_label?: string | null;
  source_failed?: { reason: string; tried: string[] } | null;
  now_segment?: string | null;
  autoplay_blocked?: boolean;
  media_ms?: number;
}

export function isNs(m: unknown): m is { ns: typeof NS; type: string } {
  return !!m && typeof m === 'object' && (m as { ns?: unknown }).ns === NS && typeof (m as { type?: unknown }).type === 'string';
}
