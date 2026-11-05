# Kiến trúc hệ thống

## 1. Monorepo đích
```text
apps/extension/        manifest, worker, content, page bridge, offscreen, sidepanel, options
apps/companion/        broker FastAPI, session scheduler, model manager, tray, launcher
workers/tts/           venv riêng, VieNeu v3 Turbo, framed IPC
workers/asr/           venv riêng, faster-whisper, framed IPC
packages/contracts/   type sinh từ contracts/ + validator
packages/audio/       PCM, clock, jitter queue, time-stretch worker/WASM
packages/captions/    adapter, parser, sentence builder
packages/translation/ prompt builder, glossary, validators
packages/storage/    SQLite, migrations, cache
packaging/windows/   installer, native host manifest, per-user registry
```
Đây là cây **cần triển khai**, không phải các thư mục code hoàn thiện có sẵn trong bộ tài liệu.

## 2. Ranh giới thành phần
- Content script theo dõi video và overlay, gửi snapshots có video_id/clock, không giữ token local.
- Page bridge chỉ đọc dữ liệu trang cần thiết khi content isolated world không thấy được. Dữ liệu page là không tin cậy; bridge không có quyền backend/shell.
- Service worker điều phối quyền Chrome và Native Messaging. Không sở hữu hàng đợi audio bền vững [S20].
- Offscreen sở hữu AudioContext, tab stream, AudioWorklet, WS với broker. Các Chrome API không hỗ trợ ở offscreen phải gọi qua runtime message về worker [S16].
- Side panel/settings React/Vite; không phải nơi thực thi model hoặc giữ clock audio.
- Broker giữ session/epoch, priority queue, status và DB; chỉ 127.0.0.1, auth bắt buộc trừ health tối thiểu.
- llama-server riêng chỉ nhận prompt text từ broker. TTS worker riêng để giữ torch/transformers tương thích VieNeu; ASR worker riêng để tránh xung đột CUDA/cuDNN [S08][S23].
- Native host nhỏ dùng stdin/stdout để bootstrap; stdout chỉ frame giao thức, log sang stderr. Không truyền PCM nhiều MB bằng Native Messaging [S18].

## 3. Luồng có caption
Trang → CaptionProvider → cue/source_revision → sentence builder → context/glossary → model dịch → structural checks → committed translation → TTS worker → audio metadata/cache → WS PCM/offscreen → schedule theo video clock. Panel nhận text/status độc lập với audio.

## 4. Luồng không caption
Người dùng bấm cấp capture → worker lấy stream ID → offscreen getUserMedia → AudioWorklet resample → PCM 16k → broker → ASR commit → pipeline dịch/TTS trên. Stream input được tách BEFORE gain output; không phát tiếng Việt vào tab nguồn [S15][S17].

```text
Captured tab audio ─┬─→ resample/ASR
                    └─→ source gain → output
VieNeu PCM ───────────→ Vietnamese gain → output
```
Caption-only không nhất thiết cần capture. Khi không capture, giảm âm thanh gốc qua adapter volume có lưu quyền sở hữu và theo dõi thao tác người dùng. Khi capture, để nguồn đủ mức cho ASR và dùng gain ở offscreen để nghe nhỏ. Không áp cả hai cách giảm khiến mất nguồn.

## 5. Message trust
Content → worker: validate sender.tab.id, videoId, namespace, size; never accept URL/path/token/model executable từ trang. Worker → broker chỉ phiên active đã auth. Model output là text không tin cậy, không tool call. UI dùng textContent hoặc escaped rendering.

## 6. Lifecycle
IDLE → CONNECTING → DISCOVERING → WARMING → BUFFERING → PLAYING. Nhánh PAUSED_USER, PAUSED_AUTO, SEEKING, AD_HOLD, STALLED, SOURCE_LOST, RECONNECTING, ERROR, STOPPED. State machine typed; mỗi transition có guard/side effect/test. Audio engine xác nhận stopped epoch để broker không nhầm worker cancel với audio đã im.

## 7. Hủy tác vụ
Khi seek: phát local STOP ngay → epoch++ → thông báo broker cancel các job epoch cũ → clear queue → re-anchor → lấy caption quanh vị trí mới. GPU kernel có thể chưa hủy ngay; discard kết quả dựa epoch. Mỗi worker serial queue có bounded backlog, không để 100 câu cũ chờ trước câu mới.

## 8. GPU scheduling
Một model dịch resident. Không phải batch cả video. TTS deadline > translation gần playhead > prefetch xa > preview/benchmark. VOD caption không nạp ASR. ASR CPU int8 là baseline tiết kiệm GPU; bật GPU ASR chỉ khi measured budget cho phép. Health bằng IPC timeout/metrics, không suy worker sống là model sẵn sàng.

## 9. Công nghệ và phiên bản
TypeScript strict + React + Vite, Python 3.11 x64 + FastAPI/Pydantic; SQLite; llama.cpp CUDA binary; VieNeu 3.8.1 baseline. Chưa pin số phiên bản mọi thư viện vì chưa resolve/build thật. Đội triển khai phải tạo uv/npm lock sau khi test, lưu SHA binary/model. Không dùng Web Speech API hoặc Chrome Translator để che integration chưa làm.
