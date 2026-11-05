# Tải và cài mới VietDub Local từ GitHub

Hướng dẫn dành cho Windows 10/11 x64 và Chrome. Bản **0.1.1 preview** dịch phụ đề tiếng Anh sang tiếng Việt và đọc bằng AI trên máy. Không cần nhập API key, cài Python/Node hay mở quyền quản trị.

## 1. Chuẩn bị máy

- Có GPU NVIDIA và driver phù hợp. Máy tham chiếu: RTX 3060 12 GB, RAM 32 GB. Chưa xác nhận cấu hình tối thiểu/mọi GPU; bộ cài sẽ kiểm driver nhưng không bảo đảm nạp model trên mọi máy.
- Nơi cài có ít nhất 20 GB trống. Cần mạng để tải thư viện, model lần đầu và xem YouTube.
- Nếu đã chạy VietDub cũ: tắt thuyết minh, chuột phải biểu tượng VietDub ở khay hệ thống → **Thoát VietDub Local**. Gỡ hoặc tắt extension VietDub cũ trong `chrome://extensions`; sau cài nạp lại đúng đường dẫn mới. Bản mới giữ cùng ID extension nên không chạy hai bản cạnh nhau trong cùng profile Chrome.

## 2. Cài sạch mà không mất bản cũ

**Khuyên dùng cho lần thử đầu:** giữ nguyên dữ liệu cũ, cài vào thư mục mới và trống, ví dụ:

```text
D:\VietDubLocal_Test
```

Không chép `models`, `cache`, `runtime` hoặc `local-config.json` từ bản cũ sang. Không chọn “dùng runtime có sẵn”. Bộ cài sẽ tải và tạo môi trường riêng. Cách này kiểm lần cài từ đầu của ứng dụng trên máy hiện tại; không tương đương thử một Windows mới hoàn toàn.

Muốn thử độc lập hơn với `D:\VietDubLocal`: sau khi **Thoát VietDub Local** và đóng Chrome, dùng File Explorer đổi tên thư mục đó thành `D:\VietDubLocal_backup` (chọn tên khác nếu đã tồn tại), rồi cài vào `D:\VietDubLocal` mới. Nếu Windows báo đang được sử dụng, dừng lại và thoát chương trình còn dùng nó; không xóa cưỡng bức. Không cần đổi tên source dự án.

### Có thể xóa `D:\VietDubLocal` không?

Có, khi bạn đã ngừng dùng bản cũ và đã giữ những gì cần thiết. Thư mục này chứa:

| Thư mục/tệp | Xóa sẽ ảnh hưởng gì? |
|---|---|
| `models`, `runtime` | Mất model/bộ chạy; cần tải/cài lại. Bản cũ không tiếp tục hoạt động bình thường. |
| `db`, `backups`, `exports` | Có thể mất thuật ngữ, bản sửa, cấu hình, lịch sử và dữ liệu xuất đã lưu. |
| `cache`, `logs`, `diagnostics`, `e2e*`, `tmp` | Mất cache, nhật ký và dữ liệu thử nghiệm. |
| `keys` | Có thể chứa khóa ký riêng của extension cũ; sao lưu riêng nếu còn cần. Không đăng lên GitHub/gửi kèm báo lỗi. |
| `local-config.json` | Mất cấu hình đường dẫn của bản cũ; không nhập vào lượt cài sạch. |

**Nên đổi tên/sao lưu trước, chỉ xóa backup sau khi bản mới đã dịch và đọc được video.** Xóa thư mục không tự gỡ extension hay mục đăng ký Windows. Bộ cài mới đăng ký lại companion cho tài khoản hiện tại. Khi cần quay lại bản cũ, phải khôi phục cả đường dẫn/đăng ký companion phù hợp; chỉ bật extension cũ chưa đủ sau khi đã cài bản mới.

## 3. Tải đúng gói

1. Mở [Release v0.1.1-preview](https://github.com/hacong86/VietDubLoca/releases/tag/v0.1.1-preview).
2. Trong **Assets**, tải **VietDubLocal-0.1.1-win-x64.zip** và **SHA256SUMS.txt**.
3. Không chọn `Source code (zip)` hoặc ZIP chỉ extension để cài từ đầu. Gói Windows đã có cả companion lẫn extension; trọng số AI được tải sau khi bạn đồng ý.
4. Có thể kiểm ZIP bằng PowerShell trong thư mục tải:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath '.\VietDubLocal-0.1.1-win-x64.zip'
```

So kết quả với dòng đúng tên ZIP trong `SHA256SUMS.txt`. Nếu khác, tải lại, không dùng gói đó. Checksum giúp kiểm tính toàn vẹn; không thay chữ ký nhà phát hành.

## 4. Cài companion

1. Chuột phải ZIP → **Extract All / Giải nén tất cả**. Mở thư mục vừa giải nén đến nơi thấy `Setup.cmd`. Không chạy trực tiếp trong cửa sổ xem ZIP.
2. Nhấp đúp **Setup.cmd**. Bộ cài chưa ký số; nếu Windows cảnh báo, kiểm đúng nguồn GitHub và checksum trước khi quyết định chạy. Không tắt Defender hay đổi chính sách máy toàn cục.
3. Chọn nơi cài mới/trống đã chuẩn bị. Lượt thử cơ bản nên để **nhận dạng âm thanh** và **tự chạy cùng Windows** tắt.
4. Xem thông tin tải, đánh dấu đồng ý rồi bấm **Cài đặt**. Lần đầu tải vài GB thư viện; giữ mạng và không tắt máy. Xem tiến độ trong cửa sổ, chi tiết tại `<nơi cài>\logs\install.log`.
5. Khi báo xong, bấm **Mở hướng dẫn**. Python và thư viện giọng được cài riêng trong nơi đã chọn. Nếu lỗi/mất mạng, xem thông báo và chạy lại vào **cùng nơi cài** để tiếp tục; không tự xóa file lẻ trong runtime.

## 5. Thêm extension vào Chrome

1. Mở `chrome://extensions`.
2. Bật **Developer mode / Chế độ dành cho nhà phát triển**.
3. Chọn **Load unpacked / Tải tiện ích đã giải nén**.
4. Chọn thư mục **extension trong nơi đã cài**, ví dụ:

```text
D:\VietDubLocal_Test\extension
```

Không chọn extension trong thư mục tải/giải nén ZIP. Giữ nguyên thư mục extension đã cài; có thể bỏ thư mục ZIP tạm sau khi cài xong.

5. Bấm biểu tượng mảnh ghép trên Chrome, ghim/mở **VietDub Local**. Nếu cùng ID đã nạp từ đường dẫn cũ, gỡ bản cũ trước rồi nạp lại đường dẫn mới. Kiểm phiên bản hiển thị là **0.1.1**.

## 6. Tải model và xem video

1. Trong bảng VietDub bấm **Kết nối**. Nếu chưa kết nối, mở **VietDub Local** từ Start Menu rồi thử lại.
2. Tab **Mô hình** → đọc dung lượng và giấy phép → đồng ý tải → **Chuẩn bị để sử dụng**.
3. Ứng dụng tải đủ Qwen Q5, VieNeu và MOSS (khoảng **3,55 GB**), kiểm checksum rồi nạp dịch/giọng. Đợi báo **Sẵn sàng dịch và đọc**. Có thể tạm dừng/tiếp tục; đóng panel không dừng tải nhưng cần giữ companion chạy.
4. Mở một video YouTube có phụ đề tiếng Anh. Tab **Xem** → **Bật tiếng Việt**. Lần đầu đợi chuẩn bị thuyết minh; sau đó phải nghe được giọng Việt.
5. Thử tạm dừng, phát lại, tua video và tắt thuyết minh. Tiếng đọc cần dừng/theo vị trí mới và âm lượng gốc được khôi phục khi tắt.

Muốn thử video không có phụ đề: chạy Setup.cmd lại vào cùng nơi cài, chọn thêm nhận dạng âm thanh; sau cài chọn model ASR trong phần chuẩn bị. Nên kiểm video có phụ đề trước để tách lỗi cài đặt với lỗi ASR.

## 7. Ghi kết quả thử

| Bước | Kết quả mong đợi |
|---|---|
| Cài thư mục trống | Báo cài thành công, có `extension`, `runtime`, `app`, hướng dẫn tại nơi cài. |
| Chrome | Nạp đúng extension 0.1.1, không báo lỗi manifest. |
| Kết nối | Mở được các tab, không báo thiếu native host. |
| Model | Tải/kiểm/nạp xong, báo sẵn sàng. |
| Video tiếng Anh | Nghe giọng Việt; tạm dừng/tua/tắt hoạt động. |
| Khởi động lại | Thoát VietDub/Chrome, mở lại và kết nối được, không tải lại toàn bộ model. |

Nếu lỗi, tạo [GitHub Issue](https://github.com/hacong86/VietDubLoca/issues/new) hoặc gửi lại: phiên bản Windows, GPU/VRAM, phiên bản Chrome, bước đang làm, mã lỗi và ảnh thông báo. Có thể gửi đoạn log quanh lỗi sau khi xem và che thông tin riêng. **Không gửi `keys`, database, local-config.json, broker.json hoặc token.**

Bản preview chưa được xác nhận trên Windows sạch/mọi GPU; hướng dẫn này giúp kiểm đúng lượt cài mới và ghi rõ bước còn lỗi. AI chạy cục bộ, Internet vẫn cần cho YouTube/tải thành phần ban đầu.
