# Kết quả đo thật — VietDub Local 0.1.0 (2026-09-23)

**Máy đo:** Windows 10 Pro x64, RTX 3060 12 GB (driver 616.92), i9-11900K, 32 GB RAM.
**Runtime:** llama.cpp b11126 CUDA 13.4, Qwen3.5-4B Q5_K_M (rev e87f1764, ctx 4096, `--reasoning off`), VieNeu v3 Turbo 3.8.1 (torch 2.8.0+cu128), faster-whisper small.en CPU int8.

**Chất lượng dịch: CHƯA NGƯỜI CHẤM (NOT_REVIEWED).** Mọi con số dưới đây chỉ đo cấu trúc, độ trễ và tài nguyên, không đo đúng nghĩa. Mô hình không được dùng để tự chấm chính nó (docs/13). Phiếu chấm tay có sẵn tại `benchmarks/human_review.template.csv`.

| Đo | Tệp | Kết quả | So với mục tiêu PRD |
|---|---|---|---|
| Tải A: Qwen dịch một mình, 80 câu seed × 3 lượt | `qwen_q5_A_alone/summary.json` | 240/240 JSON hợp lệ; p50 739 ms, p95 1071 ms / cụm | NFR-03 p95 ≤ 2,5 s: **đạt** |
| Tải B: Qwen dịch **cùng lúc** VieNeu đọc liên tục | `load-b-20260923T220051.json` | 80/80 hợp lệ; p50 945 ms, p95 1499 ms; 139 lần TTS; VRAM đỉnh toàn GPU 5257 MB | NFR-03 **đạt**; NFR-09 VRAM ≤ 9,5 GiB **đạt** |
| TTS VieNeu (test tích hợp) | `tests/python/test_tts_worker_integration.py` | 0,25 s tạo 2,24 s âm thanh (RTF ≈ 0,11) | NFR-05 RTF ≤ 0,6: **đạt** (riêng TTS) |
| ASR trực tiếp (live_delayed, fixture 17 câu) | `D:/VietDubLocal/e2e/live-asr-20260923T231555.json` | Từ cuối câu nguồn tới tiếng Việt đầu tiên: p50 2,24 s, p95 3,57 s; 0 câu lặp; 17/17 câu có tiếng | NFR-08 p95 ≤ 6 s: **đạt**. ASR có nghe sai (ví dụ "weights" thành "waits") |
| E2E trình duyệt (Chrome thật, YouTube giả lập) | `D:/VietDubLocal/e2e/fake-*/report.json` | Tắt/tua/dừng: im tiếng ≤ 150 ms; sai lệch mốc neo p95 7–10 ms; phụ đề sẵn sau 2,3 s | NFR-06 **đạt** (foreground). NFR-07: mới đo mốc neo đồng hồ, chưa đo onset từng câu bằng micro |
| Kiểm mạng khi AI chạy | `network-audit-20260923T231640.json` | 466 mẫu, 2505 kết nối, 0 kết nối ngoài loopback; chỉ nghe 127.0.0.1:8765/8766 | NFR-12 / AT-043: **đạt** |
| Soak ngắn 20 phút (broker + GPU, client giả lập) | `soak-20260923T233834.json` | 0 lỗi, không leak tăng liên tục, VRAM ổn định | NFR-10 yêu cầu 2 giờ VOD + 30 phút ASR: **chưa đạt thời lượng** |

## Soak

`soak-20260923T233834.json` — 20 phút, broker + Qwen + VieNeu GPU thật, client giả lập offscreen (không phải Chrome):
- 287 câu, 278 câu dịch xong, 337 lần phát xong, 6 lần tua; **0 lỗi, 0 câu bị chặn, 0 khung âm thanh epoch cũ sau tua**; trạng thái luôn PLAYING.
- RSS broker + llama-server + worker: 7,5 GB → đỉnh 8,4 GB (phút 6) → 6,9 GB cuối: **không tăng liên tục**. VRAM toàn GPU 5,0–5,2 GB.
- TTS p50 439 ms / p95 869 ms mỗi câu. **Hạn chế:** 80 câu mẫu lặp lại sau khoảng 6 phút nên nửa sau phần lớn trúng cache (212 lần), GPU làm ít hơn video thật.
- Warm first-ready (câu mới, không cache): tiếng Việt đầu tiên 3,19–3,51 s (5 lần) — NFR-04 ≤ 5 s **đạt**.

## Chưa đo
- Chất lượng dịch có người chấm (NFR-01, NFR-02): **BLOCKED**, cần người chấm.
- Soak 2 giờ VOD và 30 phút ASR (NFR-10).
- Gemma 4 E4B/E2B và Qwen Q4: chưa tải (theo lựa chọn của user), nên chưa có so sánh A/B.
- Onset từng câu so với video bằng thu âm thật (NFR-07).
