# Hợp đồng REST, WebSocket, IPC
Phiên bản giao thức **1**. Đường dẫn REST bên dưới do dự án thiết kế, không phải toàn bộ đều là API của VieNeu. Mẫu OpenAPI: `contracts/openapi.yaml`. JSON Schema là baseline để sinh types và validate Python/TS.

## 1. Kênh và xác thực
Broker `http://127.0.0.1:8765` là port mặc định cấu hình, launcher có thể chọn port khác và trả qua Native Messaging. llama private default8766 chỉ broker sử dụng. Không hard-code port trên page, không truyền token vào content script. TTS/ASR worker dùng IPC riêng không public port.

`GET /health` chỉ liveness/version protocol tối thiểu, không tên model/path/payload. Mọi `/v1/*` phải Bearer auth và Origin/Host hợp lệ khi từ browser. CORS đúng extension origin, không wildcard. PATCH dùng revision/If-Match khi sửa tài nguyên có thể cạnh tranh; mismatch trả409.

## 2. REST endpoints
| Endpoint | Ý nghĩa | Phản hồi chính |
|---|---|---|
| GET /health | Liveness tối thiểu | 200 protocol_version/state |
| GET /v1/status | Runtime/model/worker/queue status | 200; dữ liệu đã redact |
| GET /v1/models | Catalog và download/load state | 200 models[] |
| POST /v1/models/{model_id}/download | Tải artifact đã xác nhận | 202 job_id; thiếu consent400 |
| POST /v1/models/{model_id}/activate | Unload cũ, load preset đã verified | 202 job_id; chưa verified409 |
| DELETE /v1/models/{model_id} | Xóa artifact không đang dùng | 204 hoặc409 |
| GET /v1/voices | Voice list runtime từ VieNeu | 200 voices[] hoặc503 |
| POST /v1/voices/preview | Sample cố định hoặc text giới hạn | 202 job_id; audio qua WS |
| POST /v1/sessions | Bắt đầu phiên active tab | 201 session_id,epoch,state |
| GET /v1/sessions/{session_id} | Snapshot trạng thái để rehydrate | 200 |
| DELETE /v1/sessions/{session_id} | Stop audio/capture/jobs, đóng phiên | 204 idempotent |
| POST /v1/sessions/{session_id}/captions | Batch cues + source coverage | 202 job_id/state; accepted_count qua event |
| POST /v1/sessions/{session_id}/clock | Snapshot đồng hồ | 204; epoch cũ409 |
| POST /v1/sessions/{session_id}/control | play/pause/seek/mode/stop/replay | 202 session_id,epoch,state,mode |
| PATCH /v1/segments/{segment_id} | Override display/spoken, revision | 200 version/value |
| POST /v1/segments/{segment_id}/retranslate | Re-translate với source/context xác minh | 202 job_id |
| GET/PUT /v1/glossary | Đọc/thay glossary có revision | 200 version/value |
| GET/PUT /v1/settings | Settings allowlist, versioned | 200 version/value |
| POST /v1/cache/clear | Xóa per-video/all với phạm vi xác nhận | 202 job_id |
| POST /v1/export/subtitles | Xuất source-time SRT/VTT local | 202 job_id, tên tương đối do server tạo |

Tài nguyên model download/delete/settings/export chỉ trusted extension UI hoặc companion, không từ page. Side effects cần request_id/idempotency_key, server giữ dedup TTL10 phút. Cùng key khác payload trả409. Không endpoint chạy lệnh/URL tùy ý.

## 3. Session creation
Body: video_id, tab_id, mode(vod_sync/live_delayed/study), source_language=en, target_language=vi, request_id. Broker chỉ một active session; tạo session mới do hành động user sẽ STOP cũ trước khi cấp quyền phát mới. session_id không bằng video_id. Epoch bắt đầu0; tăng khi seek/video/source timeline reset; ratechange re-anchor không nhất thiết tăng epoch nếu không đổi semantics nhưng phải reschedule audio đang chờ.

## 4. WebSocket
`ws://127.0.0.1:<port>/v1/events`. Validate Origin/Host trước upgrade. Message đầu `{"type":"auth","token":"...","protocol_version":1}` trong3s. Token không query; AUTH response dùng event envelope. Sau auth: subscribe(session_id), clock, control, ping/pong, audio PCM. Reject input trước auth. Một socket active cho offscreen, panel nhận status qua runtime messaging để không nhân đôi audio consumer.

Event envelope fields: protocol_version,event,request_id,session_id,timeline_epoch,seq,sent_monotonic_ms,payload. Seq tăng trên mỗi connection/event stream; reconnect lấy snapshot thay vì replay không giới hạn. session.state/queue.status dùng payload có state, reason, buffer_media_ms, lag_ms. translation.ready gồm segment_id/revision/display/spoken/source bounds. audio.begin mô tả format; audio.end có duration và digest nếu complete; audio.stop bắt buộc được consumer trả audio.stopped(epoch, reason). Model progress không có session thì session_id=null,epoch=0.

Event JSON schema chung không chứng minh payload đúng loại; triển khai dùng discriminated union cho từng event và test field allowlist. `translation.ready` không được có source timestamp do model tự sinh.

## 5. Framing audio binary v1
Một WS binary message: **4 byte unsigned header length big-endian** → UTF-8 JSON header → raw PCM signed16 little-endian. Đây là giao thức do dự án thiết kế, khác Native Messaging.

Header theo contracts/audio-chunk.schema.json: protocol_version,kind,session_id,epoch,segment_id(null cho ASR),revision,seq,sample_rate,channels=1,codec=pcm_s16le,sample_count,is_last; ASR có capture_monotonic_ms và source_media_ms bắt buộc ở validator nghiệp vụ. `payload_bytes=sample_count*2*channels`, exact match; header<=4096 bytes, frame<=256KiB. ASR sample_rate16000, TTS Turbo48000. Không nén tùy tiện, không base64 audio ở JSON thường. Sequence gap tạo warning/recovery, không ghép âm thời gian sai.

Consumer kiểm epoch/revision trước append buffer. is_last không có nghĩa tự phát; chỉ complete unit. Audio header không chứa file path/token. Duration complete = số mẫu/sample_rate, đối chiếu metadata có tolerance rounding. Network chunk không được hiểu là câu/word boundary.

## 6. Native Messaging bootstrap
Manifest tên `com.vietdub.local`, allowed_origins đúng ID extension, path absolute executable đã cài; stdin/stdout JSON UTF-8 có header uint32 native-endian theo Chrome [S18]. Windows little-endian, không nhầm audio big-endian header. Messages: hello(protocol_version), start, status, stop_owned_processes; no arbitrary command. Response: broker_url, session_token,expires_at,protocol_version. Token chỉ trusted extension context. Mỗi message nhỏ dưới64KiB. Binary executable phụ không được viết log text lẫn vào stdout frames.

## 7. Worker IPC
Broker→worker length-prefixed JSON control + separate binary sample payload theo transport đã chọn (named pipe Windows có user ACL hoặc stdio framed). Không đưa payload chưa validate vào worker. Các op cố định load/list_voices/infer/infer_stream/cancel/health/unload/shutdown. Request chứa job identity/epoch/revision; response có trạng thái backend/format. Hạn timeout rõ; `cancel` best effort không hứa ngắt CUDA kernel.

## 8. Error taxonomy
CONNECT_FAILED, AUTH_REQUIRED, AUTH_EXPIRED, ORIGIN_DENIED, PROTOCOL_MISMATCH, STALE_EPOCH, SOURCE_UNAVAILABLE, SOURCE_PARTIAL, PERMISSION_DENIED, INVALID_SUBTITLE, MODEL_NOT_READY, MODEL_CHECKSUM_MISMATCH, TRANSLATION_INVALID, TRANSLATION_TRUNCATED, VOICE_NOT_FOUND, TTS_INVALID_AUDIO, GPU_OOM, WORKER_CRASHED, LIVE_QUEUE_OVERFLOW, AUDIO_CAPTURE_ENDED, CACHE_DISK_FULL, REVISION_CONFLICT.

Response theo error.schema: code,message_vi,retryable,request_id; details allowlist không exception/path/token. HTTP400 validation;401 auth;403 origin/permission;404 unknown;409 epoch/revision/state;413 size;429 rate;503 model/worker chưa sẵn sàng. 500 được log redacted, UI không thấy traceback.

## 9. Contract tests
Python và TS phải đọc cùng fixtures trong examples. Validate unknown field, bad enum, negative time, end<start business check, source_id mismatch, epoch stale, seq gap, length mismatch/over-limit, invalid PCM rate, token query rejected, two active sessions, response ID omissions. Schema không thay business invariants hoặc security auth.
