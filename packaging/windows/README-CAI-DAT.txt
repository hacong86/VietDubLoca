VietDub Local 0.1.5 preview — Cài trên Windows 10/11 x64
======================================================

Nguồn tải: https://github.com/hacong86/VietDubLoca/releases/tag/v0.1.5-preview
Hướng dẫn thử cài từ đầu: CAI-MOI-TU-GITHUB.md trong gói hoặc docs/CAI_MOI_TU_GITHUB.md trên GitHub.
Đã dùng bản 0.1.1? Chọn đúng thư mục đã cài để giữ model. Giữ backup dữ liệu quan trọng.

1. Giải nén gói ZIP. Nhấp đúp Setup.cmd.
2. Chọn nơi lưu có ít nhất 20 GB trống. Xem thông tin tải; ô đồng ý đã tích sẵn, có thể bỏ tích. Bấm Cài đặt để bắt đầu.
   Bộ cài tự chuẩn bị Python, thư viện giọng đọc và runtime. Không cần quyền quản trị.
   Nhận dạng âm thanh (ASR) và tự chạy cùng Windows là tùy chọn, mặc định tắt.
   Cửa sổ hiện bước, thành phần đang tải/cài và log trực tiếp. Chỉ hiện phần trăm tệp khi có dung lượng thực tế.
3. Mở hướng dẫn khi cài xong. Chrome > chrome://extensions > Developer mode > Load unpacked.
   Chọn thư mục extension TẠI NƠI CÀI được ghi trong hướng dẫn, không chọn từ ZIP tạm.
4. Mở VietDub > Kết nối > Mô hình > đồng ý tải > Chuẩn bị để sử dụng.
   Tự tải và kiểm đủ Qwen, VieNeu, MOSS; sau đó tự nạp bộ dịch/giọng.
5. Đợi “Sẵn sàng dịch và đọc”. Mở video có phụ đề > tab Xem > Bật tiếng Việt. Kiểm ngôn ngữ ở nhãn nguồn.

Yêu cầu: NVIDIA GPU/driver tương thích runtime CUDA ghim. Máy tham chiếu RAM 32 GB,
RTX 3060 12 GB. Chưa xác nhận cấu hình tối thiểu trên nhiều máy. Cần mạng để tải lần đầu.

Nếu bị gián đoạn: chạy lại Setup.cmd vào cùng nơi lưu. Tệp tải hợp lệ được dùng tiếp.
Cập nhật sau này: mở Cap-nhat-VietDub.cmd trong nơi cài, làm theo hướng dẫn, rồi Reload tiện ích Chrome.
Thêm ASR tiếng Anh: chạy lại Setup.cmd, chọn chức năng nhận dạng; tải model ASR trong tab Mô hình.
Nhật ký: <nơi cài>\logs\install.log, setup-error.log; chẩn đoán runtime trong tiện ích.
Chi tiết: HUONG-DAN.html tại nơi đã cài.

Gỡ cài bằng PowerShell:
powershell -NoProfile -ExecutionPolicy Bypass -File "<nơi cài>\app\uninstall.ps1" -KeepModels -KeepData
Bỏ hai cờ cuối nếu muốn xóa cả model/dữ liệu.

AI xử lý trên máy. YouTube và tải thành phần ban đầu vẫn cần Internet.
Bản thử nghiệm chưa ký số, chưa kiểm trên Windows sạch/mọi GPU. Không kèm trọng số AI.
Kiểm SHA256 của ZIP theo SHA256SUMS.txt từ nơi nhận gói; checksum không phải chữ ký nhà phát hành.
