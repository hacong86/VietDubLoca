# Bảo mật, riêng tư và giấy phép

## Threat model
Kẻ tấn công có thể kiểm soát caption/title/DOM trang hoặc một website khác đang mở; có thể gửi HTTP/WS tới loopback từ trình duyệt. Không giả định localhost là an toàn mặc định. Extension hoặc máy đã bị malware có quyền user là ngoài bảo đảm của app, nhưng vẫn không để log/token/path lộ không cần thiết.

## Bootstrap và xác thực
Native host `com.vietdub.local` chỉ allowed_origins đúng extension ID (không wildcard), validate caller origin và message schema. Host khởi broker path đã cài cố định; không nhận exe/args/path tùy ý. Browser được token phiên entropy ≥256 bit qua Native Messaging, không qua page. Token có TTL, rotate khi restart/re-pair, lưu memory/session extension trusted context, không storage.sync.

Broker bind 127.0.0.1 với port do launcher cấp; Host allowlist và Origin chrome-extension://ID kiểm trước upgrade. REST dùng Authorization Bearer. Browser WebSocket không gửi custom Authorization header qua constructor: dùng message AUTH đầu tiên trong 3s; không cho enqueue/subscribe/PCM trước auth, frame đầu cap nhỏ; không token query string hoặc Sec-WebSocket-Protocol log. Session binding active tab/epoch chống cross-tab. CORS không thay auth. Reject Origin null/website; native broker↔worker IPC không cần CORS nhưng cần token/ACL theo transport.

## Giới hạn và đường dẫn
Text/request ≤64KiB, max 3 segments normal batch, imported file ≤10MiB, audio frame ≤256KiB, queue cap, rate limit và connection cap. Mọi path do server tạo hoặc file picker của companion; normalize rồi resolve trong app root, chặn `..`, UNC/network paths, symlink/junction traversal. Không nhận URI HTTP tùy ý để fetch. Model URL từ catalog allowlist và revision đã xác minh, không execute remote code trong model. GGUF/weights cũng cần nguồn đáng tin và checksum.

## Chrome permissions
Chỉ youtube.com hosts cần thiết, activeTab/scripting/storage/offscreen/sidePanel/nativeMessaging; tabCapture optional xin khi ASR, không mic. Loopback host permission giới hạn localhost; vì match pattern không giới hạn port như firewall, app tự validate port bootstrap. Không <all_urls>, cookies, debugger, webRequest hay permissions rộng nếu không có yêu cầu/test tương ứng. Chính sách API/version cần đối chiếu tài liệu Chrome lúc release [S15–S20].

## Prompt injection
Caption là untrusted data. System chỉ dịch; tool use disabled; output schema không tool fields; không lời nhắc nào từ caption được xem là chỉ dẫn app. Gửi LLM câu “run this command” chỉ để dịch câu đó; không execute. HTML escaping bắt buộc ở source/target/diagnostic. Prompt rules không thay sandbox, auth và no-tools.

## Quyền riêng tư
Không telemetry/cloud crash reporting mặc định; không analytics remote. Sau provisioning, worker inference phải chạy khi chặn internet. YouTube browser vẫn tải video nên không quảng cáo “toàn máy không có traffic Internet”. Network audit phân process/domain. Raw audio RAM bounded và xóa khi dừng. Private mode không lưu history/text/audio/log payload. Diagnostic xuất local có preview và redaction; gửi cho ai là quyết định riêng người dùng.

## Model và code license
Theo các kho đã kiểm: Qwen3.5-4B [S04], Gemma4 [S01], VieNeu v3 Turbo [S12] công bố Apache-2.0. Tệp quant là artifact riêng cần provenance/notice. FAQ tác giả VieNeu xác nhận preset voices kèm model và audio tạo bằng chúng có quyền thương mại; vẫn giữ notices và không suy rộng sang reference voice bên ngoài [S12]. Đây là hồ sơ license theo nguồn, không phải tư vấn pháp lý bảo đảm mọi cách dùng.

Giữ LICENSE/NOTICE của model/runtime/codec/phonemizer/GUI/audio DSP trong SBOM. Việc dùng Apache model không tự cấp quyền transcript/video của người khác. Không bypass DRM/paywall, không tự tải/tái xuất bản video; export phụ đề chỉ theo thao tác người dùng và nhắc quyền nội dung. Thương hiệu tạm không ngụ ý được YouTube/Google/VieNeu bảo trợ.

## Windows/install/update
Per-user, không admin nếu không cần; native manifest dưới đường dẫn app, registry đúng Chrome NativeMessagingHosts của current user. Không tắt Defender/firewall hoặc set execution policy toàn máy. Bản phát hành ký số khi có chứng thư của chủ sản phẩm; không fake chữ ký. Update xác minh hash và chữ ký manifest đã pin; TLS không thay toàn bộ integrity. Giữ binary cũ để rollback có kiểm tra DB compatibility.

## Security release gates
Website ngoài app không gọi infer, auth giả hết hạn fail, null Origin fail, path traversal fail, caption injection không thực thi, malformed JSON/PCM không crash, download mismatch không load, private mode không artifact payload, log không token, hai tab không cross-session, sleep/wake không phát cũ. Có exploit proof/test thay vì chỉ checklist tick thủ công.
