# Rủi ro và nhật ký quyết định
| ID | Rủi ro | Kiểm soát | Bằng chứng đóng |
|---|---|---|---|
| R01 | Không biết model nào dịch hay hơn đúng bài toán | A/B checkpoint/quant, human review, config switch | Report13 và holdout |
| R02 | Caption YouTube thay DOM/không lấy được future | Adapter version, coverage, import/ASR fallback | Test nguồn thật manual/auto/none |
| R03 | Gemma effective parameter bị hiểu là size resident | Artifact + peak VRAM thực | Model load report |
| R04 | Qwen thinking làm chậm hoặc rò vào tiếng đọc | Native template, disable, validate, reject | LLM integration smoke |
| R05 | GPU chung VieNeu/LLM/Unity thiếu bộ nhớ | Scheduler/headroom/OOMbounded, Q4 lựa chọn | Concurrent test |
| R06 | Python/CUDA deps xung đột | Sidecars và venv riêng, pin build thật | Clean Windows run |
| R07 | TTS self-capture gây vòng lặp | Audio ngoài captured tab, split gain | Audio loopback E2E |
| R08 | Tua/chuyển video còn nói câu cũ | Epoch/revision guard ở producer và consumer | Race tests |
| R09 | LLM dịch mất phủ định/cảnh báo | Context + validator + human gate | Criticalerror ledger |
| R10 | VOD clock drift/speed pitch | Anchored media clock, DSP, bounded schedule | Sync measurements |
| R11 | Live quá tải bỏ câu âm thầm | Hữu hạn queue, visible interruption | Overflow test |
| R12 | Caption truy cập local service/exfiltrate | Host/Origin/token/limits/no tool execution | Threat suite |
| R13 | Dùng quyền giọng/model suy sang video | Notices, percontent rights, không exportvideo | License review |
| R14 | Dữ liệu riêng tư trong cache/log | Optin history, privateRAM, redact/erase | Disk/network audit |
| R15 | Installer update phá runtime/DB | Versioned install, healthrollback/backup | Upgrade/downgrade test |

## ADR đã quyết định
ADR-001 QwenQ5 default **ban đầu**, Q4 nhẹ, GemmaE4B đối chứng. Không có kết luận chất lượng đã đo.
ADR-002 LocalAI endtoend: llama.cpp + VieNeu + ASR; không Chrome Translator/cloud.
ADR-003 Ưu tiên caption đủ nghĩa/future; ASR là đường dự phòng luôn có chức năng.
ADR-004 Offscreen audio, serviceworker điều phối, Native Messaging bootstrap; không audio engine trong popup.
ADR-005 SDK VieNeu v3Turbo/3.8.1 baseline, không v4cloud, không style param đã bỏ.
ADR-006 Timestamp không do LLM sinh; epoch+revision bắt buộc, src clock là mốc.
ADR-007 API/WS loopbackauth, token không URL/page, no proxy arbitraryURLs.
ADR-008 Từng câu VOD có duration biết trước; live stream chỉ committed translations.
ADR-009 Toàn bộ45FR trong phạm vi, milestone không là lý do bỏ tính năng.

## Điểm phải chốt bằng kiểm thử trong triển khai
Runtime llama build/SHA/modelSHA; exact ASR/pip/node lock; model thắng holdout; final sampling; DSP time-stretch implementation/license; installer packaging strategy; thực tế caption source selectors. Các điểm này có owner: Claude Code triển khai và ghi evidence; người dùng duyệt trải nghiệm/những tác động dữ liệu. Không phải lý do để hỏi lại yêu cầu nền tảng hoặc giảm phạm vi.

## Quy tắc dừng an toàn
Đầu ra sai ID/placeholder/format sau repair, nguồn/timeline chưa rõ, epoch mismatch, audio channel/rate sai, nguồn mic không được phép, auth fail, queue live vượt ngưỡng, OOM liên tục → dừng phần bị ảnh hưởng và hiện lý do. Không phát nội dung “gần đúng” để che lỗi. Không khẳng định kiểm định tự động phát hiện được mọi sai nghĩa; người xem luôn có quyền tắt/xem nguồn/sửa.
