# Quy trình chọn model bằng dịch thật
## Mục đích và trạng thái
So sánh checkpoint + quant + template + prompt cụ thể, không xếp hạng tên hãng. Qwen Q5 là quyết định khởi đầu; kết quả hiện tại **NOT_RUN**. Những nguồn [S01–S06] xác nhận artifact/tài liệu, không chứng minh bên nào thắng phụ đề Anh–Việt.

`benchmarks/seed_envi.jsonl` có 80 mẫu tự biên soạn, chia dev/test mỗi loại 40 câu theo domain. Các câu Việt là đáp án gợi ý **assistant_authored_unreviewed**, chưa là gold standard. Không lấy mẫu sinh này làm bằng chứng chất lượng thực tế hoặc chỉ số thị trường. Không đưa `reference_vi`, `must_preserve_meaning_vi`, `review_notes` vào input model. Script đã tách riêng các trường này.

Trước gate phát hành: người giỏi Anh–Việt duyệt các câu kiểm thử và bổ sung tối thiểu 200 đơn vị phụ đề từ video được phép dùng, theo dạng nội dung người dùng thực sự xem. Sếp đánh giá mức dễ hiểu/dễ nghe của tiếng Việt; không bắt Sếp tự xác nhận nghĩa tiếng Anh. Có ít nhất 50 đoạn nguồn bị cắt/thiếu dấu, 30 câu có phủ định/điều kiện, 30 câu có thuật ngữ/số (có thể chồng nhóm). Không công bố lại transcript có bản quyền nếu chưa có quyền.

## Thí nghiệm
| Trục | Cách thực hiện |
|---|---|
| Model | Qwen Q5, Qwen Q4, Gemma E4B QAT; E2B tùy chọn |
| Prompt | Cùng logic, cùng source/context/glossary; native template đúng từng họ |
| Sampling | Baseline theo model trước; tuning low-temperature chỉ trên dev; ghi tất cả thông số |
| Cache | Tắt cache dịch ở lượt đo; ghi prompt cache của runtime; thứ tự ngẫu nhiên có seed |
| Phần cứng | Ghi CPU/GPU/driver/RAM/OS/Chrome/runtime build/SHA/model SHA |
| Tải máy | A: model riêng; B: model + VieNeu cùng chạy; C: thêm ASR CPU; D: video tích hợp |
| Lần chạy | Warm-up 2 câu; ≥3 lượt, đảo thứ tự model giữa các lượt; cold-load riêng |
| Dữ liệu | Dev để sửa; test đã khóa không dùng tune; tập video holdout mới cho nghiệm thu |

Đo latency request hoàn tất, tokens nếu server cung cấp, lỗi cấu trúc và số repair; helper hiện tại **không đo TTFT, VRAM, chất lượng người chấm hoặc TTS**. Các phép đó do harness tích hợp và người chấm bổ sung. Một HTTP lỗi không được loại khỏi tỷ lệ lỗi để làm p95 đẹp hơn; công bố tổng số, số thành công/thất bại và latency có điều kiện trên thành công.

## Rubric người chấm (mù tên model)
- **Đầy đủ và đúng nghĩa (0–5):** 5 giữ đủ ý/điều kiện; 4 lỗi nhẹ không đổi cách hiểu; 3 bỏ/sai ý đáng chú ý; 2 sai nhiều; 1 phần lớn sai; 0 rỗng/không dịch. Mức 4 không được dùng che một lỗi critical.
- **Tự nhiên tiếng Việt (0–5):** 5 như lời hướng dẫn tự nhiên; 4 hơi cứng nhưng dễ nghe; 3 phải đọc lại; 2 khó hiểu; 1 gần vô nghĩa; 0 không có bản Việt hợp lệ.
- **Thuật ngữ (0–5 hoặc N/A):** giữ đúng tên nút/code và nghĩa chuyên ngành trong ngữ cảnh. Không phạt tên tiếng Anh cố ý giữ.
- **Critical error (true/false):** đảo phủ định, mất điều kiện quan trọng, sai số/đơn vị làm đổi hành động, biến giả định thành khẳng định, bịa lời không có trong nguồn. Ghi span nguồn và giải thích, không chỉ chấm điểm.

Chấm riêng bản hiển thị và nghe bản VieNeu của cùng câu. Lỗi phát âm giọng đọc không tự quy là lỗi dịch. Đối chiếu nghe cần cùng voice và cấu hình TTS. Có thể dùng chrF/COMET bổ sung khi đã chọn dependency/license, nhưng không có score tự động nào thay người duyệt ý nghĩa. Không lấy một reference duy nhất để cấm cách diễn đạt Việt đúng khác.

## Ra quyết định
Điều kiện bắt buộc: không có lỗi critical đã xác nhận trong tập gate; adequacy ≥4.5/5, naturalness ≥4/5; cấu trúc/placeholder không lỗi chưa xử lý; NFR về độ trễ/tài nguyên trên phần cứng đích đạt. Các ngưỡng là yêu cầu dự án, không phải kết quả.

Gemma trở thành mặc định nếu hơn ≥0.25/5 naturalness, adequacy không giảm, paired review xác nhận khác biệt hữu ích và đạt ngân sách. Đây là ngưỡng thực dụng nội bộ, không tự chứng minh ý nghĩa thống kê. Báo khoảng biến thiên qua lượt/người chấm; không kết luận chắc nếu còn bất đồng. Nếu hòa chọn model đạt chất lượng với tài nguyên/latency tốt hơn thực đo; nếu Q4 tương đương Q5, dùng Q4. Không sửa gate âm thầm để hợp thức hóa model mặc định.

## Cách chạy helper
Từ thư mục gốc, sau khi **đã** khởi động llama-server local có xác thực và model tương ứng:
```powershell
$env:VIETDUB_LLM_KEY = Read-Host 'Nhập khóa local của llama-server'
python tools/benchmark_translation.py --model qwen35_4b_q5 --profile qwen_non_thinking --out benchmarks/results/qwen_q5
# Dừng/unload Qwen, khởi động cùng runtime với Gemma rồi chạy:
python tools/benchmark_translation.py --model gemma4_e4b_qat --profile gemma_non_thinking --out benchmarks/results/gemma_e4b
python tools/make_blind_review.py --run-a benchmarks/results/qwen_q5/results.jsonl --run-b benchmarks/results/gemma_e4b/results.jsonl --out benchmarks/results/blind
Remove-Item Env:VIETDUB_LLM_KEY
```
Khóa là bí mật cục bộ, không phải khóa OpenAI/cloud; không dán vào chat. Dùng khóa test ngắn hạn rồi xoay sau benchmark; không dùng transcript riêng tư trong seed test. Script chỉ cho IP loopback và không theo redirect/proxy. Tên `--model` phải khớp alias server; không làm server tải model từ tên đó. `--dry-run` kiểm request, không sinh kết quả model.

`review.csv` để người chấm điền; `review_key.json` phải giấu khỏi reviewer đến khi chấm xong. Trường điểm ban đầu trống. Trước phát hành tạo `model-selection-report.md` ghi kết luận, dữ liệu, người duyệt, đo máy, exceptions và cập nhật ADR-001/config. Không nộp results của HTTP mock làm kết quả model thật.
