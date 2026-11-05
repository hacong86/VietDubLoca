# Tích hợp VieNeu local — tài liệu bắt buộc

## 1. Nguồn và phiên bản
Đọc https://docs.vieneu.io/ → On-device SDK, không dùng phần Cloud API như SDK cục bộ. Baseline của bộ tài liệu là `vieneu==3.8.1` (PyPI ngày 23/09/2026), model **v3 Turbo**. Tên SDK 3.8.1 không có nghĩa model v3.8.1. v4 là cloud độc quyền và không thuộc dự án [S07][S11][S13].

README/model card có thể không đồng bộ số giọng; lấy danh sách từ SDK đang cài. Docs chỉ rõ README là nguồn ưu tiên khi bất đồng, nhưng khi release vẫn pin revision đã test, không tự nâng theo main [S07][S12].

## 2. Worker và môi trường Windows
TTS là process riêng dùng Python 3.11 x64. Baseline hướng dẫn Windows của nhà cung cấp: torch/torchaudio 2.8.0 cu128, transformers 4.57.6, vieneu [S08]. Đây không phải lock đã resolve trong máy Sếp. Script setup phải kiểm driver/cuda.is_available, pip check, import và warm-up rồi sinh lock thực. Không cài transformers mới cho Qwen vào venv này; llama.cpp chạy binary ngoài Python.

`requirements-vieneu.in` là input baseline, không phải dependency lock. Cài torch từ index CUDA chính thức riêng, không mix global pip. CUDA toolkit/compiler đầy đủ không được yêu cầu trừ khi dependency thật cần build; không tự đổi driver hệ thống.

## 3. SDK adapter
Luồng logic (thông số/syntax phải smoke-test với bản pin):
```python
from vieneu import Vieneu
engine = Vieneu(mode="v3turbo", max_batch_size=2)
voices = engine.list_preset_voices()
audio = engine.infer(text, voice=validated_voice_id)
engine.save(audio, output_path)
# Live: for chunk in engine.infer_stream(text, voice=validated_voice_id): ...
```
Chỉ dùng preset được liệt kê; mặc định gợi ý Minh Quân nếu runtime có, nếu không yêu cầu chọn trong danh sách. Không hard-code 23/25 giọng như điều kiện chức năng. Không tự clone giọng người nói trong video. Không cần reference clip cho preset [S07][S12].

Worker chuẩn hóa output envelope: job_id/session_id/epoch/segment/revision, sample_rate=48000 với Turbo, channels=1, codec pcm_s16le, seq, is_last, duration nếu complete. SDK stream float32 mono 48k cần clamp về [-1,1], convert s16le chính xác trước wire [S09]. PCM chunk boundaries không phải word boundaries.

## 4. Hai cách gọi
**Mặc định:** broker → framed IPC → worker Vieneu trực tiếp. Ít dịch vụ mở cổng, kiểm soát queue/epoch và ràng buộc bộ nhớ.
**Adapter tùy chọn:** dùng compatible server local của VieNeu và `/v1/audio/speech`. Chỉ accept loopback, auth; adapter tự phát metadata theo project contract. Không dùng mode='remote' legacy v2 như nhánh v3 mới, không mặc định gọi api.vieneu.io [S10].

Tính năng project không phụ thuộc người dùng phải mở official VieNeu Desktop. Giao diện Dubbing của ứng dụng chính thức không được giả định là module API sẵn có trong SDK; dự án tự xây đồng bộ.

## 5. VOD và live
VOD: tạo xong audio từng unit để biết D chính xác; cache native-speed PCM/WAV. Streaming chỉ dùng khi unit đã dịch hoàn chỉnh nhưng muốn nghe sớm trong chế độ live; không feed từng token dịch chưa ổn định.

Nếu server trả streaming WAV/chunked HTTP, không gọi decodeAudioData cho từng network chunk như mỗi chunk là WAV hoàn chỉnh. Ưu tiên PCM với header cố định của project hoặc gom toàn WAV trước decode. Resample ở AudioContext theo thông tin sample rate, không hard-code device 48k.

## 6. Warm-up và tài nguyên
Load một engine, không khởi tạo mỗi câu. Warm-up batch 1/2 bằng text fixture có dấu Việt/tên tiếng Anh; tách thời gian load/first call/steady. GPU scheduler chỉ dispatch gần deadline; hạn batch để không mở graph/buffer lớn hàng loạt. Không bật max_streams lớn để chạy một người nghe.

TTFA/RTF từ tác giả là chỉ số riêng của TTS trong điều kiện tác giả; không quảng cáo toàn pipeline nhanh 115ms. Con số benchmark ghi vào report phải từ máy thực, có phiên bản/cỡ câu/mức GPU đang bận.

## 7. Điều khiển và giới hạn
`style` đã deprecated/ignored trong nhánh hiện tại [S11]; không thiết kế UI “phong cách giọng” dựa tham số không còn tác dụng. Không thêm emotion tags tự động. Từ điển phát âm xử lý trước TTS, có preview và version. Không đọc mã placeholder/JSON.

Turbo CPU ONNX fp32 là phục hồi không cloud nếu người dùng đồng ý; kiểm tra chất lượng/tốc độ lại. Không âm thầm chuyển Nano vì Nano chất lượng/48k/streaming khác; Nano không thuộc preset mặc định của sản phẩm này [S08][S09]. CPU int8 có yêu cầu tập lệnh CPU và rủi ro âm thanh; không bật chỉ vì CPU có chữ i9.

## 8. Cancel và lỗi
Cancel job ngăn dispatch mới; kernel đã chạy xong vẫn trả rồi broker bỏ khi epoch/revision stale. Audio engine stop độc lập. Worker crash một lần retry có cooldown; OOM reduce batch/stop competing work; hai lần thất bại liên tiếp → rõ lỗi, không loop restart. Unit output zero/NaN/Inf/wrong duration/sample rate → reject, không phát tiếng rè. Voice missing, model missing, backend unavailable có error code riêng.

## 9. License và model provisioning
Nguồn SDK/model preset do tác giả công bố Apache-2.0; lưu license/notices và nguồn dependency codec/phonemizer [S12]. Tải artifact thực qua SDK có kiểm tra đường dẫn/egress chỉ trong setup. Không mang nhầm model 0.3B cũ có điều kiện khác vào release. Không phân phối lại clone voice không có quyền. Quyền model không thay thế quyền video/transcript.

## 10. Acceptance riêng
Import+infer có dấu Việt, tên Unity/Qwen, số/đơn vị, câu ngắn/dài; list voices; pause/cancel midstream; complete/stream waveform duration hợp lý; backend không mạng sau tải; GPU thật và CPU recovery; không tắt tiếng source làm ASR câm; không capture lại TTS; kiểu đọc/naturalness được nghe bởi người Việt. Không chỉ assert file WAV tồn tại.
