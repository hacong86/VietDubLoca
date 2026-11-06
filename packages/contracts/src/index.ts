/**
 * Contract wire (docs/08) bằng zod — mirror contracts/*.schema.json (test đối chiếu Ajv ở tests/ts/contracts.test.ts).
 * Mọi dữ liệu từ trang/broker đều validate trước khi dùng. snake_case trên wire.
 */
import { z } from 'zod';

export const PROTOCOL_VERSION = 1 as const;

const id128 = z.string().min(1).max(128);

export const PlaybackClock = z.strictObject({
  session_id: id128,
  timeline_epoch: z.number().int().min(0),
  video_id: id128,
  media_ms: z.number().int().min(0),
  monotonic_ms: z.number().min(0),
  playback_rate: z.number().min(0.25).max(4),
  paused: z.boolean(),
  seeking: z.boolean(),
  stalled: z.boolean(),
  ad_state: z.enum(['content', 'ad', 'unknown']),
  visibility: z.enum(['visible', 'hidden']),
});
export type PlaybackClock = z.infer<typeof PlaybackClock>;

export const SourceCue = z.strictObject({
  cue_id: id128,
  start_ms: z.number().int().min(0),
  end_ms: z.number().int().min(0),
  text: z.string().max(16000),
  committed: z.boolean(),
});

export const CaptionBatch = z.strictObject({
  session_id: id128,
  timeline_epoch: z.number().int().min(0),
  source_id: id128,
  source_revision: z.number().int().min(1),
  source_kind: z.enum(['manual', 'auto', 'import', 'asr']),
  language: z.string().max(20).regex(/^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$/),
  coverage: z.enum(['full', 'partial', 'current_only']),
  available_until_ms: z.number().int().min(0),
  cues: z.array(SourceCue).max(500),
}).refine((b) => b.cues.every((c) => c.end_ms >= c.start_ms), { message: 'end_ms < start_ms' });
export type CaptionBatch = z.infer<typeof CaptionBatch>;

export const EVENT_NAMES = ['auth.ok', 'auth.error', 'session.state', 'source.changed', 'translation.ready', 'translation.blocked',
  'audio.begin', 'audio.end', 'audio.stop', 'audio.stopped', 'queue.status', 'model.progress', 'warning', 'error', 'ping', 'pong',
  'asr.draft'] as const;

export const EventEnvelope = z.strictObject({
  protocol_version: z.literal(1),
  event: z.enum(EVENT_NAMES),
  request_id: id128,
  session_id: z.string().nullable(),
  timeline_epoch: z.number().int().min(0),
  seq: z.number().int().min(0),
  sent_monotonic_ms: z.number().min(0),
  payload: z.record(z.string(), z.unknown()),
});
export type EventEnvelope = z.infer<typeof EventEnvelope>;

export const TranslationReady = z.object({
  segment_id: id128,
  revision: z.number().int().min(1),
  target_display: z.string(),
  target_spoken: z.string(),
  source_text: z.string(),
  flags: z.array(z.string()),
  start_ms: z.number().int().min(0),
  end_ms: z.number().int().min(0),
});
export type TranslationReady = z.infer<typeof TranslationReady>;

export const AudioBegin = z.object({
  segment_id: id128,
  revision: z.number().int().min(1),
  start_ms: z.number().int().min(0).optional(),
  end_ms: z.number().int().min(0).optional(),
  next_start_ms: z.number().int().min(0).nullable().optional(),
  sample_rate: z.literal(48000),
  duration_ms: z.number().nullable().optional(),
  target_display: z.string().optional(),
  source_text: z.string().optional(),
  preview: z.boolean().optional(),
  voice_id: z.string().nullable().optional(),
  speaker: z.string().nullable().optional(),
});

export const AudioEnd = z.object({
  segment_id: id128,
  revision: z.number().int().min(1),
  duration_ms: z.number().nullable().optional(),
  complete: z.boolean(),
  digest: z.string().optional(),
  frames: z.number().int().optional(),
  preview: z.boolean().optional(),
});

export const AudioStop = z.object({
  reason: z.string(),
  stop_epoch: z.number().int().min(0).optional(),
  segment_id: z.string().optional(),
  stop_revision_below: z.number().int().optional(),
});

export const SessionSnapshot = z.object({
  session_id: z.string(),
  video_id: z.string(),
  tab_id: z.number().int(),
  mode: z.enum(['vod_sync', 'live_delayed', 'study']),
  timeline_epoch: z.number().int(),
  state: z.string(),
  reason: z.string().nullable(),
  source: z.record(z.string(), z.unknown()).nullable(),
  media_ms: z.number(),
  buffer_media_ms: z.number(),
  pending_translation: z.number(),
  units: z.number(),
  blocked: z.number(),
  lag_ms: z.number().nullable(),
  live_queue_ms: z.number(),
  asr_active: z.boolean(),
  last_error: z.string().nullable(),
  audio_consumer: z.boolean().optional(),
});
export type SessionSnapshot = z.infer<typeof SessionSnapshot>;

export const ProjectError = z.object({
  code: z.string().min(1).max(128),
  message_vi: z.string().min(1),
  retryable: z.boolean(),
  request_id: z.string().min(1).max(128),
  session_id: z.string().nullable().optional(),
  details: z.record(z.string(), z.unknown()).optional(),
});
export type ProjectError = z.infer<typeof ProjectError>;

export const Segment = z.object({
  segment_id: z.string(),
  revision: z.number().int(),
  start_ms: z.number(),
  end_ms: z.number(),
  source_text: z.string(),
  status: z.string(),
  target_display: z.string(),
  target_spoken: z.string(),
  override: z.boolean(),
  flags: z.array(z.string()),
  error: z.string().nullable(),
  audio: z.string(),
  audio_ms: z.number().nullable(),
  final: z.boolean(),
  speaker: z.string().nullable().optional(),
});
export type Segment = z.infer<typeof Segment>;

/** Native Messaging (docs/08 §6). */
export const NativeReply = z.discriminatedUnion('type', [
  z.object({ type: z.literal('hello'), protocol_version: z.number(), app_version: z.string(), compatible: z.boolean() }),
  z.object({ type: z.literal('paired'), broker_url: z.string().regex(/^http:\/\/127\.0\.0\.1:\d{2,5}$/), session_token: z.string().min(32),
    expires_at: z.number(), protocol_version: z.number() }),
  z.object({ type: z.literal('status'), running: z.boolean(), port: z.number().nullable() }),
  z.object({ type: z.literal('stopped') }),
  z.object({ type: z.literal('error'), code: z.string() }),
]);
export type NativeReply = z.infer<typeof NativeReply>;

/** Tin nhắn nội bộ page bridge → content (dữ liệu KHÔNG tin cậy). */
export const CaptionTrackInfo = z.object({
  base_url: z.string().max(4096),
  language_code: z.string().max(20),
  kind: z.string().max(10).optional(),
  name: z.string().max(200).optional(),
  vss_id: z.string().max(100).optional(),
});
export const BridgePlayerInfo = z.object({
  ns: z.literal('vietdub-bridge'),
  type: z.literal('player_info'),
  nonce: z.string().max(64),
  video_id: z.string().max(20),
  title: z.string().max(500).optional(),
  duration_s: z.number().nonnegative().optional(),
  is_live: z.boolean().optional(),
  original_track_index: z.number().int().min(0).max(99).optional(),
  original_language: z.string().max(20).optional(),
  tracks: z.array(CaptionTrackInfo).max(100),
  captured_timedtext: z.array(z.string().max(4096)).max(20).optional(),
  captured_bodies: z.array(z.object({ video_id: z.string().max(20), lang: z.string().max(20), kind: z.string().max(10),
    body: z.string().max(8 * 1024 * 1024) })).max(6).optional(),
});
export type BridgePlayerInfo = z.infer<typeof BridgePlayerInfo>;
