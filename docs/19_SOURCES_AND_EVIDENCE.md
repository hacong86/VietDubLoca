# Nguồn, bằng chứng và giới hạn kiểm chứng
Ngày đối chiếu: **23/09/2026**. Mọi số dung lượng bên dưới là GB thập phân làm tròn của tệp, **không phải VRAM đo được**.

Bộ tài liệu là đặc tả do trợ lý thiết kế, không phải phần mềm đã hoàn thành. Chưa tải trọng số, chưa chạy benchmark dịch/TTS/GPU trên máy của Sếp. Trong môi trường tạo tài liệu đã kiểm tra được cấu trúc tệp và các công cụ phụ trợ; kết quả thực tế được ghi riêng trong DELIVERY_VALIDATION.md.

Các con số buffer/latency/quality trong PRD là mục tiêu nghiệm thu do dự án đặt ra, không phải số nhà sản xuất đã chứng minh cho toàn chuỗi. Không có bảng thắng–thua Anh→Việt đáng tin cậy cho đúng các checkpoint/quantization đang so sánh trong những nguồn đã đọc. Benchmark toán, code, đa ngôn ngữ tổng quát hoặc dịch từ audio không thay thế kiểm thử phụ đề.

## Danh mục
### S01 — Gemma 4 model card — Google
Nguồn: https://ai.google.dev/gemma/docs/core/model_card_4

Dùng để xác minh: Kích thước effective/total, khả năng, benchmark tổng quát; không có đối chứng phụ đề Anh–Việt trên RTX 3060.

### S02 — Gemma 4 E4B QAT GGUF — Google
Nguồn: https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-gguf/tree/main

Dùng để xác minh: Tệp text gemma-4-E4B_q4_0-it.gguf khoảng 5,15 GB; mmproj riêng khoảng 992 MB; QAT do Google phát hành.

### S03 — Gemma 4 E2B QAT GGUF — Google
Nguồn: https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf/tree/main

Dùng để xác minh: Tệp text khoảng 3,35 GB; không phải 2 GB chỉ vì tên E2B.

### S04 — Qwen3.5-4B — tác giả Qwen
Nguồn: https://huggingface.co/Qwen/Qwen3.5-4B

Dùng để xác minh: Mô hình gốc, chat template, chế độ không thinking, cấu hình sampling tham khảo.

### S05 — Qwen3.5-4B GGUF — nhà chuyển đổi Unsloth
Nguồn: https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/tree/main

Dùng để xác minh: Q4_K_M khoảng 2,74 GB; Q5_K_M khoảng 3,14 GB. Đây là bản chuyển đổi của Unsloth, không phải kho GGUF do Qwen phát hành.

### S06 — Danh mục chính thức Qwen
Nguồn: https://huggingface.co/Qwen

Dùng để xác minh: Đã có các bản Qwen3.8 lớn; không gọi Qwen3.5 là thế hệ mới nhất. Bản được chọn vì ngân sách máy.

### S07 — VieNeu — SDK overview
Nguồn: https://docs.vieneu.io/docs/sdk/overview/

Dùng để xác minh: Nhánh on-device v3 Turbo, đọc giọng, danh sách giọng; tài liệu dẫn README khi có bất đồng.

### S08 — VieNeu — Install & backends
Nguồn: https://docs.vieneu.io/docs/sdk/standard-mode/

Dùng để xác minh: Hướng dẫn Windows CUDA và phiên bản torch/transformers; CPU ONNX; Nano khác Turbo.

### S09 — VieNeu — Streaming
Nguồn: https://docs.vieneu.io/docs/sdk/streaming/

Dùng để xác minh: Turbo trả float32 mono 48 kHz; Nano không frame-stream; adapter phải giữ định dạng.

### S10 — VieNeu — local compatible server
Nguồn: https://docs.vieneu.io/docs/sdk/remote-mode/

Dùng để xác minh: Giao thức TTS cục bộ; không nhầm với API cloud v4 hoặc remote mode v2 legacy.

### S11 — VieNeu — mã nguồn chính thức
Nguồn: https://github.com/pnnbao97/VieNeu-TTS

Dùng để xác minh: v3 Turbo là nhánh mở; v4 cloud độc quyền; style deprecated; cập nhật SDK/giọng.

### S12 — VieNeu Turbo — model card và quyền sử dụng
Nguồn: https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Turbo

Dùng để xác minh: Apache-2.0; FAQ tác giả về preset voices và audio; không suy rộng quyền clone giọng người khác.

### S13 — VieNeu — PyPI
Nguồn: https://pypi.org/project/vieneu/

Dùng để xác minh: Ngày tra cứu: phiên bản 3.8.1, Python >=3.10. Phiên bản SDK không phải phiên bản model.

### S14 — llama.cpp — server README
Nguồn: https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/server/README.md

Dùng để xác minh: Loopback server, auth, Jinja, disabling reasoning, JSON output. Cần pin build đã qua smoke test.

### S15 — Chrome — audio recording/screen capture
Nguồn: https://developer.chrome.com/docs/extensions/how-to/web-platform/screen-capture

Dùng để xác minh: Đường service worker → offscreen; không đặt phiên audio trong popup.

### S16 — Chrome — offscreen API
Nguồn: https://developer.chrome.com/docs/extensions/reference/api/offscreen

Dùng để xác minh: Quyền, reasons, lifecycle, các giới hạn API trong offscreen.

### S17 — Chrome — tabCapture API
Nguồn: https://developer.chrome.com/docs/extensions/reference/api/tabCapture

Dùng để xác minh: Cần thao tác người dùng; bắt tab audio và khôi phục đường phát gốc.

### S18 — Chrome — Native Messaging
Nguồn: https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging

Dùng để xác minh: Native host Windows, framing JSON, allowed_origins.

### S19 — Chrome — network requests
Nguồn: https://developer.chrome.com/docs/extensions/develop/concepts/network-requests

Dùng để xác minh: Host permissions, trust boundary; không làm proxy URL tùy ý.

### S20 — Chrome — service worker lifecycle
Nguồn: https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle

Dùng để xác minh: Worker có thể bị kết thúc; trạng thái phiên không chỉ nằm trong RAM worker.

### S21 — YouTube Data API — captions.download
Nguồn: https://developers.google.com/youtube/v3/docs/captions/download

Dùng để xác minh: Tải caption chính thức yêu cầu quyền chỉnh sửa video; không phải API-key tải mọi caption công khai.

### S22 — YouTube Help — transcripts
Nguồn: https://support.google.com/youtube/answer/15930243?hl=en

Dùng để xác minh: Video có caption có thể có giao diện transcript cho người dùng; không bảo đảm API ổn định.

### S23 — faster-whisper — SYSTRAN
Nguồn: https://github.com/SYSTRAN/faster-whisper

Dùng để xác minh: ASR CTranslate2, CPU int8/GPU; phiên bản CUDA/cuDNN phải kiểm thử riêng.

## Quy tắc trích dẫn trong repo
[Sxx] dẫn đến mục tương ứng tại tệp này. Với mỗi bản release, lưu URL, ngày truy cập, checkpoint revision, SHA-256 của tệp thật đã tải, phiên bản runtime và giấy phép. Không dùng riêng nhánh `main` làm khóa phát hành. Các trường chưa xác minh phải để null, không tạo hash giả.

## Phân biệt chứng cứ
- **Đã kiểm tra từ nguồn:** artifact có tồn tại, dung lượng tệp, tham số/giấy phép tự công bố, giao thức tài liệu mô tả.
- **Quyết định thiết kế:** Qwen Q5 mặc định ban đầu, quy trình dịch, port, quota bộ đệm, schema, UX, tiêu chí nghiệm thu.
- **Chưa đo:** model nào dịch tự nhiên nhất trên nội dung của Sếp, VRAM peak, tốc độ khi đồng thời chạy các tác vụ khác, độ ổn định Chrome/Windows.
- **Không khẳng định:** mọi video lấy được transcript; dịch trực tiếp không trễ; tổng hệ thống chỉ trễ bằng TTFA của VieNeu; GPU 12 GB luôn đủ bất kể context/batch/ứng dụng khác.
