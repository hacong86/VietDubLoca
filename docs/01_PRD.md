# PRD — VietDub Local
Phiên bản 1.0 • 23/09/2026 • Trạng thái: **sẵn sàng làm cơ sở triển khai, chưa chứng nhận chạy thực tế**.

## 1. Vấn đề và mục tiêu
Người dùng chính là Sếp Hà, nói tiếng Việt, thường xem YouTube về AI, công nghệ, lập trình/app/game nhưng khó hiểu tiếng Anh. Cần bật một lần để nghe bản thuyết minh Việt tự nhiên, nhìn được phụ đề và giữ quyền điều khiển video; không trả phí API theo ký tự và không gửi lời thoại cho nhà cung cấp AI.

Thành công là hiểu đúng nội dung, đọc tên nút/tùy chọn đủ nhận diện, không bỏ cảnh báo hay phủ định, và không phải thường xuyên chỉnh lại âm thanh. Tốc độ không được đánh đổi bằng việc tự tóm tắt hoặc bỏ câu.

## 2. Phạm vi sản phẩm hoàn chỉnh
Chrome trên Windows + companion local. YouTube video thông thường, playlist/chuyển video kiểu SPA, chế độ theater/fullscreen; Shorts được xử lý như nguồn video có lifecycle riêng và phải có ca kiểm thử. Caption có sẵn, nhập SRT/VTT và ASR từ tab khi không lấy được caption đều thuộc phạm vi. Livestream có chế độ thuyết minh trễ được ghi rõ, không giả định đồng bộ môi theo hình.

Các chức năng đầy đủ: model manager, dịch ngữ cảnh, glossary, sửa câu, phát âm, VieNeu preset, audio sync, học kỹ, song ngữ, cache/history có lựa chọn, xuất phụ đề, diagnostic, bảo mật, installer và rollback. Không có tài khoản, thanh toán, quảng cáo trong extension, API cloud, clone giọng người trong video, đa ngôn ngữ tự phát, xử lý TikTok/Facebook, lip-sync, hoặc tải/xuất video để tái xuất bản trong phạm vi này. Việc loại các sản phẩm khác là ranh giới của dự án, không phải bỏ FR.

## 3. Các quyết định nền tảng
Qwen3.5-4B Q5_K_M là preset khởi đầu do trọng số tương đối gọn; Gemma E4B QAT là đối chứng, có thể trở thành mặc định nếu thắng đo chất lượng và vẫn đáp ứng tài nguyên. Đây là quyết định triển khai có cổng kiểm chứng, không phải kết luận khoa học về model [S01–S06].
VieNeu v3 Turbo local; SDK baseline 3.8.1. TTS và ASR có process/venv riêng, model dịch qua llama.cpp [S07–S14][S23].

## 4. Hành trình người dùng
### UJ-01 — Lần đầu
Cài companion per-user → cài/bật extension → kiểm cấu hình → xem dung lượng/quyền model → tải hoặc chọn model đã có → thử dịch câu mẫu và nghe giọng → ghép nối local → mở video. Đổi model lớn không xảy ra âm thầm.
### UJ-02 — Video có caption
Bấm Bật tiếng Việt → hiển thị nguồn và đang chuẩn bị → đọc trước vài cụm → giảm audio gốc ở mức người dùng chọn → phát theo video. Tua sang chỗ khác hủy tiếng cũ và chuẩn bị lại. Thiếu buffer ở VOD được phép hold có chỉ báo.
### UJ-03 — Không lấy được caption
Hiện lý do → cho lựa chọn Nhập phụ đề hoặc Dịch âm thanh tab → người dùng cấp tabCapture → ASR commit cụm → dịch → nói có trễ. Không quảng cáo chế độ này là âm Việt đúng theo từng khung hình.
### UJ-04 — Học kỹ
Bật Học kỹ → mỗi câu được nghe đầy đủ dù phải dừng hình → xem Anh–Việt, nghe lại, sửa bản dịch/thuật ngữ. Người dùng tự pause thì ứng dụng không tự bật play.
### UJ-05 — Máy bận hoặc worker lỗi
Hiện pipeline bottleneck → dừng phát sai thời gian → hạ batch/đọc trước → đề nghị preset nhẹ hoặc Turbo CPU đã có, không tải model tự ý → retry có giới hạn, cache/override còn nguyên.

## 5. Nguyên tắc trải nghiệm
Không dịch độc lập từng cue cắt giữa câu. Không đưa văn bản chưa commit vào TTS. Không giả định có phụ đề là luôn lấy được cả video. Không đọc quảng cáo bằng transcript nội dung. Không để người dùng nghe hai tab cùng nói. Giao diện chính bằng tiếng Việt, tên sản phẩm/nút/code giữ đúng chữ gốc.

## 6. Yêu cầu chức năng

### FR-001 — Kiểm tra môi trường
**Nhóm:** Cài đặt.

Phát hiện OS x64, Python/runtime đóng gói, GPU/driver, RAM, ổ đĩa và model có sẵn. Không suy VRAM trống từ dung lượng nhãn GPU.

**Nghiệm thu:** Hiện nguồn đo và lỗi hành động được; không hiện Sẵn sàng nếu dependency/model thiếu.

### FR-002 — Model manager
**Nhóm:** Cài đặt.

Hiện model, quant, nguồn, cỡ download, trạng thái kiểm checksum; tải có đồng ý, pause/resume, retry và nhập tệp local.

**Nghiệm thu:** Không tải mmproj ở text-only; file .part không được load; checksum sai phải chặn.

### FR-003 — Ghép nối extension–companion
**Nhóm:** Cài đặt.

Native Messaging kiểm extension ID và trả token phiên qua kênh riêng, chỉ loopback; onboarding hướng dẫn trong side panel.

**Nghiệm thu:** Trang YouTube không đọc được token; companion dừng thì có thông báo và nút kết nối lại.

### FR-004 — Tự khởi động có lựa chọn
**Nhóm:** Cài đặt.

Có tùy chọn khởi động cùng Windows, tray trạng thái và thoát; mặc định không tự bật startup.

**Nghiệm thu:** Thoát phải ngừng thu/phát và không còn worker con mồ côi do app tạo.

### FR-005 — Phát hiện video và nguồn caption
**Nhóm:** Nguồn.

Theo dõi SPA navigation, video ID, track en/en-US/en-GB, caption thủ công/auto và khả năng đọc trước.

**Nghiệm thu:** Chuyển video không dùng transcript cũ; ưu tiên track tiếng Anh thủ công nếu có.

### FR-006 — Lấy transcript có kiểm soát
**Nhóm:** Nguồn.

Adapter thử nguồn trang công khai trong phiên người dùng; transcript DOM có phân trang/ảo hóa; không đoán đã đủ từ vài dòng visible.

**Nghiệm thu:** Gắn coverage full/partial/current_only và available_until_ms đúng; timeout chuyển nguồn có thông báo.

### FR-007 — Nhập SRT/VTT
**Nhóm:** Nguồn.

Người dùng nhập phụ đề họ có quyền dùng; hỗ trợ UTF-8/BOM, line ending, cue overlap, offset chỉnh tay.

**Nghiệm thu:** Tệp lỗi không crash; hiển thị dòng lỗi; không chạy markup/script trong caption.

### FR-008 — Dự phòng ASR local
**Nhóm:** Nguồn.

Xin tabCapture khi người dùng bấm; mono 16k PCM vào faster-whisper; không lấy microphone.

**Nghiệm thu:** Từ chối quyền không làm hỏng caption mode; ASR không chạy khi caption đủ.

### FR-009 — Ổn định ASR và chống lặp
**Nhóm:** Nguồn.

VAD, cửa sổ overlap, commit phần ổn định, word-time optional; không gửi draft còn sửa sang TTS.

**Nghiệm thu:** Hai cửa sổ chứa cùng lời nói chỉ phát một lần; chữ draft được phân biệt trên UI.

### FR-010 — Ghép cụm đủ nghĩa
**Nhóm:** Dịch.

Khôi phục dấu câu thận trọng, gộp cue theo ranh giới ý với time map còn nguyên; giữ phủ định/điều kiện.

**Nghiệm thu:** Fixture câu bị cắt giữa dòng cho một đơn vị dịch đúng thứ tự, không tự sửa timestamps bằng LLM.

### FR-011 — Ngữ cảnh giới hạn
**Nhóm:** Dịch.

Hai đơn vị trước, một đơn vị sau nếu có, chủ đề do người dùng chọn và glossary; không suy nội dung video chưa thấy.

**Nghiệm thu:** Prompt có giới hạn token; context tham khảo không xuất hiện như câu được dịch thêm.

### FR-012 — Dịch tiếng Việt tự nhiên đầy đủ
**Nhóm:** Dịch.

Giọng diễn đạt trung tính, dễ nghe, không lược ý, không bình luận, giữ ngôi và mức chắc chắn.

**Nghiệm thu:** Qua chấm người theo rubric; câu phủ định/đơn vị/cảnh báo không được đảo hoặc mất.

### FR-013 — Từ điển thuật ngữ
**Nhóm:** Dịch.

Thêm/sửa/xóa/nhập/xuất glossary; phân domain, case sensitivity, whole phrase, preserve/translate; bản ghi theo phiên bản.

**Nghiệm thu:** Tên lệnh và thuộc tính protected phục hồi đủ; từ bank/margin không thay hàng loạt sai ngữ cảnh.

### FR-014 — Bản hiển thị và bản đọc
**Nhóm:** Dịch.

target_display giữ code/tên gốc, target_spoken áp dụng từ điển phát âm và số/đơn vị có quy tắc.

**Nghiệm thu:** Sửa phát âm không đổi chữ phụ đề hoặc semantic numbers; spoken text không đọc placeholder.

### FR-015 — Kiểm tra trước TTS
**Nhóm:** Dịch.

JSON/ID/schema, placeholder, coverage, length warning, ngôn ngữ heuristic, dấu reasoning/tool call; tối đa một repair.

**Nghiệm thu:** Kết quả sai cấu trúc bị chặn; từ ngoại ngữ/tên riêng hợp lệ không bị cấm máy móc.

### FR-016 — Sửa và dịch lại câu
**Nhóm:** Dịch.

Panel cho chỉnh bản Việt, nghe preview, lưu override, hoặc dịch lại đơn vị; giữ lịch sử revision.

**Nghiệm thu:** Audio revision cũ hủy; override còn sau mở lại video và được đánh dấu do người dùng sửa.

### FR-017 — Đổi model/preset
**Nhóm:** Dịch.

Chọn Qwen Q5/Q4 hoặc Gemma đã tải; tắt thinking đúng template; chuyển model có unloading.

**Nghiệm thu:** Chỉ một model dịch resident; preset và fingerprint xuất hiện trong diagnostic/cache key.

### FR-018 — VieNeu Turbo local
**Nhóm:** TTS.

Tạo âm thanh bằng SDK v3 Turbo hoặc adapter compatible local theo contract; không gọi cloud.

**Nghiệm thu:** Mạng AI egress bị chặn mà model đã tải vẫn dịch và nói được từ fixture local.

### FR-019 — Chọn và nghe thử giọng
**Nhóm:** TTS.

Lấy danh sách giọng từ SDK runtime; tìm kiếm/nghe thử/chọn; không hard-code tổng số giọng.

**Nghiệm thu:** Voice ID không còn hợp lệ báo rõ và yêu cầu chọn preset khác; không tự đổi giọng âm thầm.

### FR-020 — Buffer câu và streaming
**Nhóm:** TTS.

VOD tạo xong từng câu để biết duration; live cho streaming PCM nhưng chỉ từ bản dịch đã commit.

**Nghiệm thu:** Audio ghi rõ sample rate/channel/seq/done; không coi mỗi HTTP chunk là một WAV riêng.

### FR-021 — Bật/tắt thuyết minh
**Nhóm:** Phát.

Nút trên trang và side panel; khi tắt dừng audio/ASR và khôi phục audio gốc theo quyền sở hữu volume.

**Nghiệm thu:** Không còn lời Việt sau thao tác tắt quá giới hạn stop latency; không tăng âm lượng do người dùng đã giảm.

### FR-022 — Âm lượng độc lập
**Nhóm:** Phát.

Thanh tiếng Việt/tiếng gốc; capture route giảm gain sau điểm ASR; chế độ không capture có adapter volume riêng.

**Nghiệm thu:** Giảm tiếng gốc không làm ASR mất tín hiệu; TTS không lọt vào nguồn ASR.

### FR-023 — Phụ đề Việt/song ngữ
**Nhóm:** Phát.

Overlay bật/tắt, font/size/vị trí, tương phản, không đè nút quan trọng; panel theo câu đang xem.

**Nghiệm thu:** Dấu tiếng Việt hiển thị đúng trong fullscreen/theater; thao tác bàn phím đọc được.

### FR-024 — Pause/play/seek
**Nhóm:** Phát.

Dừng/tiếp tục theo vị trí thực; seek flush audio, tăng epoch và ưu tiên vị trí mới.

**Nghiệm thu:** Kết quả worker cũ trả muộn bị bỏ; replay câu rõ ràng thay vì nối sai nửa câu.

### FR-025 — Đổi tốc độ video
**Nhóm:** Phát.

Theo 0.5–2.0x, căn wall-time mới, time-stretch giữ pitch; nếu không đủ chuyển hold rõ ràng trong VOD.

**Nghiệm thu:** Không double-speed do vừa đổi rate video vừa áp cùng rate sai lần nữa lên audio đã stretch.

### FR-026 — Buffering và quảng cáo
**Nhóm:** Phát.

Khi video stalled/ad hoặc loại nội dung không xác định: hold tiếng Việt, khôi phục audio gốc quảng cáo.

**Nghiệm thu:** Không phát lời nội dung trong quảng cáo; resume phải re-anchor timeline, không trừ duration quảng cáo bằng phỏng đoán.

### FR-027 — Chế độ đồng bộ VOD
**Nhóm:** Phát.

Đọc trước nguồn có coverage, buffer thích nghi và auto-hold ngắn nếu cần để không bỏ câu.

**Nghiệm thu:** UI phân biệt đang nạp giọng với đang chuẩn bị nội dung; không tuyên bố zero-latency.

### FR-028 — Chế độ trực tiếp có trễ
**Nhóm:** Phát.

Live hoặc current_only ASR, hiển thị độ trễ; queue hữu hạn và cảnh báo không theo kịp.

**Nghiệm thu:** Không lặng lẽ bỏ câu; queue overflow dừng tiếng Việt/báo lỗi và yêu cầu thao tác tiếp tục.

### FR-029 — Chế độ Học kỹ
**Nhóm:** Phát.

Tự dừng ở cuối câu để đọc hết, nghe lại câu, tua tới câu, xem Anh–Việt; không tự tạo bài học ngoài nội dung.

**Nghiệm thu:** Người dùng bấm pause luôn thắng auto-resume; audio nguồn không được kỳ vọng tiến khi video đã dừng.

### FR-030 — Một tab chủ động
**Nhóm:** Phát.

Mỗi thời điểm chỉ một tab phát/thu; đổi tab bằng hành động người dùng, giải phóng tab trước.

**Nghiệm thu:** Hai tab YouTube cùng mở không phát tiếng Việt chồng; tab nền không giành phiên.

### FR-031 — Chuyển video và mất tab
**Nhóm:** Phát.

Hủy phiên khi SPA navigation/tab đóng/nguồn audio ended; resume sau lỗi phải revalidate video ID.

**Nghiệm thu:** Không audio mồ côi và không caption cross-video.

### FR-032 — Side panel đầy đủ
**Nhóm:** Giao diện.

Video/source/mode/translation/TTS/model/queue/CPU-GPU trạng thái, transcript, tìm kiếm, sửa câu, điều khiển.

**Nghiệm thu:** Popup đóng không dừng phiên; panel có thể đóng mà audio engine vẫn đúng.

### FR-033 — Cài đặt và reset
**Nhóm:** Giao diện.

Ngôn ngữ UI Việt, mức buffer, giọng, model, cache, quyền riêng tư, shortcut; reset có xác nhận và phạm vi.

**Nghiệm thu:** Reset settings không xóa model/override nếu người dùng không chọn.

### FR-034 — Lỗi có hướng xử lý
**Nhóm:** Giao diện.

Mã lỗi ổn định, thông báo Việt, retry/đổi nguồn/mở diagnostic; không hiển thị traceback hoặc token cho người dùng.

**Nghiệm thu:** Mỗi mã lỗi có hành động hữu ích và error record đã redact.

### FR-035 — Cache bản dịch/âm thanh
**Nhóm:** Dữ liệu.

Fingerprint source/context/model/prompt/glossary/voice; LRU và TTL; cache hit không chạy lại model.

**Nghiệm thu:** Đổi model/giọng/override không lấy nhầm audio; cue giống text nhưng khác context không đụng key.

### FR-036 — Lịch sử cá nhân và xuất phụ đề
**Nhóm:** Dữ liệu.

Lưu video theo opt-in lịch sử; tìm lại bản dịch; xuất VI/song ngữ SRT/VTT với quyền nội dung; không xuất video lồng tiếng.

**Nghiệm thu:** Timecode bản export là timeline nguồn, không phải lịch âm thanh đã auto-hold.

### FR-037 — Xóa dữ liệu và private mode
**Nhóm:** Dữ liệu.

Xóa từng video/toàn bộ cache; private mode không ghi caption/audio/history xuống đĩa.

**Nghiệm thu:** File audio đã mở đóng handle trước xóa; private mode không để payload trong log/crash report.

### FR-038 — Phục hồi worker/GPU
**Nhóm:** Vận hành.

Health monitor, restart worker có giới hạn, OOM backoff, hạ batch/context theo preset; không restart loop.

**Nghiệm thu:** Hai OOM liên tiếp dừng an toàn; không mất override; UI giải thích tình trạng GPU.

### FR-039 — Benchmark và diagnostic
**Nhóm:** Vận hành.

Chạy A/B local, kết quả latency/output/token/error; xuất gói diagnostic redacted có opt-in.

**Nghiệm thu:** Không gửi dữ liệu đi; chất lượng người chấm không bị thay bằng điểm tự chấm của model.

### FR-040 — Đóng gói/update/rollback
**Nhóm:** Vận hành.

Companion Windows per-user, extension build, pinned artifacts, kiểm checksum update, rollback app và DB tương thích.

**Nghiệm thu:** Cài trên tài khoản Windows sạch không cần cài Python toàn máy; gỡ cài đặt có chọn giữ/xóa model.

### FR-041 — Xác thực loopback
**Nhóm:** Bảo mật.

Origin/Host validation, token ngắn hạn, không token URL, giới hạn frame/file/text; backend không làm proxy tùy ý.

**Nghiệm thu:** Trang web thù địch/WS không auth bị chặn; endpoint không bind LAN.

### FR-042 — Không thực thi từ nội dung
**Nhóm:** Bảo mật.

Caption được coi là dữ liệu, escape HTML, tools disabled, subprocess argv cố định, không eval.

**Nghiệm thu:** Câu yêu cầu bỏ qua lệnh/chạy shell được dịch như nội dung, không được thực thi.

### FR-043 — Offline AI và quyền tối thiểu
**Nhóm:** Bảo mật.

Không telemetry cloud mặc định; chỉ tải model có đồng ý; manifest chỉ host YouTube/loopback cần thiết.

**Nghiệm thu:** Network audit tách YouTube browser traffic với AI worker egress; AI không gọi dịch vụ từ xa khi đang xem.

### FR-044 — Thông báo giấy phép
**Nhóm:** Bảo mật.

About/Notices ghi nguồn code/model/voices, quy tắc quyền video; không quảng cáo liên kết chính thức YouTube/Google/VieNeu.

**Nghiệm thu:** Bộ cài có SBOM/notices và checkbox hiểu phạm vi lưu/xuất nội dung.

### FR-045 — Bàn giao có bằng chứng
**Nhóm:** Chất lượng.

Traceability FR→test, báo cáo acceptance, benchmark cả đơn và đồng thời TTS, lỗi còn mở.

**Nghiệm thu:** Release bị chặn nếu có lỗi đảo nghĩa nghiêm trọng hoặc sai epoch/âm thanh vòng lặp.

## 7. Yêu cầu phi chức năng
Tất cả số dưới đây là **mục tiêu thiết kế phải đo**, không phải số đã đạt trên máy người dùng.

### NFR-01 — Đúng nghĩa
Không lỗi critical trên tập nghiệm thu do người chấm duyệt; đây là release gate chứ không phải bảo đảm mọi video.

### NFR-02 — Dịch tự nhiên
Điểm tự nhiên trung bình ≥4/5 và đầy đủ ý ≥4.5/5 trên holdout đã review; đánh giá mù.

### NFR-03 — Độ trễ dịch
Mục tiêu p95 ≤2.5s/cụm ≤60 từ nguồn, đã warm-up, context 4096, khi TTS cùng hoạt động; đo thật và chỉnh cấu hình trước release.

### NFR-04 — Độ trễ VOD
Mục tiêu warm first-ready ≤5s nếu caption phía trước có sẵn; cold-start báo riêng, không gồm download/model load vào số warm.

### NFR-05 — Thông lượng
Mục tiêu RTF toàn pipeline ≤0.6 ở video 1x; 2x cần ≤0.5 để theo kịp, dùng hold khi không đạt.

### NFR-06 — Stop latency
Mục tiêu p95 từ thao tác tắt/seek/pause đến stop audio ≤150ms; test foreground và background, stop tại consumer không chờ kernel hủy.

### NFR-07 — Đồng bộ VOD
Mục tiêu p95 sai lệch onset ≤350ms ở 1x, không tích lũy drift quá một câu; ghi riêng các lần auto-hold.

### NFR-08 — Dịch trực tiếp
Mục tiêu p95 từ cuối cụm nguồn đến âm Việt đầu ≤6s ở 1x; latency phụ thuộc commit/queue, không hứa hình–tiếng đồng bộ trong ASR live.

### NFR-09 — Tài nguyên
Điểm bắt đầu budget VRAM ≤9.5 GiB cho toàn app; RAM ≤16 GiB; cả hai phải đo, không suy từ model file.

### NFR-10 — Ổn định
Soak 2 giờ VOD và 30 phút ASR, không leak tăng liên tục, không sai video/epoch, không deadlock.

### NFR-11 — Độ tin cậy dữ liệu
SQLite transaction, migration có backup, atomic audio cache, unclean shutdown không hỏng DB.

### NFR-12 — Riêng tư
No AI cloud egress sau provisioning, no mic capture, no payload log mặc định, token không lưu trong page/storage sync.

### NFR-13 — Khả năng bảo trì
Adapter cho caption/model/TTS có version và contract test; không hard-code DOM selector khắp codebase.

### NFR-14 — Khả năng truy cập
Keyboard/focus, screen-reader label, reduced motion, font Việt; không dùng màu làm dấu hiệu duy nhất.

### NFR-15 — Tương thích
Windows 10/11 x64, Chrome stable thực tế tại release; baseline thiết kế Chrome ≥116 do capture flow; kiểm lại các API đã dùng.

### NFR-16 — Reproducible release
Lockfile, checkpoint hash, compiler/runtime build ID, SBOM, checksums của installer; không tự cập nhật model không kiểm thử.

### NFR-17 — Chất lượng audio
Không clipping rõ rệt, không đọc placeholder/JSON/reasoning, không đổi pitch do sample-rate mismatch; nghe thử bằng người.

### NFR-18 — Khôi phục
Mất WS báo trong khoảng 3s sau heartbeat thất bại; restart không auto phát bất ngờ; resumable download không làm mất bản model tốt trước đó.

## 8. Quy tắc ưu tiên chất lượng
Critical gồm đảo phủ định, sai điều kiện, sai số/đơn vị ảnh hưởng ý, thêm hành động không tồn tại, đọc nhầm đoạn/video. Một lỗi critical xác nhận trên bộ holdout chặn việc chọn model/prompt hiện tại. Không tăng điểm tự nhiên để bù critical. Mọi câu lỗi không thể sửa phải hiển thị và ngừng/hold đoạn tương ứng, không thay bằng câu bịa.

## 9. Thông số mặc định ban đầu
Context 4096 token; một yêu cầu dịch tại một thời điểm; nhóm tối đa 3 đơn vị, tổng ≤120 từ nguồn; một đơn vị tối đa 60 từ hoặc 12s trước khi tách tại ranh giới ý. Cửa sổ đọc trước 30s, low-water 8s, high-water 45s tính theo thời gian video có coverage; đổi tốc độ phải tính nhu cầu wall-time. TTS batch 1–2, tối đa 4 sau đo. Cache 2 GiB, TTL 14 ngày, lịch sử không bật mặc định. Mức audio gốc đề xuất 15%, tiếng Việt 100%, giữ muted do người dùng chọn. Live queue hard cap 30s audio đã commit; đầy thì báo và dừng an toàn.

## 10. Điều kiện bàn giao
Mỗi FR có test và chứng cứ. Cần ít nhất một bản cài trên máy Windows sạch, một phiên GPU thật, kiểm thử cùng VieNeu, chấm bản dịch tiếng Việt, thử mất phụ đề/quyền capture/seek/ad/sleep/wake, và network audit. Không coi all-unit-tests-pass là đã hoàn tất tích hợp YouTube. Không ký xác nhận độ chính xác tuyệt đối hoặc hỗ trợ mọi video.

## 11. Hồ sơ đầu ra
Mã nguồn extension/companion, bản build/installer, lockfile và model manifest có hash, SBOM/notices, báo cáo model A/B, báo cáo FR/NFR, video demo do đội triển khai tự ghi từ nguồn được phép, hướng dẫn sử dụng/khắc phục, danh sách lỗi còn mở. Thứ tự triển khai trong docs/15 là tích hợp từng phần, không thu hẹp phạm vi sản phẩm.
