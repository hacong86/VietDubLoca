# Hướng dẫn sử dụng — VietDub Local 0.1.6 preview

VietDub Local dịch phụ đề video YouTube sang tiếng Việt và đọc thuyết minh bằng giọng VieNeu. Mọi xử lý AI (dịch Qwen, giọng đọc, nhận dạng giọng nói) chạy **trên máy của bạn**, không gửi phụ đề hay âm thanh lên Internet. Nhận dạng âm thanh khi không có phụ đề hiện chỉ hỗ trợ tiếng Anh.

Yêu cầu: Windows 10/11 x64, NVIDIA và driver tương thích runtime đã ghim, Chrome, ít nhất 20 GB trống. Máy tham chiếu RAM 32 GB/RTX 3060 12 GB; chưa công bố cấu hình tối thiểu đã đo trên nhiều máy. Nếu tải từ GitHub hoặc chuyển từ bản cũ, đọc [hướng dẫn cài mới](CAI_MOI_TU_GITHUB.md) trước.

## 1. Cài đặt

1. Giải nén `VietDubLocal-0.1.6-win-x64.zip`, đối chiếu mã SHA256 với `SHA256SUMS.txt` từ nơi nhận gói.
2. Nhấp đúp **Setup.cmd**, chọn nơi lưu, xem thông tin tải và đánh dấu đồng ý. Bấm **Cài đặt**. Python, thư viện giọng và runtime được cài riêng; không cần quyền quản trị. ASR và tự chạy cùng Windows đều mặc định tắt. Có thể cài lại vào cùng nơi để thêm ASR.
3. Mở hướng dẫn sau cài. Chrome → `chrome://extensions` → bật **Developer mode** → **Load unpacked** → chọn thư mục `extension` **tại nơi đã cài** ghi trong hướng dẫn. Không chọn thư mục trong ZIP tạm.
4. Biểu tượng VietDub trên khay hệ thống là chương trình xử lý AI trên máy. Bản cài chưa ký số; Chrome yêu cầu người dùng tự nạp tiện ích.

**Cập nhật:** mở `Cap-nhat-VietDub.cmd` trong nơi lưu, đồng ý tải và bấm Cài đặt; xong bấm Reload tiện ích Chrome. Nếu bộ xử lý mới không khởi động được trong lúc cài, bộ cài thử trả con trỏ về bản trước. Xem nhật ký nếu báo không khôi phục được hoàn toàn.
**Gỡ cài:** `powershell -ExecutionPolicy Bypass -File D:\VietDubLocal\app\uninstall.ps1` (thêm `-KeepModels` để giữ mô hình, `-KeepData` để giữ bản sửa/bộ nhớ đệm), rồi gỡ tiện ích trong `chrome://extensions`.

## 2. Lần đầu sử dụng

1. Bấm biểu tượng VietDub trên thanh Chrome để mở **bảng bên**, bấm **Kết nối**. Nếu chưa sẵn sàng, tiện ích chuyển tới tab **Mô hình**.
2. Xem bộ đề xuất và dung lượng, đồng ý tải rồi bấm **Chuẩn bị để sử dụng**. Ứng dụng tự kiểm/tải *Qwen3.5 4B Q5*, *VieNeu v3 Turbo* và *MOSS codec* (khoảng 3,55 GB trọng số), sau đó nạp dịch/giọng. ASR là tùy chọn. Tệp chỉ được dùng sau khi kiểm checksum; khi lỗi có thể thử lại, phần hợp lệ được dùng tiếp. Có thể đóng panel trong lúc tải nhưng giữ companion chạy. Đợi **Sẵn sàng dịch và đọc** trước khi xem.
3. Tab **Cài đặt** → **Giọng đọc**: bấm **Nghe thử** rồi chọn giọng dễ nghe. Không giọng nào là giọng thật của người trong video, và app không nhân bản giọng.

## 3. Xem video có phụ đề

Các chú thích âm thanh thông dụng như [nhạc], [vỗ tay] không được đọc thành tiếng. Nếu một câu vừa có chú thích vừa có lời thoại, ứng dụng vẫn đọc phần lời; chú thích có thể xem trong phụ đề gốc.

1. Mở video YouTube. Trên thanh điều khiển của video có nút **VI**. Bấm nút này hoặc bấm **Bật tiếng Việt** trong bảng bên (phím tắt `Alt+Shift+V`).
2. App thử lấy phụ đề theo thông tin ngôn ngữ từ YouTube, không cần bạn bật CC; kiểm nhãn nguồn để biết phụ đề được chọn.
   **Chuẩn bị trước khi phát:** nếu video đang chạy, app tạm dừng và hiện "Đang chuẩn bị thuyết minh tiếng Việt… %" giữa khung hình (và trong bảng bên) cho tới khi có sẵn khoảng 30 giây tiếng Việt, rồi **tự phát tiếp**. Bấm **Xem luôn** hoặc tự bấm play để bỏ qua. Sau khi tua, app chỉ chuẩn bị ngắn (khoảng 8 giây). Chỉnh 10/20/30 giây hoặc tắt ở tab **Cài đặt**.
3. **Nhãn nguồn phụ đề** cho biết chất lượng đầu vào:
   - xanh **Phụ đề của tác giả**: tốt nhất;
   - vàng **Phụ đề YouTube tự tạo**: có thể sai chữ hoặc thiếu dấu câu, nên bản dịch có thể kém hơn;
   - vàng **Máy bạn nghe và chép lại**: chậm vài giây so với hình.

   Chấm của nút **VI** cũng đổi màu theo nguồn; rê chuột lên nút để xem giải thích.
4. Tiếng gốc tự nhỏ xuống 15%. Chỉnh riêng **Âm lượng tiếng Việt** và **Âm lượng tiếng gốc** trong tab **Xem**.
5. Phụ đề trên video: **Ẩn phụ đề**, **Phụ đề Việt** hoặc **Song ngữ**.
6. Bạn cứ tua, dừng, đổi tốc độ trên YouTube như bình thường; tiếng Việt dừng ngay và theo kịp vị trí mới. Khi quảng cáo chạy, tiếng Việt im và tiếng gốc trở lại.
7. Không bao giờ có hai giọng đọc chồng nhau: câu sau luôn chờ câu trước đọc xong. App **không bỏ câu nào**. Nếu tiếng Việt trễ quá khoảng 3 giây, video dừng một nhịp ("Đang bắt kịp tiếng Việt…") rồi **tự phát lại**, bạn không cần bấm gì. Nếu bạn tự bấm dừng thì app không tự phát lại.

## 4. Ba chế độ thuyết minh (tab Xem → Chế độ)

- **Đồng bộ theo phụ đề** (mặc định): đọc khớp thời điểm câu gốc và **không dừng video giữa chừng**. Câu tiếng Việt dài được đọc nhanh tối đa 1,25 lần (giữ cao độ giọng); câu sau xếp hàng chờ. Chỉ khi trễ quá khoảng 3 giây mới dừng một nhịp để bắt kịp rồi tự phát.
- **Học kỹ**: đọc đúng tốc độ tự nhiên, video tự dừng ở cuối câu để nghe hết rồi tự chạy tiếp. Có nút **Nghe lại câu** (`Alt+Shift+R`). Nếu bạn bấm dừng trong lúc đó thì video đứng yên cho tới khi bạn bấm phát.
- **Trực tiếp có độ trễ**: dùng cho livestream hoặc khi dịch âm thanh tab. Tiếng Việt đi sau lời gốc vài giây. Nếu máy xử lý không kịp, app dừng thuyết minh và báo rõ, cho bạn chọn nối lại, chứ không lặng lẽ bỏ câu.

## 5. Nhiều người nói

Khi phụ đề đánh dấu đổi người nói (dấu `>>` của YouTube hoặc tên người nói trong tệp VTT), app đọc người nói thứ hai bằng giọng khác (tự chọn giọng khác giới với giọng chính). Tắt/bật hoặc chọn giọng thứ hai ở tab **Cài đặt** → **Đổi giọng khi đổi người nói**. Nếu phụ đề không có dấu hiệu nào, app đọc một giọng.

## 6. Video không có phụ đề

- **Nhập phụ đề**: chọn tệp SRT/VTT (tối đa 10 MB). App báo dòng lỗi nếu tệp hỏng và cho chỉnh lệch thời gian (−600 đến 600 giây).
- **Dịch âm thanh tab** (`Alt+Shift+A`): Chrome hỏi quyền **của tab**, không hỏi microphone. App nghe lời gốc rồi mới dịch, nên luôn chậm vài giây so với hình. Bấm **Dừng thu âm thanh tab** để tắt.

## 7. Sửa bản dịch, thuật ngữ, xuất phụ đề

- Tab **Bản dịch**: xem song ngữ theo câu, tìm kiếm, bấm một câu để tua tới. Nút **Sửa** mở hộp:
  - *Chữ hiển thị*: sửa phụ đề;
  - *Cách đọc*: chỉ đổi cách giọng đọc phát âm, không đổi phụ đề;
  - **Lưu bản sửa** tạo lại tiếng cho câu đó; **Dịch lại** cho mô hình dịch phương án khác; **Hoàn tác bản sửa** trả về bản máy dịch.

  Bản sửa được giữ khi mở lại video.
- Tab **Thuật ngữ**: thêm từ cần giữ nguyên (ví dụ tên nút `Apply Root Motion`) hoặc dịch cố định. Chỉ các câu **chưa đọc** mới dịch lại theo từ điển mới.
- **Xuất phụ đề** (SRT Việt, SRT song ngữ, VTT Việt): mốc thời gian theo video gốc. Bạn phải xác nhận chỉ dùng cho nội dung mình có quyền.

## 8. Khi có sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| "Mất kết nối với chương trình trên máy" | Mở VietDub Local từ menu Start hoặc khay hệ thống; bảng bên tự kết nối lại. Không dán khoá nào vào website hay chat. |
| "Đang nạp mô hình dịch…" lâu | Lần đầu mất 30–60 giây. Nếu mãi không xong: tab **Mô hình** kiểm các tệp đã "Đã kiểm tra mã". |
| Máy thiếu bộ nhớ đồ hoạ (GPU) | Đóng bớt game/phần mềm dùng GPU. Sau 2 lần thiếu liên tiếp, app dừng an toàn và báo, không tự tải thêm gì. |
| "Giọng đọc đã chọn không còn trong bộ cài" | Chọn giọng khác ở tab **Cài đặt**; app không tự đổi giọng. |
| Không có tiếng | Kiểm thanh âm lượng tiếng Việt, âm lượng Chrome, bấm **Nghe thử**. Nếu hiện nút "Bấm để tiếp tục âm thanh" thì bấm vào. |
| Không lấy được phụ đề | Bấm **Thử lại**, hoặc nhập SRT/VTT, hoặc dịch âm thanh tab. App không bao giờ hỏi mật khẩu hay cookie YouTube. |
| Cần gửi báo lỗi | Tab **Chẩn đoán** → xem trước rồi xuất. Mặc định không kèm nội dung phụ đề. |

## 9. Dữ liệu và quyền riêng tư

- Mọi dữ liệu nằm trong `D:\VietDubLocal` (mô hình, bộ nhớ đệm, bản sửa, nhật ký). Ổ C chỉ có vài khoá registry nhỏ để Chrome tìm thấy chương trình.
- Lịch sử xem chỉ lưu khi bạn bật. Bộ đệm câu dịch/âm thanh giúp mở lại nhanh; xoá theo video hoặc tất cả ở tab **Cài đặt**.
- **Chế độ riêng tư**: không ghi câu dịch hay âm thanh xuống đĩa.
- Chương trình chỉ nghe ở địa chỉ nội bộ `127.0.0.1`. Đã đo thực tế: khi đang dịch và đọc, các tiến trình AI không mở kết nối nào ra ngoài máy.

## 10. Giới hạn hiện tại

- Chất lượng dịch **chưa được người chấm**. Hãy dùng **Sửa** cho câu sai và báo lại.
- Dịch âm thanh tab và YouTube thật đã có bước kiểm tay, nhưng phần kiểm tự động chạy trên trang YouTube giả lập (xem `IMPLEMENTATION_STATUS.md`).
- Bộ cài chưa có chữ ký số, và chưa thử trên tài khoản Windows mới tinh.
