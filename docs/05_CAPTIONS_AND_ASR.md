# Nguồn phụ đề và ASR

## 1. CaptionProvider contract
`probe(video_identity) -> SourceCapability`; `fetch(window) -> CuePage`; `subscribe(callback)` nếu nguồn cập nhật; `dispose()`. SourceCapability gồm kind, language, is_auto_generated, coverage(full/partial/current_only), available_until_ms, source_revision, seekable, confidence_basis. Full nghĩa có dữ liệu bao phủ toàn nội dung nguồn, không chỉ thấy transcript panel.

Provider order: caption tiếng Anh manual từ dữ liệu trang → auto tiếng Anh → transcript UI với coverage kiểm chứng → SRT/VTT người dùng cung cấp → tabCapture ASR do người dùng cấp quyền. Có thể chọn thủ công nguồn khác; adapter lỗi không làm crash toàn extension.

YouTube có transcript UI ở video có caption [S22], nhưng endpoint và cấu trúc DOM không phải hợp đồng ổn định cho extension. API captions.download chính thức yêu cầu quyền chỉnh sửa video, không phải giải pháp API-key cho mọi video công khai [S21]. Không yêu cầu cookie export, tài khoản bí mật, hoặc tránh paywall/DRM. Không dùng yt-dlp như điều kiện mặc định của extension.

## 2. Cách triển khai adapter trang
Feature probe, schema checking, finite timeout và diagnostics “đã thử nguồn nào”. Main-world bridge chỉ đọc JSON được trang cung cấp và kiểm videoId/language/cue structure. Content script gửi dữ liệu đã giới hạn về worker. Caption URL nếu có phải xuất phát từ dữ liệu track của video hiện tại, match host/path allowlist; không nhận URL từ arbitrary postMessage. Không backend-fetch URL bất kỳ.

Transcript DOM có thể virtualize/lazy load: phải tích lũy page/cursor và xác định thiếu đoạn. Không scrape vài dòng visible rồi gọi full. Không dựa vào selector lớp CSS duy nhất; adapter version + fixtures. Retry tối đa 2 với backoff, sau đó UI chọn import/ASR. Không claim “hỗ trợ tất cả video”.

## 3. Parser nhập
SRT/VTT UTF-8/BOM/CRLF; tối đa 10 MiB mặc định; 100.000 cue cap. Giữ cue overlaps và voice labels như metadata, không tự trộn người nói. Cue end<start → lỗi có số dòng. Mốc quá duration → cảnh báo trước apply. Cho offset signed trong phạm vi ±10 phút với xác nhận; raw time không sửa vĩnh viễn, lưu source_offset_ms.

## 4. Thu âm tab
Người dùng bấm hành động extension mới gọi tabCapture [S17]. Service worker lấy streamId, offscreen sử dụng với điều kiện phiên bản Chrome tương ứng [S15]. Không capture mic. Capture audio có thể làm đường loa gốc đổi: nối source audio vào output sau gain để vẫn nghe khi muốn [S17]. Nhánh ASR nằm trước gain. Tiếng VieNeu phát trong offscreen riêng, không insert vào tab YouTube.

AudioWorklet nhận float audio theo sample rate thực của AudioContext; chuyển mono có normalization, resample bandlimited về 16.000 Hz, gửi PCM s16le chunk 100–250ms qua WS. Không chỉ “bỏ bớt mẫu mỗi 3 sample” nếu input không đúng 48k. Chunk header có seq/capture_clock/media anchor/epoch. Packet gap phải được ghi nhận; không nối hai đoạn cách nhau như liên tục.

## 5. ASR baseline
faster-whisper `small.en` CPU int8, worker riêng; model tải opt-in, có hash. Đây là điểm bắt đầu để đo trên i9-11900K, không tuyên bố đủ nhanh trước test [S23]. VAD loại im lặng, max voiced window khoảng 8s, overlap khoảng 1s, endpoint silence khoảng 500ms; các giá trị là cấu hình đề xuất, cần tune bằng fixture nói nhanh/chậm.

Giữ draft và committed riêng. Local-agreement trên hai lần decode hoặc VAD endpoint + timestamp overlap để commit. Window tiếng Anh dùng task=transcribe, language=en; không nhờ Whisper translate tiếng Việt (pipeline dịch do Qwen/Gemma). Không phát TTS từ draft. Reject no_speech/lặp hallucination theo ngưỡng đã calibrate, không coi probability của ASR là bảo đảm.

## 6. Clock audio–video
Capture monotonic clock và video currentTime là hai trục khác nhau. Bản đồ từng đoạn dùng anchor(media_time_ms, mono_time_ms, playback_rate); khi pause/seek/ad/ratechange tạo đoạn mapping mới. Không gắn một tỉ lệ cố định cho toàn phiên. Model ASR timestamps được quy về capture interval rồi map sang source timeline. Tốc độ 2x có thể làm ASR kém: báo trạng thái và dùng Học kỹ/1x đề xuất, không lặng lẽ dịch thiếu.

## 7. Live và nguồn không đọc trước
Không có caption phía trước thì không dịch trước được; pause video cũng dừng âm thanh mới. Live source không seekable phải dùng delayed narration. Queue tối đa 30s, cảnh báo ở 12s/20s; ở hard cap dừng capture/narration với thông báo không theo kịp. Giữ văn bản đã commit để người dùng xem, không âm thầm bỏ lịch sử. VOD current_only có thể chọn Học kỹ pause sau mỗi cụm đã thu, tránh nói chồng nhưng không gọi đó là dịch trước.

## 8. Nguồn bị mất
Tab capture ended, permission denied, audio zero kéo dài, source language khác en, ad hoặc SPA change đều đóng phiên capture/flush. Resume chỉ sau xác minh nguồn và thao tác phù hợp. Không tự nhảy sang microphone. Dữ liệu raw audio chỉ ring buffer RAM khoảng 30s, không ghi đĩa mặc định.

## 9. Test bắt buộc
Caption có/không, full/partial/visible-only, auto rolling, cue overlap, SRT sai, seek trong khi ASR decode, VAD im lặng/nhạc, giọng Anh/Mỹ, code switching, tốc độ 2x, pause 30s, quảng cáo, fullscreen, Shorts, tab đóng/mute, từ chối quyền. E2E live YouTube không có fixture ổn định phải ghi là manual integration test, không fake mạng như đã test thật.
