# Kế hoạch triển khai đầy đủ cho Claude Code
## Quy tắc thực thi
Đọc CLAUDE.md và PRD trước. Lập `IMPLEMENTATION_STATUS.md` từ 45 FR/18 NFR, ban đầu NOT_STARTED; cập nhật bằng commit, test và evidence. Chia công việc dưới đây là thứ tự kỹ thuật, **không phải chia cắt phạm vi sang phiên bản khác**. Không kết thúc bằng một mock UI hoặc chỉ đọc SRT và gọi đó là sản phẩm hoàn chỉnh.

| Epic | Phụ thuộc | Đầu ra phải có | Cổng nghiệm thu |
|---|---|---|---|
| E01 Nền repo & contracts | Không | Monorepo, lint/typecheck/test, shared types, OpenAPI validators, errors | Schema/negative tests; secrets không commit |
| E02 Runtime & model manager | E01 | Python sidecars/llama build lock, downloads có consent/SHA/resume, import/unload | Corrupt/partial reject, Windows target smoke |
| E03 Dịch và A/B | E02 | Segmentation, glossary, context, JSON validation/repair, benchmark harness | Trước chọn final model có đánh giá đúng nghĩa/tự nhiên |
| E04 VieNeu thực | E02 | V3Turbo SDK worker, voice enumeration, infer/stream, warm-up/health | Audio48k đúng, giọng runtime, local network audit |
| E05 Broker/data/security | E01 | REST/WS/native framing, SQLite/cache/revision, auth/origin/rate | Contract+threat tests, crash-safe persist |
| E06 Chrome source/UX foundation | E01,E05 | Content/SPAnav, caption adapter, SRTVTT, panel/settings/onboarding | Coverage thực, token không lộ vào page |
| E07 Sync/audio hoàn chỉnh | E04,E05,E06 | Offscreen, clocks, output gain, seek/ad/rate/pause owner, DSP | SYS01–15; wrongepoch/echo không được tồn tại |
| E08 ASR/live | E05,E06,E07 | TabCapture,16k,VAD,commit/dedupe,delay/overflow UX | Nguồn thu gốc không lẫn TTS; live không drop âm thầm |
| E09 Học kỹ/biên tập/dữ liệu | E03,E07 | Song ngữ, nghe lại, override, glossary pronunciation, history/export/private | Editing invalidates đúng; export timeline nguồn |
| E10 Tích hợp tối ưu | E03,E04,E07,E08 | GPU scheduler, priorities/backpressure/OOM, diagnostics, all mode | Benchmark concurrent + 2h soak + NFR |
| E11 Đóng gói Windows | E02,E05,E10 | Peruser installer, bundled runtime, nativehost registry, update/rollback | Clean profile không cần global Python; uninstall rõ dữ liệu |
| E12 Acceptance/handoff | Tất cả | Coverage45FR18NFR, build artifacts, notices/SBOM, guide, report | Không fake PASS, all release gate được kiểm |

## Những phần phải làm đầu để tránh làm lại
Khóa timeline_epoch và revision trước viết scheduler. Tách DTO source/time khỏi output LLM. Capture graph tách source ASR và narration ngay từ đầu. Khởi động VieNeu và Qwen **đồng thời trên máy đích sớm**, không đợi UI xong mới phát hiện xung đột VRAM. Kiểm nhận caption thật và coverage trước tối ưu đọc trước. Cho Gemma dùng cùng adapter API, không code nhánh UI đặc biệt cho từng hãng.

## Cấu trúc mục tiêu
```text
apps/extension/          content, background, offscreen, sidepanel, settings
apps/companion/          tray, onboarding, native-host, launcher
services/broker/         sessions, API, cache, queues, security
services/translator/     llama adapter, prompts, validator, quality metadata
services/tts/            VieNeu worker và IPC
services/asr/            capture ingest, faster-whisper, stability/VAD
packages/contracts/     TypeScript/Python sinh/kiểm từ contracts hiện có
packages/audio/         frame codec, clock scheduler, time-stretch adapter
scripts/                build, pin, smoke, installer, diagnostics
tests/                  unit, contract, integration, e2e, fixtures
```
Đây là cấu trúc dự kiến để tạo, không phải các module đã tồn tại trong ZIP tài liệu.

## Mỗi phiên Claude Code
Đọc status → chọn công việc chưa hoàn tất có dependencies sẵn → triển khai thực → chạy test phù hợp → cập nhật status/evidence. Tool không truy cập được Chrome/GPU phải ghi chính xác giới hạn, vẫn hoàn thiện phần độc lập. Không tự công bố lên Chrome Web Store, push repo, mở firewall, xóa model/dữ liệu hoặc chạy installer toàn máy khi chưa được cho phép. Không cần hỏi lại lựa chọn cloud/offline/phần cứng đã ghi rõ.

## Definition of Done
Source + lockfiles build tái lập; ứng dụng thực đạt FR; source/voice/model license notices; seed và realholdout review; plugin/audio/capture hoạt động không dựa mock; hướng dẫn người dùng tiếng Việt; benchmark đủ tải; test report/known limitations. Chủ sản phẩm nhận extension build và companion installer, không phải chỉ hướng dẫn cài Python thủ công.
