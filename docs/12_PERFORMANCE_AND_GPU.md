# Hiệu năng và GPU

## Không đánh đồng cỡ file với bộ nhớ
Qwen Q5 3,14 GB và Gemma E4B 5,15 GB là tệp weights [S02][S05]. Khi chạy còn KV/recurrent state, compute buffers, CUDA graph/runtime, Chrome render/video decode và VieNeu. PLE placement/offload tùy runtime; không tự suy VRAM resident từ effective parameters. Đo nvidia-smi/NVML và process RAM thực.

## Preset đích
Máy RTX 3060 12 GB, RAM32; chỉ một model dịch loaded, context4096, llama parallel1, token max512/nhóm nhỏ, TTS batch1–2. Budget khởi điểm toàn app VRAM≤9.5GiB và RAM≤16GiB, chừa headroom cho Windows/Chrome; đây là mục tiêu chứ không cam kết. Không huấn luyện/benchmark nền khi đang xem. Unity/Blender/Hermes có thể dùng cùng GPU: diagnostics phải thấy VRAM còn, không chỉ tên GPU.

## Thứ tự ưu tiên và bộ đệm
Audio consumer deadline > TTS cần nghe gần > dịch gần playhead > prefetch xa > preview/benchmark. Inference translator serial. TTS microbatch chỉ units đã commit có cùng deadline phù hợp; không batch32 để chase throughput benchmark. Prefetch target30s, low8s, high45s có coverage; giữ completed audio không phải 45s model requests bất kể nguồn.

## Phép đo phải ghi
Hardware/driver/OS/Chrome/runtime SHA/model SHA/prompt/sampling/threads/GPU offload/context; load_ms, warmup_ms, queue_ms, TTFT nếu stream model đo được, translation_complete_ms, TTS first/chunk/complete, audio_start_lag, cancellation_ack; peak GPU used/CPU RSS, error count. Chỉ số helper bench hiện có đo request complete latency, không gọi đó là TTFT.

Có bốn phép chạy: model đơn; model + TTS workload lặp cố định; model + TTS + ASR CPU; video tích hợp. Warm-up2 lần, test ít nhất3 lượt, thứ tự model xen kẽ để giảm bias nhiệt/GPU clocks. Cold-load một lần riêng, không lẫn download. ASR mặc định CPU int8; GPU ASR thử tùy ngân sách và runtime, không nạp sẵn ở caption mode [S23].

## RTF và tốc độ xem
RTF=wall processing time/source media duration cho cửa sổ pipeline, đo cả queue/wait cần thiết và ghi định nghĩa. Ở 1x cần dưới1 để không tụt; mục tiêu≤0.6 tạo dự phòng. Ở2x phải dưới0.5 để theo kịp, nếu không thì auto-hold/VOD hoặc live overflow handling. TTS RTF riêng audio duration không bằng pipeline RTF source duration. Không cộng throughput tokens/s thành số đo chất lượng.

## OOM ladder
Dừng prefetch mới → giảm TTS batch xuống1 và giới hạn graph shapes → giảm llama context đã vượt mức cần → unload ASR GPU/đưa ASR CPU nếu đã cấu hình → đề nghị Qwen Q4 đã tải hoặc Turbo CPU. Mỗi bước có rewarm và report. Không tự tải model khác, không đổi giọng, không bỏ câu. Kernel fail/worker crash: restart≤1 lần với cooldown; nếu lặp lại dừng an toàn, UI cho người dùng giải phóng GPU.

## Cổng hiệu năng
NFR trong PRD là mục tiêu; không thay số target thành measured. Model không qua quality dù nhanh vẫn loại. Nếu hardware target chưa test thì report NOT_RUN, không release-ready. Phải thử fullscreen, video1080p, browser background, Windows sleep/wake và một ứng dụng GPU cùng mở; chế độ cạnh tranh cho phép báo giới hạn thay vì crash.
