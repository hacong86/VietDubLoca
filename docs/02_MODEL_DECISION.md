# Quyết định model dịch — ADR-001
Ngày đối chiếu 23/09/2026. Đích: phụ đề tiếng Anh → tiếng Việt tự nhiên, đầy đủ, nhẹ khi dùng chung RTX 3060 12 GB với VieNeu.

## Bảng đối chiếu có bằng chứng
| Ứng viên | Artifact text chọn | Cỡ tệp xấp xỉ | Vai trò |
|---|---|---:|---|
| Qwen3.5-4B | Unsloth Q5_K_M | 3,14 GB | Mặc định khởi đầu, cân bằng dung lượng và mức lượng tử hóa |
| Qwen3.5-4B | Unsloth Q4_K_M | 2,74 GB | Preset nhẹ/đối chứng với Q5 |
| Gemma 4 E4B | Google QAT Q4_0 | 5,15 GB | Đối chứng chất lượng, có thể được chọn làm mặc định sau đo |
| Gemma 4 E2B | Google QAT Q4_0 | 3,35 GB | Thử tùy chọn khi cần hiệu suất; không mặc định chỉ vì tên E2B |

Nguồn: [S02][S03][S05]. Không tính projector vì bài toán text-only. Không tải cả repository chứa mọi quant. Qwen quant là bản chuyển đổi Unsloth; cần giữ cả nguồn model gốc [S04] và nguồn artifact [S05]. Dung lượng chưa bao gồm KV cache, compute buffers, CUDA runtime và TTS.

## Điều dễ nhầm
Gemma E4B có 4,5B effective nhưng khoảng 8B tính cả embedding; E2B khoảng 5,1B tổng/2,3B effective [S01]. Không so chữ “4B” và “E4B” rồi suy cùng bộ nhớ. Gemma 26B A4B không phải model chỉ lưu 4B weights; không chọn cho ngân sách này. Qwen đã có thế hệ mới hơn dạng lớn [S06]; Qwen3.5-4B được chọn theo cấu hình, không được giới thiệu là model Qwen mới nhất.

## Kết luận triển khai
Chọn **Qwen3.5-4B Q5_K_M** làm cấu hình ban đầu. Nó chỉ lớn hơn bản Q4 khoảng 0,40 GB theo số tệp niêm yết, vẫn gọn hơn E4B; việc Q5 có giữ chất lượng dịch tốt hơn Q4 phải đo, không giả định là chắc chắn. Preset Q4 vẫn có đầy đủ chức năng, chỉ khác runtime/model artifact.

Không đủ bằng chứng để khẳng định Qwen hay Gemma dịch EN→VI chính xác/tự nhiên hơn cho các video của Sếp. Model card tổng quát không có trận so sánh đúng checkpoint, quant và pipeline này. Vì vậy thiết kế đã có cổng A/B; việc “chưa có kết quả” không ngăn triển khai sản phẩm.

## Cổng chọn model cuối
1. Mỗi model phải qua structural/placeholder/thinking checks và không có critical semantic error đã xác nhận trên holdout.
2. Chấm mù adequacy, naturalness, terminology bằng người; xuất điểm rời và các lỗi, không để model tự chấm thay người.
3. So paired outputs trên cùng câu, cùng context; đo p50/p95, peak RAM/VRAM, errors, cold và warm tách riêng.
4. Nếu Gemma tốt hơn có ý nghĩa thực tế (mục tiêu dự án: hơn ≥0,25/5 naturalness trong khi adequacy không giảm, người chấm xác nhận) và qua NFR, đổi default sang Gemma bằng config/ADR. Con số 0,25 là ngưỡng nội bộ, không phải kết quả đo hay bằng chứng thống kê.
5. Nếu không có khác biệt rõ, giữ model qua quality gate mà dùng ít tài nguyên/latency hơn. Nếu Q5 và Q4 tương đương về lỗi/điểm, chọn Q4. Nếu mọi model thất bại, sửa segmentation/prompt/glossary hoặc thử quant cao hơn trong ngân sách; không phát hành giả vờ đạt.

## Cấu hình thí nghiệm
Text only; context 4096; batch/parallel 1; max output 512 cho nhóm nhỏ, tăng có giới hạn khi bị truncation; fixed seed nếu runtime hỗ trợ. Không yêu cầu reasoning. Qwen kiểm chat_template_kwargs.enable_thinking=false; Gemma dùng template đúng và không đưa <|think|> vào system prompt [S01][S04][S14]. Không chỉ xóa reasoning sau sinh rồi coi đã tắt chi phí thinking.

Sampling baseline theo tài liệu model: Qwen non-thinking temperature 0.7/top_p 0.8/top_k 20; Gemma 1.0/0.95/64 [S01][S04]. Dự án có thể thử low-temperature 0.2/0.9 trên dev split, nhưng đó là thử nghiệm khác và phải ghi nhãn; không ép mọi model cùng thông số rồi tuyên bố so sánh công bằng. Chỉ chốt preset qua benchmark.

## Provenance và license
Model gốc Qwen và Gemma4 công bố Apache-2.0 [S01][S04]; bản quant phải giữ notices và SHA/revision. Không dùng tên “Google” để ngụ ý xác nhận chất lượng tiếng Việt hoặc liên kết thương mại. Không cần fine-tune ngay; chỉ cân nhắc sau khi lỗi đã phân loại và prompt/segmentation không giải quyết được.

Chi tiết: docs/13_BENCHMARK_PROTOCOL.md; kết quả điền sau tại benchmarks/results/, không chứa số giả trong bộ bàn giao này.
