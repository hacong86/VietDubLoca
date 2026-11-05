PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
BEGIN;
CREATE TABLE IF NOT EXISTS videos (
 video_id TEXT PRIMARY KEY, provider TEXT NOT NULL DEFAULT 'youtube', title TEXT,
 history_opt_in INTEGER NOT NULL DEFAULT 0 CHECK(history_opt_in IN (0,1)),
 created_at TEXT NOT NULL, last_opened_at TEXT
);
CREATE TABLE IF NOT EXISTS source_tracks (
 source_id TEXT PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
 revision INTEGER NOT NULL CHECK(revision>=1), language TEXT NOT NULL, kind TEXT NOT NULL,
 coverage TEXT NOT NULL CHECK(coverage IN ('full','partial','current_only')),
 content_hash TEXT NOT NULL, available_until_ms INTEGER NOT NULL DEFAULT 0 CHECK(available_until_ms>=0),
 offset_ms INTEGER NOT NULL DEFAULT 0, UNIQUE(video_id,content_hash)
);
CREATE TABLE IF NOT EXISTS cues (
 cue_id TEXT NOT NULL, source_id TEXT NOT NULL REFERENCES source_tracks(source_id) ON DELETE CASCADE,
 start_ms INTEGER NOT NULL CHECK(start_ms>=0), end_ms INTEGER NOT NULL CHECK(end_ms>=start_ms),
 raw_text TEXT NOT NULL, committed INTEGER NOT NULL CHECK(committed IN (0,1)),
 PRIMARY KEY(source_id,cue_id)
);
CREATE TABLE IF NOT EXISTS segments (
 segment_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source_tracks(source_id) ON DELETE CASCADE,
 revision INTEGER NOT NULL CHECK(revision>=1), source_hash TEXT NOT NULL, source_text TEXT NOT NULL,
 start_ms INTEGER NOT NULL CHECK(start_ms>=0), end_ms INTEGER NOT NULL CHECK(end_ms>=start_ms),
 cue_map_json TEXT NOT NULL, boundary_reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_artifacts (
 artifact_id TEXT PRIMARY KEY, source_repo TEXT NOT NULL, revision TEXT, filename TEXT NOT NULL,
 sha256 TEXT CHECK(sha256 IS NULL OR length(sha256)=64), size_bytes INTEGER CHECK(size_bytes>=0),
 local_path TEXT, verified INTEGER NOT NULL DEFAULT 0 CHECK(verified IN (0,1)),
 CHECK(verified=0 OR (sha256 IS NOT NULL AND revision IS NOT NULL AND local_path IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS translations (
 translation_id TEXT PRIMARY KEY, segment_id TEXT NOT NULL REFERENCES segments(segment_id) ON DELETE CASCADE,
 revision INTEGER NOT NULL CHECK(revision>=1), cache_key TEXT NOT NULL UNIQUE,
 model_fingerprint TEXT NOT NULL, prompt_version TEXT NOT NULL, glossary_version INTEGER NOT NULL,
 context_hash TEXT NOT NULL, target_display TEXT NOT NULL, target_spoken TEXT NOT NULL,
 flags_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL CHECK(status IN ('DRAFT','READY','BLOCKED','OVERRIDE')),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audio_assets (
 audio_id TEXT PRIMARY KEY, cache_key TEXT NOT NULL UNIQUE, translation_id TEXT NOT NULL REFERENCES translations(translation_id) ON DELETE CASCADE,
 voice_fingerprint TEXT NOT NULL, sdk_version TEXT NOT NULL, codec TEXT NOT NULL,
 sample_rate INTEGER NOT NULL CHECK(sample_rate>0), channels INTEGER NOT NULL CHECK(channels=1),
 duration_ms INTEGER NOT NULL CHECK(duration_ms>0), size_bytes INTEGER NOT NULL CHECK(size_bytes>0),
 sha256 TEXT NOT NULL CHECK(length(sha256)=64), relative_path TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('READY','DELETE_PENDING')), last_access_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS overrides (
 override_id TEXT PRIMARY KEY, segment_id TEXT NOT NULL REFERENCES segments(segment_id) ON DELETE CASCADE,
 revision INTEGER NOT NULL CHECK(revision>=1), target_display TEXT NOT NULL, target_spoken TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(segment_id,revision)
);
CREATE TABLE IF NOT EXISTS glossary_entries (
 entry_id TEXT PRIMARY KEY, version INTEGER NOT NULL CHECK(version>=1), domain TEXT NOT NULL,
 source_term TEXT NOT NULL, target_term TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('preserve','translate')),
 case_sensitive INTEGER NOT NULL DEFAULT 0 CHECK(case_sensitive IN (0,1)), pronunciation TEXT,
 enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)), UNIQUE(domain,source_term)
);
CREATE TABLE IF NOT EXISTS playback_sessions (
 session_id TEXT PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
 timeline_epoch INTEGER NOT NULL CHECK(timeline_epoch>=0), active_tab_id INTEGER NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('vod_sync','live_delayed','study')), state TEXT NOT NULL,
 media_ms INTEGER NOT NULL DEFAULT 0 CHECK(media_ms>=0), updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_segments_time ON segments(source_id,start_ms,end_ms);
CREATE INDEX IF NOT EXISTS idx_audio_lru ON audio_assets(last_access_at);
CREATE INDEX IF NOT EXISTS idx_translation_segment ON translations(segment_id,revision);
PRAGMA user_version = 1;
COMMIT;
