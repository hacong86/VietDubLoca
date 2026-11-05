# Đồng bộ audio và video

## 1. Ba chế độ
**Đồng bộ VOD:** có caption phía trước, tạo audio hoàn chỉnh theo unit, bám timeline; cho phép auto-hold có chỉ báo nếu tiếng Việt dài/thiếu buffer để giữ đủ nội dung.
**Trực tiếp có trễ:** nguồn live/current-only ASR; tiếng Việt đi sau nguồn và UI hiển thị lag. Không đồng bộ khuôn miệng; không thể xử lý tương lai chưa nhận được.
**Học kỹ:** dừng ở ranh giới ý khi cần, nghe lại/chỉnh câu/xem song ngữ. Bảo toàn nghĩa cao hơn dòng hình chạy liên tục.

Không có chế độ “bỏ các câu chậm để bắt kịp” mặc định. Khi người dùng seek hoặc bấm Tiếp tục từ hiện tại sau lỗi live, đó là hành động chuyển epoch rõ ràng, có thông báo đoạn giữa không được nghe.

## 2. Clock chính
Dùng HTMLVideoElement.currentTime làm media clock tại snapshot. AudioContext.currentTime làm đồng hồ scheduling âm thanh. Khi PLAYING, anchor `(media_ms, audio_seconds, playback_rate, epoch)` dự đoán thời điểm phát:
`audio_start = anchor_audio + ((unit_start_ms - anchor_media_ms) / 1000) / playback_rate`.

Refresh anchor từ events và định kỳ khoảng 200ms ở foreground; background timers có thể bị throttle, nên audio engine dùng AudioContext clock cho horizon ngắn và yêu cầu re-anchor khi lệch/visibility đổi. Không dựa setTimeout một lần cho cả video. event `timeupdate` một mình không đủ làm scheduler chính xác. Kiểm tra currentTime nhảy hoặc video.paused/stalled trước phát. Clock stale >1s là cảnh báo; quá ngưỡng an toàn phải hold audio và đồng bộ lại thay vì nói sai.

## 3. Audio queue
Mỗi buffer kèm session_id, timeline_epoch, segment_id, revision, sample_rate, duration_ms, complete, source bounds. Audio engine từ chối item epoch/revision cũ cả lúc nhận lẫn lúc chuẩn bị play. Schedule horizon ban đầu tối đa 2s để hủy nhanh; phần còn lại giữ queue chưa gắn source node. Stop all active nodes ngay trên thao tác pause/seek/off, không chờ broker trả lời.

PCM s16le/float32 phải decode đúng sample rate. Turbo 48k mono; output device có thể 44.1k/48k khác, AudioContext resample phù hợp. Không đọc PCM 48k như 24k khiến giọng chậm/trầm [S09]. AudioBufferSourceNode là one-shot: pause/resume phải lưu offset và tạo node mới hoặc dùng media element seekable, không gọi start lại node cũ.

## 4. Bản Việt dài hơn khung nguồn
Cho source budget `B=(end_ms-start_ms)/1000/playback_rate` và audio duration `D`. Với chế độ VOD, audio native được stretch theo tốc độ video; residual catch-up chỉ 1.0–1.15 lần nếu nghe còn rõ. Cần time-stretch giữ pitch, không chỉ đổi playbackRate AudioBufferSourceNode làm pitch tăng. Component DSP/WASM phải được audit license trước bundle; test reference pitch và tiếng Việt. Không chọn thư viện cụ thể chưa xác minh license/duy trì.

Mượn khoảng lặng tối đa 500ms khi chắc không lấn unit kế tiếp; không làm thay mốc phụ đề gốc. Nếu vẫn thiếu thời gian, hold hình ở cuối cụm để nghe hết, gắn trạng thái “Đang đọc hết câu”. Không rewrite tự động gây mất nghĩa để đạt độ dài. At 2x, báo rõ giới hạn; ưu tiên giảm tốc độ xem bằng thao tác người dùng hoặc auto-hold của chế độ đã chọn.

## 5. Pause ownership
Lưu `pause_reason` USER/AUTO_BUFFER/AUTO_SENTENCE/AD/STALL. Chỉ auto-play nếu app là bên đã pause, session/epoch vẫn đúng và người dùng chưa pause thêm. Nếu người dùng bấm pause trong lúc auto-hold, chuyển USER và không auto-resume. Autoplay promise reject phải hiện nút “Bấm để tiếp tục âm thanh”.

## 6. Seek
Content dừng audio bằng control message ưu tiên → bump epoch → broker cancel → discard queue → currentTime mới → re-anchor → prefetch quanh vị trí. Nếu seek giữa câu, quy tắc mặc định: tìm unit chứa vị trí, hiện “Đọc lại câu hiện tại”, dùng nguyên câu từ đầu khi người dùng tiếp tục; không đoán cắt tiếng Việt theo phần trăm ký tự. Có cấu hình skip-current chỉ do người dùng chọn và thông báo. Không tự seek lùi video ngoài thao tác Nghe lại/Học kỹ đã bật.

## 7. Ads và YouTube SPA
Adapter xác định ad qua nhiều tín hiệu có kiểm chứng; khi không chắc nội dung/mốc video đã đổi phải AD_HOLD/UNKNOWN_SOURCE. Không bypass, skip hoặc chặn quảng cáo. Trong ad, dừng TTS và ASR nội dung, trả audio gốc thích hợp; sau ad re-probe video identity, source và clock. Không lấy ad media duration để cộng/trừ timeline nội dung bằng suy đoán. SPA navigation, playlist next, Shorts swipe đều session mới hoặc epoch mới có video identity mới.

## 8. Volume ownership
Trước thay volume/mute lưu snapshot và app-applied value. Theo dõi sự kiện người dùng thay đổi; khi tắt chỉ khôi phục phần app còn sở hữu, không ghi đè mức người dùng vừa chọn. Nếu dùng capture, audio input cho ASR không phụ thuộc source output gain. Không tự unmute một video người dùng đã mute mà không thao tác cho phép.

## 9. Đóng offscreen và worker suspend
AUDIO_PLAYBACK có quy tắc lifecycle khi im lặng; USER_MEDIA chỉ dùng khi thật sự capture [S16]. Không phát âm im để lách lifecycle. Khi offscreen bị đóng, worker recreate khi có lý do hợp lệ, reauth WS và rehydrate metadata, bắt đầu audio từ vị trí xác minh. Worker restart không khởi động bất ngờ đoạn cũ. Không đặt heartbeat ở popup.

## 10. Phép đo
Log thời điểm thao tác, audio stop ack, unit due/start/end, media offset, underrun, auto_hold duration, timeline reset. p95 onset drift ≤350ms là mục tiêu 1x caption VOD đã chuẩn bị; live đo lag riêng, không đưa chung một số. Soak 2h, nhiều seek/ratechange/ad; không tích lũy trễ theo tổng số câu.
