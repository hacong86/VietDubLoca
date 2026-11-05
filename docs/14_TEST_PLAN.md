# Kế hoạch kiểm thử và nghiệm thu
## Các lớp
1. Unit: parse SRT/VTT, rolling dedupe, unit grouping, placeholder, term boundary, numeric normalization, cache keys, clock mapping, epoch/revision guard, volume ownership.
2. Contract: JSON Schema/OpenAPI, REST/WS envelope, byte framing, giới hạn payload, token/origin, lỗi có mã ổn định. Test cả field không biết, duplicate ID, timestamp ngược, body quá lớn, MIME sai.
3. Worker integration: llama native template/thinking/schema, VieNeu list/infer/stream/48k, ASR VAD+commit, scheduler/OOM/health restart. Không mock đường này khi nghiệm thu.
4. Browser integration: extension MV3 thật, offscreen, tabCapture permission, Native Messaging, page↔content trust boundary, side panel, audio graph. Không suy test trang DOM đơn giản là YouTube đã chạy.
5. E2E: 45 FR ở `tests/acceptance-cases.csv`; benchmark ở tài liệu 13; ma trận kỹ thuật bên dưới.

## Ma trận phần cứng/trình duyệt
Máy đích chính Windows10 Pro x64/i9-11900K/32GB/RTX3060 12GB; thêm Windows11 x64. Chrome Stable thực cài ghi đầy đủ build và ngày test; minimum API architecture116 không đồng nghĩa khuyến nghị cài Chrome cũ. Extension unpacked cho dev; package release cài trên user profile sạch; không dựa profile đã có quyền/model. Tài khoản YouTube đăng nhập/không; caption manual/auto/absent/partial; network chậm/ngắt lại; full screen/theater/Shorts; 0.75x/1x/1.5x/2x; tab foreground/background. Mỗi môi trường chưa chạy ghi NOT_RUN.

## Kịch bản hệ thống bắt buộc
| ID | Kịch bản | Kết quả đúng |
|---|---|---|
| SYS-01 | Đang đọc, tua 02:00→10:00→01:00 nhanh | Epoch cuối thắng; không phát một sample của job cũ sau stop deadline |
| SYS-02 | LLM cũ hoàn tất sau chuyển video | Kết quả loại, không cache sai source/video; không TTS |
| SYS-03 | Người dùng pause khi auto-hold đang chờ | Không tự play dù buffer sẵn |
| SYS-04 | Quảng cáo giữa video/nguồn timeline không rõ | Hold tiếng Việt, tiếng quảng cáo gốc bình thường, re-anchor content |
| SYS-05 | Narration to nhưng tiếng gốc bằng0 | ASR vẫn nghe source; không nhận lại tiếng Việt |
| SYS-06 | Cùng transcript text nhưng context khác | Cache key khác; không dùng nhầm bản dịch |
| SYS-07 | Voice/model/glossary/override đổi | Invalidate đúng lớp, không xóa nguồn không liên quan |
| SYS-08 | Đổi 1x→2x giữa câu | Không đổi cao độ kiểu giọng sóc; dừng/re-anchor an toàn |
| SYS-09 | VOD có caption future bị mất nguồn | Không giả vờ buffer còn; chuyển trạng thái có chỉ báo |
| SYS-10 | Live dịch chậm, vượt queue cap | Không drop âm thầm, dừng/báo và cho chọn nối lại |
| SYS-11 | Worker bị kill/GPU OOM2lần | Bounded retry, không restart loop, bảo toàn override |
| SYS-12 | Companion off, native host sai path | Lỗi tiếng Việt có bước sửa, không app giả Sẵn sàng |
| SYS-13 | Chrome worker suspend/offscreen close | Reconnect lấy snapshot, không phát trùng đoạn đã nghe |
| SYS-14 | Sleep/wake, tai nghe Bluetooth đổi thiết bị | Clock reset/re-anchor, không bùng audio tồn |
| SYS-15 | Hai tab cùng bật/đóng tab đang nói | Quyền phiên rõ, chỉ một nguồn, không audio mồ côi |
| SYS-16 | WebSocket từ website lạ/replay token | Reject trước xử lý, không log token, không download |
| SYS-17 | Caption chứa HTML/script/"ignore instructions" | Render text, dịch dữ liệu, không eval/tool/shell |
| SYS-18 | File model hỏng/path ../ /tệp .part | Không load, không vượt thư mục, có thông báo |
| SYS-19 | Private mode rồi crash | Không transcript/audio/token rơi xuống đĩa hoặc diagnostics |
| SYS-20 | Tắt mạng AI sau download | Fixture→dịch→TTS chạy local; YouTube Internet được tách riêng |
| SYS-21 | Export SRT sau nhiều lần auto-hold | Mốc nguồn vẫn đúng, không lấy clock thời gian thực |
| SYS-22 | 2giờ VOD/30phútASR | Memory không tăng không chặn, không drift tích lũy |

## Gate không được bỏ qua
No critical semantic error trên tập đã review; all P0 pass; NFR đo có chứng cứ; no auth bypass/echo/wrong-epoch; rollback test; notices/licenses/source hashes; performance và dữ liệu người chấm là thật. Mock tests chỉ đánh giá wiring/helper. Video thiếu caption không phải lỗi sản phẩm nếu fallback đầy đủ, thông báo trung thực; nhưng fallback không chạy được là FR fail.

## Bằng chứng cần lưu
Log đã redact, version/commit/model SHA, fixtures có quyền, event timeline, latency CSV, peak memory, ảnh/video thao tác kiểm thử có đồng ý. Mỗi test có status NOT_RUN/PASS/FAIL/BLOCKED, tester/date/build/evidence. Mọi FAIL/BLOCKED phải có issue và tác động, không đổi thành PASS bằng ghi chú.

## Kiểm tra bộ tài liệu hiện tại
`python -m unittest discover -s tools -p 'test_*.py' -v` kiểm công cụ phụ trợ. Báo cáo thực tại `DELIVERY_VALIDATION.md` phân biệt rõ với các gate sản phẩm chưa thực hiện.
