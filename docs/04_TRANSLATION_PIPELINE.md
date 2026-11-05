# Pipeline dịch Anh → Việt

## 1. Input chuẩn hóa
RawCue: cue_id, source_track_id, source_revision, start_ms, end_ms, text, origin(manual/auto/import/asr), committed. Dùng integer milliseconds. Giữ raw text riêng; normalize Unicode NFC, whitespace, HTML entities và line breaks nhưng không xóa số/ký hiệu/code. Cue markup chỉ parse theo allowlist, tuyệt đối không render HTML trực tiếp.

Loại rolling-caption duplicates bằng token overlap + time overlap, không chỉ dedup chuỗi: câu “No, no, no” phải được giữ nếu người nói thực sự nhắc lại. Dữ liệu thiếu thời gian không được tự gán như mốc có thật; yêu cầu offset/source có thời gian hoặc đánh dấu chỉ dịch văn bản ngoài lịch phát.

## 2. Sentence builder
Trạng thái accumulator có các cue gốc và source token offsets. Tách tại `.?!` khi không phải dấu thập phân/viết tắt, hoặc khoảng nghỉ >800ms sau một cụm có nghĩa. Không tách sau “do not”, “unless”, “only if”, “not only” khi còn vế phụ. Hard cap 60 từ/12s là mục tiêu kỹ thuật: ưu tiên tách tại dấu phẩy/liên từ/cụm có nghĩa; không bỏ phần vượt cap. Khi live chưa đủ nghĩa đến timeout, commit một mệnh đề ổn định hoặc tiếp tục chờ với chỉ báo, không bịa vế kết thúc.

Builder trả TranslationUnit có `unit_id`, `cue_ids`, `start_ms=min(...)`, `end_ms=max(...)`, `source_text`, `revision`, `source_hash`, `boundary_reason`. Một cue dài có thể chia nhiều unit; cần giữ token/time mapping, không đòi quan hệ cue→unit luôn 1:1.

Mốc thời gian là việc của chương trình. LLM không được trả hoặc sửa start_ms/end_ms. Các câu dịch được gắn lại unit_id ban đầu sau khi kiểm tra.

## 3. Context và glossary
Input gồm topic do người dùng chọn, 2 unit trước, 1 unit sau nếu nguồn thực có, danh sách protected terms và glossary domain. Tổng prompt + output nằm trong context 4096; trước tiên giảm context tham khảo, không cắt văn bản cần dịch. Khi input vẫn dài, builder chia unit, không truncate âm thầm.

Không gửi cả lịch sử chat/video mỗi lần. Không chứa token/URL signed cookie/đường dẫn máy. Ngữ cảnh phải tách khỏi `segments` cần trả kết quả. Nếu source bị sửa, context hash của các unit chịu ảnh hưởng cũng thay đổi.

## 4. Chính sách ngôn ngữ
Ưu tiên trung tính, rõ và tự nhiên trong tiếng Việt; không thêm “Sếp”, lời chào, lời giải thích của trợ lý. Giữ ngôi nhân xưng nếu biết; không tự gán tuổi/giới/quan hệ. Giữ mức chắc chắn may/might/must, phủ định, số, điều kiện, đối chiếu, câu nói đùa theo nghĩa khi có thể. Không làm nội dung “hay hơn” bằng cách bỏ điều kiện hoặc thêm ví dụ.

Tên nút/code/path giữ chữ gốc ở display. Glossary phải có domain: “margin” trong CSS không giống tỷ suất lợi nhuận; “bank” không luôn là ngân hàng. Nếu chưa rõ, ưu tiên diễn đạt giữ nghĩa rộng và context, không ép thuật ngữ sai.

## 5. Protected tokens
Chỉ bảo vệ những literal cần chính xác: `Apply Root Motion`, `com.appmaven.demo`, `git reset --hard`, đường dẫn, tên hàm. Placeholder dạng `__KEEP_0001__`; lưu mapping trong chương trình. Cho phép đảo vị trí theo cú pháp tiếng Việt nhưng kiểm tra multiplicity chính xác. Không gửi mapping chứa bí mật. Nếu model làm biến dạng/mất placeholder: retry một lần với cảnh báo, sau đó chặn unit và hiện lỗi. Không giải quyết bằng cách thay chuỗi gần giống mù quáng.

Phân biệt protected literal và thuật ngữ cần dịch: không bọc toàn bộ tiếng Anh vì sẽ làm model trả nguyên văn. Không cấm mọi chữ Hán/Latin vì tên riêng có thể hợp lệ. Heuristic language detector chỉ tạo cảnh báo, cần exemption cho code/tên riêng; một unit ngắn “OK” không đủ bằng chứng sai ngôn ngữ.

## 6. Output và validation
Một model request trả object `translations:[{segment_id, target_text}]`. JSON grammar được runtime kiểm thử; schema nằm trong contracts/translation-output.schema.json. Không có thời gian, confidence tự chấm, tool_calls hoặc lời dẫn. Validate:
1. JSON đúng schema, không extra keys, đủ đúng IDs một lần.
2. Target không rỗng, không reasoning tags/markup hệ thống, không truncation (`finish_reason=length`).
3. Protected tokens/literal numbers có bảo toàn theo quy tắc đã định; semantic numbers khác dạng “1.5”/“1,5” chỉ normalize có locale rõ.
4. Kiểm tra ngôn ngữ/length ratio là warning có giải thích, không tự kết luận đúng nghĩa.
5. Một repair request tối đa, cùng model, không load model thứ hai cho mỗi lỗi. Nếu fail: BLOCKED_TRANSLATION. VOD hold, live giữ text/lỗi và không phát câu bịa.

Không thể dùng regex để chứng minh phủ định không bị đảo nghĩa. Critical semantic errors phải được bộ holdout và người chấm phát hiện. Không dùng back-translation hoặc model tự khen như release certificate.

## 7. target_display và target_spoken
`target_display` = bản dịch sau restore literal, giữ tên lệnh để tìm trong UI. `target_spoken` = quy tắc phát âm có version áp lên display. Ví dụ `GPU` giữ ở phụ đề, dictionary có thể chọn cách đọc người dùng muốn; không chèn cách đọc vào tên tệp/code xuất phụ đề. Số/đơn vị phải xử lý locale ngữ cảnh: 1,024 KB khác 1.024 trong quy ước khác. Không expand lệnh `--force` thành hướng dẫn chạy.

Không tự thêm nhãn cảm xúc [cười]/[thở dài] vào câu vì bản dịch thấy “funny”. Nếu source chứa dấu ngoặc, escape/canonicalize các control tags của TTS trước gọi SDK. Chỉ cho tag do UI tính năng có kiểm soát sinh ra; mặc định không dùng emotion tags.

## 8. Sửa và phát lại
Override của người dùng tạo revision mới, không phá raw/source. Nếu đang đọc unit đó: dừng, hỏi thao tác Nghe bản mới; không tự thay nửa câu. Future unit: hủy audio revision cũ và regen. Chỉnh glossary tạo glossary_version mới và invalidate future units + cache phụ thuộc; không đổi câu đã nghe trong lịch sử không thông báo.

## 9. Cache keys
Translation hash = SHA256(canonical JSON(source text, source/context hashes, languages, topic, glossary_version, prompt_version, model artifact SHA, sampling config, normalizer_version)). Không dùng riêng text để cache câu đa nghĩa. Audio hash = translation display/spoken revisions + voice artifact fingerprint + SDK/model versions + synthesis controls + phonetic dictionary version. Timing được bind ở session, không nhúng timing vào reusable raw audio.

## 10. Scheduler
Cụm gần playhead đến hạn được ưu tiên. Prefetch bounded theo source coverage 30s target/45s high-water; không gửi 3 giờ transcript vào một request. `request_id` để dedup, `epoch` để hủy. Concurrent translator=1. Retry không được đẩy câu cần nghe ra sau hàng trăm job nền.

## 11. Ví dụ nghiệm thu do dự án biên soạn
EN: “You can enable this option, but only after creating a backup.”
VI mong đợi về nghĩa: “Bạn có thể bật tùy chọn này, nhưng chỉ sau khi đã tạo bản sao lưu.”
Không chấp nhận: “Bạn có thể bật tùy chọn này.” — mất điều kiện.

EN: “Attach the script to the player and disable root motion.”
VI: “Gắn script vào nhân vật và tắt root motion.” Có thể có bản diễn đạt khác đúng nghĩa; không ép string match làm thước đo duy nhất.
