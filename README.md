# VietDub Local

Dịch phụ đề YouTube sang tiếng Việt và đọc thuyết minh bằng AI chạy trên máy Windows. Không cần API key. Internet cần cho YouTube và tải thành phần ban đầu.

**0.1.2 preview — bản dùng thử**, chưa phát hành Chrome Web Store và chưa được xác nhận trên Windows sạch/mọi GPU. Mã nguồn được chia sẻ theo **[PolyForm Noncommercial 1.0.0](LICENSE)**; sử dụng phi thương mại theo các điều khoản của giấy phép. Thành phần bên thứ ba giữ giấy phép riêng, xem [NOTICE](NOTICE) và [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

**[Tải bộ cài Windows](https://github.com/hacong86/VietDubLoca/releases/tag/v0.1.2-preview)** · **[Hướng dẫn cài mới hoàn toàn bằng tiếng Việt](docs/CAI_MOI_TU_GITHUB.md)**

Tại trang Release, mở **Assets**, tải `VietDubLocal-0.1.2-win-x64.zip` và `SHA256SUMS.txt`. Không chọn **Source code (zip)** để cài ứng dụng: đó là mã nguồn dành cho người phát triển. ZIP khoảng 19 MB; khi cài còn tải vài GB thư viện và khoảng 3,55 GB model cơ bản.

## Điểm mới 0.1.2

- Hiện bước cài, công việc hiện tại, thư viện đang tải, thời gian chạy và log trực tiếp. Tệp runtime có số byte/tổng và phần trăm; khi chưa biết tổng, thanh chạy chỉ biểu thị đang xử lý.
- Sửa báo thất bại dù bộ cài đã hoàn tất do mã thoát rỗng trên PowerShell 5.1.
- Ô đồng ý tải được tích sẵn; có thể bỏ tích. Chỉ tải khi bấm **Cài đặt**.
- Chọn phụ đề YouTube theo thông tin ngôn ngữ có sẵn và gửi ngôn ngữ nguồn tới bộ dịch; chẳng hạn phụ đề tiếng Thái được dịch sang tiếng Việt. Chất lượng và việc chọn đúng phụ đề tùy từng video. Nhận dạng âm thanh không có phụ đề vẫn chỉ hỗ trợ tiếng Anh.
- Sau khi cài, mở tệp `Cap-nhat-VietDub.cmd` tại nơi lưu để tải bản mới; model đã tải được giữ lại. Bản 0.1.1 có thể tải riêng tệp `Cap-nhat-tu-0.1.1.cmd` và chọn nơi cài cũ.
- Bản 0.1.1 đang dùng vẫn có thể tiếp tục tải model/xem video; không bắt buộc cài lại để dùng chức năng hiện tại.

## Cài và dùng

1. Tải ZIP Windows ở trang Release phía trên và giải nén toàn bộ vào một thư mục.
2. Nhấp đúp **Setup.cmd**. Chọn nơi lưu có ít nhất 20 GB trống; xem thông tin tải rồi bấm **Cài đặt**. Ô đồng ý tải đã tích sẵn và bạn có thể bỏ tích. Chức năng nhận dạng âm thanh là tùy chọn. Không cần tự cài Python/Node hoặc quyền quản trị.
3. Mở hướng dẫn sau cài. Trong Chrome, vào `chrome://extensions`, bật **Developer mode**, chọn **Load unpacked** và chọn thư mục **extension tại nơi đã cài**. Không chọn extension trong gói ZIP tạm.
4. Mở VietDub → **Kết nối** → tab **Mô hình**. Xem dung lượng/giấy phép, đồng ý rồi bấm **Chuẩn bị để sử dụng**. Ứng dụng tải, kiểm và nạp đủ bộ dịch Qwen, giọng VieNeu và codec MOSS.
5. Khi báo **Sẵn sàng dịch và đọc**, mở video YouTube có phụ đề, vào tab **Xem** → **Bật tiếng Việt**; kiểm ngôn ngữ đã chọn trong thông tin nguồn.

Máy đích: Windows 10/11 x64, NVIDIA GPU và driver tương thích runtime CUDA đã ghim; cấu hình tham chiếu là RAM 32 GB/RTX 3060 12 GB. Chưa công bố cấu hình tối thiểu đã đo trên nhiều máy. Bản cài kiểm kiến trúc, dung lượng, sự hiện diện driver; điều đó không thay thử nạp model trên từng GPU.

Tệp tải hợp lệ được dùng lại khi thử lại. Nếu cài dở, chạy Setup.cmd vào cùng nơi lưu. Khi cập nhật, giữ nơi cài và bấm Reload tiện ích Chrome sau khi xong. Cài lại để thêm ASR, sau đó tải thêm model ASR trong phần chuẩn bị. Không dùng thư mục dữ liệu của bản dev chưa có dấu cài đặt: chọn thư mục mới.

Xem [hướng dẫn chi tiết](docs/CAI_MOI_TU_GITHUB.md), nhật ký tại `<nơi cài>/logs/install.log` và tab Chẩn đoán. Bộ cài chưa ký số. SHA256 trong tệp tải kèm Release kiểm tính toàn vẹn, không thay chữ ký/xác minh nhà phát hành.

## Phát triển và đóng gói

Yêu cầu Node >=22, pnpm, Python 3.11 và uv. Không cần model AI để chạy unit test/build extension.

```powershell
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build
uv venv --python 3.11 .venv-broker
uv pip sync --python .venv-broker/Scripts/python.exe --require-hashes requirements/dev.lock.txt
.venv-broker/Scripts/python.exe -m pytest -q tests/python
.venv-broker/Scripts/python.exe scripts/build_release.py --uv <duong-dan-uv.exe>
```

`config/extension-public-key.json` là **khóa công khai**, dùng để giữ ID extension ổn định; không chứa khóa ký riêng. `config/runtime-lock.json` chứa URL/checksum runtime đã ghim. Build không đọc cấu hình hoặc runtime của máy phát triển. ZIP không kèm model, dữ liệu người dùng hoặc môi trường Python của máy build; bộ cài tải Python và thư viện riêng vào nơi người dùng chọn.

Các phép kiểm bổ sung:

- `node scripts/test_setup_ui.mjs`: Chrome headless, profile riêng, giao diện thật với API kiểm thử; bằng chứng trong `.local/setup-ui-*`.
- `powershell -NoProfile -STA -ExecutionPolicy Bypass -File packaging/windows/setup.ps1 -PreviewImage .local/setup-preview.png`: render cửa sổ cài thật và kiểm trạng thái đồng ý; không cài/tải.
- `install.ps1 -HomeDir <thu-muc> -CheckOnly`: kiểm checksum gói và thư mục mà không cài. Chạy từ gói đã build.
- `install.ps1 -AcceptDownloads -IncludeAsr -StartWithWindows`: CLI nâng cao, ASR và tự chạy đều tự chọn. `-UseExistingRuntime -TtsPython ... -AsrPython ...` chỉ dành cho người chủ động dùng runtime có sẵn.
- `powershell -NoProfile -ExecutionPolicy Bypass -File <noi-cai>/app/uninstall.ps1 -KeepModels -KeepData`: gỡ chương trình, giữ model/dữ liệu. Bỏ hai cờ nếu muốn xóa chúng.

Các bài kiểm GPU/YouTube thật được tách khỏi unit test; không suy ra chất lượng dịch/giọng hoặc độ ổn định dài hạn từ test xanh. Tài liệu thiết kế gốc tại `docs/01_PRD.md`, `docs/03_ARCHITECTURE.md`, hợp đồng tại `contracts/`. Tài liệu thiết kế cũ và số đo 0.1.0 là tư liệu lịch sử; hướng dẫn cài hiện hành là [CAI_MOI_TU_GITHUB.md](docs/CAI_MOI_TU_GITHUB.md).

## Kết quả kiểm bản preview

Các kiểm thử tự động dùng runtime giả cho luồng phụ đề, không đánh giá chất lượng dịch thật. Đã tái hiện lỗi mã thoát PowerShell và kiểm tiến trình thật trả mã 0/7, log cập nhật trước khi kết thúc, byte/phần trăm có số đo. Bản preview vẫn cần kiểm với video thực tế, mô hình AI và GPU của từng máy.
