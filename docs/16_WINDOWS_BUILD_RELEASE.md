# Windows: môi trường, build và phát hành
## Nền tảng
Đích Windows x64 của người dùng. Dev có thể dùng Python3.11 và runtime Node được dự án kiểm thử rồi khóa; người dùng cuối không bị yêu cầu tự cài chúng. Không mặc định yêu cầu WSL/Docker. Windows/Chrome actual build/driver được ghi trong report; mọi version ngoài baseline dưới đây cần xác minh khi pin release.

## Tách môi trường
- `runtime/llama/`: binary CUDA riêng, model GGUF text-only. Khóa release/commit, SHA binary và native chat template.
- `.venv-broker`: FastAPI/Pydantic/SQLite helpers; không cài mọi framework GPU vào đây.
- `.venv-vieneu`: VieNeu/PyTorch/Transformers đúng baseline dưới.
- `.venv-asr`: faster-whisper/CTranslate2 riêng, CPU int8 mặc định. CUDA/cuDNN cho GPU ASR có gate riêng [S23].

Ví dụ dev PowerShell (trong thư mục project):
```powershell
py -3.11 -m venv .venv-vieneu
& .\.venv-vieneu\Scripts\python.exe -m pip install --upgrade pip
& .\.venv-vieneu\Scripts\python.exe -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
& .\.venv-vieneu\Scripts\python.exe -m pip install -r config/requirements-vieneu.in
& .\.venv-vieneu\Scripts\python.exe -m pip check
```
Baseline lấy từ tài liệu Windows VieNeu và phiên bản PyPI đã tra [S08][S13], **chưa cài thực trên máy Sếp**. Không coi lệnh install là chứng nhận driver/CUDA compatibility. Sau smoke thành công lưu lock toàn bộ dependency + hash; `runtime-lock.todo.json` hiện để null vì chưa có kết quả thật. Không cần sửa ExecutionPolicy để activate vì gọi trực tiếp python.exe trong venv.

## Lấy model
Xem model-catalog, tải **đúng một filename**, không snapshot cả repository. Chủ động lấy revision/commit thật tại thời điểm tải; tải qua host allowlist, .part, resume theo server, checksum/size và provenance. Nếu hash upstream chưa xác minh, hiển thị UNVERIFIED và không đưa vào release default; tự tính hash local chỉ chứng minh tính nhất quán, không tự xác thực nguồn. Không điền hash tưởng tượng. Model Gemma text-only không cần mmproj. Không chạy mã từ repository model.

## Ví dụ llama-server local
Sau khi lấy binary đã kiểm, model đã xác minh và tạo tệp khóa ngẫu nhiên có ACL chỉ user hiện tại:
```powershell
# Các biến là đường dẫn tuyệt đối do launcher/installer thiết lập, không nhập từ caption.
& $LlamaServerPath `
  --model $ModelPath `
  --alias qwen35_4b_q5 `
  --host 127.0.0.1 --port 8766 `
  --ctx-size 4096 --parallel 1 --n-gpu-layers 99 `
  --jinja --reasoning off --api-key-file $KeyFilePath
```
Flags dựa [S14]; trước pin build kiểm `--help` và request smoke thật. Nhiều build/kiến trúc thay đổi: flag tồn tại chưa đủ để tin model template hỗ trợ. Request Qwen tắt `enable_thinking`, schema JSON, max tokens và sampling trong cấu hình; Gemma alias đổi tương ứng, template không có think token. Không hard-code ngl99 như VRAM bảo đảm: measure actual GPU offload/resident và điều chỉnh theo budget. Endpoint không mở LAN/tunnel.

## Smoke trước đóng gói
Model health→translation exactid→không reasoning→placeholder intact; VieNeu presets→infer→float32/48k→streamconcat; simultaneous inference→đo memory; ASR English fixture→stabletext; network blocking AI; extension handshake và sourceaudioecho test. Kiểm dependency build thực bằng `pip check`, license inventory và clean-user run.

## Đóng gói
Companion per-user vào `%LOCALAPPDATA%\VietDubLocal\app\<version>`; dữ liệu/model/cache ở thư mục riêng có ACL user. Bundle Python runtime và môi trường đã khóa, sidecars/version manifests; launcher native đáng tin nhận đường dẫn cố định. Không mặc định dùng one-file freezer gom mọi CUDA dependency vào một executable vì phải kiểm DLL và license riêng. Kỹ thuật cụ thể freeze/embedded được ghi ADR sau smoke và phải tạo installer thực.

Native Messaging host manifest allowed_origins đúng extensionID; registry HKCU theo tài liệu Chrome [S18]; không yêu cầu admin nếu không cần. Đường dẫn manifest/binary có dấu và khoảng trắng phải test. Dev unpacked ID phải lấy thật rồi pair, không dùng wildcard. Extension package giữ ID/update provenance; Web Store chỉ là bước phát hành khi người dùng yêu cầu, không làm thay trong tác vụ tài liệu.

## Update, rollback và gỡ cài
Download bản mới vào staging, kiểm signature/checksum/manifest, stop children, atomic switch version, run health; fail rollback app và database backup compatible. Không tự downgrade DB bằng xóa bảng. Không autoupdate model vì thay model thay output/cache/license. Gỡ cài có lựa chọn giữ model/overrides; xóa key/registry/startup của app; không xóa Python/driver dùng chung. Startup Windows opt-in mặc định tắt.

## Hồ sơ bản phát hành
Extension.zip + companion installer + checksums + source commit + model/runtime lock + SBOM/THIRD_PARTY_NOTICES + acceptance report + benchmark report + guide tiếng Việt + known issues/rollback plan. Bản tài liệu hiện tại chưa chứa các binary này.
