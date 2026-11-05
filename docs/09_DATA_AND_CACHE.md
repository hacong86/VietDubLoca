# Dữ liệu, cache và migration

Schema thực thi baseline: `data/schema.sql`; SQLite WAL + foreign_keys=ON, tất cả thao tác đổi revision trong transaction. Đường dẫn mặc định `%LOCALAPPDATA%/VietDubLocal/`, có thư mục models/cache/logs/db/runtime tách riêng.

## Thực thể
Video: định danh video/provider, title có thể rỗng; không lưu URL signed/cookie. SourceTrack: language/origin/coverage/revision/content hash. Cue: text/time gốc. Segment: translation unit có cue map và source revision. Translation: model/prompt/glossary/context fingerprints, display/spoken, validator flags, status. AudioAsset: content hash, format, sample rate, duration, voice fingerprint, path tương đối. PlaybackSession: ephemeral timeline_epoch/state/active tab, không phải định danh nội dung cache. Override: bản người dùng sửa có prior revision/audit timestamp. GlossaryEntry: scope và version. ModelArtifact: nguồn/version/SHA/path/size/verified, không coi `main` là checksum.

## Khóa
DB UUID cho row; content-address SHA-256 cho cache reuse. Canonical JSON UTF-8 sorted keys; normalize Unicode NFC trước hash; ghi normalization_version. Source/video/time mapping không bị model ghi đè. Một text ở context khác phải có translation cache key khác. Một audio raw có thể reuse qua timeline khác nhưng binding session/epoch nằm ở consumer.

## Chính sách cache
Target 2 GiB, LRU + TTL 14 ngày; max per-file 64 MiB mặc định; segment audio nhỏ hơn nhiều nhưng limit bảo vệ đầu vào. Ghi .tmp trong cache root, fsync/rename atomic sau complete+validate; không đưa file incomplete vào DB READY. Streaming không complete không cache thành full audio. Cleanup không xóa file đang mở: lease count + deferred deletion. Khi ổ đĩa gần đầy dừng cache mới, vẫn hoạt động RAM bounded và báo trạng thái.

## Invalidation
- Model/quant/SHA/sampling/template/prompt khác → translation và downstream audio khác.
- Glossary/context/source revision khác → units chịu ảnh hưởng khác; không global flush không cần thiết.
- Giọng/SDK/TTS model/phonetic rule khác → chỉ audio/spoken phụ thuộc.
- Override mới → revision mới, cancel future stale audio; lưu bản trước để undo.
- Seek/chuyển tab → epoch mới, không nhất thiết xóa cache nội dung đúng.

## Privacy
History opt-in, cache bounded có thời hạn; private mode dùng memory DB/queue và không ghi text/audio, log chỉ metric không payload. Không lưu raw capture ngoài ring RAM 30s. Xuất diagnostic phải preview phạm vi, mặc định bỏ title/transcript/audio/path user; hash có thể vẫn là dữ liệu liên kết nên không upload tự động.

## Export SRT/VTT
Có xuất Việt/song ngữ theo time nguồn, đã áp source offset do user xác nhận. Không dùng thời gian wall-clock khi app auto-hold. Preserve cue mapping: một unit từ nhiều cue có thể xuất cue gộp theo span; ghi lựa chọn và không pretend word-level alignment. Dấu câu Việt giữ UTF-8. Có cảnh báo quyền sử dụng trước export, không kèm video/audio gốc.

## Migration/recovery
`PRAGMA user_version`; migration tăng đơn điệu, backup DB trước thay lớn, schema checksum. WAL checkpoint trước backup/export. Model/audio cache không nằm trong migration. Khi crash giữa TTS write và DB insert, startup janitor dọn orphan temp với TTL, không xóa file đang thuộc phiên khác. Installer rollback kiểm phiên bản DB hỗ trợ; không mở DB mới bằng binary cũ nếu migration không tương thích.

## Các bất biến phải test
end_ms>=start_ms; mọi translation chỉ thuộc segment có nguồn; revision tăng; audio READY có checksum và duration>0; unique(session_id,epoch,segment,revision) trong scheduling; path resolve nằm trong app root; file import không symlink/junction escape; stale jobs không tạo trạng thái PLAYING.
