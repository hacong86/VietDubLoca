# UX, nội dung tiếng Việt và asset

## Hệ thống giao diện
Tên tạm VietDub Local. Phong cách tiện ích tập trung video: ít chiếm diện tích, văn bản Việt rõ; hỗ trợ sáng/tối theo hệ thống. UI dùng font hệ thống hỗ trợ tiếng Việt, không tải font runtime. Icon đơn sắc SVG do đội tự vẽ hoặc thư viện license kiểm tra; màu xanh trạng thái sẵn sàng, vàng chờ, đỏ lỗi, luôn có chữ/icon đi kèm.

## Danh sách màn hình (đều trong phạm vi)
| ID | Màn hình | Nội dung và hành động |
|---|---|---|
| UI-01 | Onboarding | Local AI, mạng chỉ cần tải model/xem YouTube; nút Kết nối companion |
| UI-02 | Kiểm máy | GPU/VRAM trống/RAM/driver/ổ đĩa/backend, sửa lỗi không cần terminal |
| UI-03 | Quản lý model | Tên/quant/nguồn/dung lượng/trạng thái hash, tải/import/pause/resume/xóa |
| UI-04 | Ghép nối | Chờ Native host, thành công, sai extension ID, cài lại companion |
| UI-05 | Chọn giọng | Danh sách runtime, tìm kiếm, sample, chọn; không tự clone |
| UI-06 | Bảng điều khiển video | Bật Việt, nguồn, mode, buffer, volume hai đường, trạng thái |
| UI-07 | Overlay | Dòng Anh/Việt, current highlight, nút mở panel, ẩn khi không cần |
| UI-08 | Transcript | Cuộn theo video, khóa cuộn, tìm kiếm, click đi tới câu, nghe lại |
| UI-09 | Sửa bản dịch | Source readonly, display/spoken, preview, undo, lưu revision |
| UI-10 | Thuật ngữ | Domain/preserve/translate, nhập JSON, xuất, kiểm xung đột |
| UI-11 | Không có caption | Nguyên nhân, Thử lại, Nhập phụ đề, Dịch âm thanh tab |
| UI-12 | Live | Nhãn Có độ trễ, lag, queue, cảnh báo không theo kịp, dừng an toàn |
| UI-13 | Học kỹ | Nghe lại/tiếp câu, auto-hold on/off, song ngữ |
| UI-14 | Cài đặt | Model, audio, buffer, privacy/cache, shortcuts, startup |
| UI-15 | History/cache | Opt-in lịch sử, xóa theo video/toàn bộ, export SRT/VTT |
| UI-16 | Diagnostic/A-B | Chạy test local, tiến độ, lỗi, xuất kết quả; không tự chấm đúng nghĩa |
| UI-17 | About/Notices | Phiên bản app/runtime/model, nguồn, license, quyền dữ liệu |
| UI-18 | Update/recovery | Tải đã xác minh, rollback, thiếu dung lượng, worker crash, GPU bận |

## Side panel chính
Header tên video (1–2 dòng) và Local badge; hàng nguồn “Phụ đề tiếng Anh • Có thể chuẩn bị trước” hoặc “Âm thanh tab • Có độ trễ”; công tắc Bật tiếng Việt; chọn Đồng bộ / Trực tiếp / Học kỹ; hai sliders audio; transcript chiếm phần chính; footer status model/giọng và mở diagnostics. Không hiển thị mọi tham số temperature/KV cache ở giao diện thường.

## Các chuỗi trạng thái chuẩn
“Đang kết nối chương trình trên máy…”; “Đang nạp mô hình dịch…”; “Đang chuẩn bị giọng đọc…”; “Đang chuẩn bị câu tiếp theo…”; “Đang đọc hết câu”; “Đã dừng theo thao tác của bạn”; “Video đang phát quảng cáo”; “Không lấy được phụ đề phía trước”; “Dịch âm thanh tab sẽ có độ trễ”; “Máy đang xử lý không kịp — đã dừng thuyết minh, không bỏ câu âm thầm”; “Bản dịch câu này chưa đạt kiểm tra”; “Mô hình bị thiếu hoặc tệp tải chưa hoàn tất”.

## Quy tắc interaction
Click overlay không cản seek bar; dùng Shadow DOM và scoped CSS. Fullscreen phải xác minh overlay nằm trong fullscreen element hoặc panel fallback; Picture-in-Picture có hạn chế khác, không hứa overlay tồn tại trong cửa sổ PiP nếu browser không hỗ trợ. Đóng popup/panel không tắt phiên. Esc đóng dialog trước, không dừng video bất ngờ. Mỗi control có aria-label Việt và focus visible; shortcut có thể đổi và không ghi đè phím YouTube một cách mù quáng.

## Asset manifest
Icon app PNG 16/32/48/128 (extension) và ICO 16/32/48/256 (Windows); SVG source 1 file; icons trạng thái link/download/pause/play/volume/caption/glossary/settings/error/offline; empty states đơn giản bằng SVG; 4 screenshot hướng dẫn do đội ghi từ bản app thật. Tên icon và label liệt kê tại config/ui.vi.json. Bộ tài liệu không chứa thiết kế logo đã chốt; không dùng logo Google/YouTube/VieNeu làm thương hiệu app hoặc tạo ảnh giả như screenshot sản phẩm đã chạy.

## Accessibility acceptance
Tab order theo nhóm; screen reader đọc label/value/error; font 14–16 px trở lên panel, subtitle cho tăng; contrast đo ở theme thực; không emoji thay icon bắt buộc; nội dung dài wrap không overflow; 125%/150% DPI Windows; subtitle có đủ dấu; reduced motion không auto animation.
