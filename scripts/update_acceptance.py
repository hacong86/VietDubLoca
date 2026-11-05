"""Ghi trạng thái nghiệm thu TRUNG THỰC vào tests/acceptance-cases.csv và tổng hợp tests/traceability.csv (E12, FR-045).

Quy ước: PASS = có bằng chứng chạy thật (GPU/Chrome/installer thật, hoặc logic tất định không phụ thuộc AI);
PARTIAL = một phần đã kiểm / chỉ runtime giả; NOT_RUN = chưa chạy; BLOCKED = thiếu điều kiện (model/người chấm/máy sạch).
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

E2E = "E2E Chrome153+extension+broker/GPU thật trên YouTube giả lập: D:/VietDubLocal/e2e/fake-2026-09-23T17-57-25 (41/41)"
PY = "pytest tests/python (runtime giả — wiring)"
TS = "vitest tests/ts"
BENCH_A = "benchmarks/results/qwen_q5_A_alone (240/240 cấu trúc hợp lệ, p95 1071 ms)"
BENCH_B = "benchmarks/results/load-b-20260923T220051.json (Qwen+VieNeu cùng GPU, 80/80, p95 1499 ms)"
ASR = "scripts/e2e_live_asr.py thật (small.en CPU): D:/VietDubLocal/e2e/live-asr-20260923T231555.json"
NET = "scripts/audit_network.py: benchmarks/results/network-audit-20260923T231640.json (0 kết nối ngoài loopback)"
INST = "Cài/cập nhật/rollback/gỡ thật vào D:/VietDubTest/home (PROGRESS 22:52)"
SMOKE = "scripts/e2e_broker_smoke.py (broker+Qwen+VieNeu thật)"

S: dict[str, tuple[str, str]] = {
    "AT-001-A": ("PASS", "/v1/env + tab Chẩn đoán trên máy thật (GPU/driver/RAM/ổ đĩa/model); " + SMOKE),
    "AT-001-B": ("NOT_RUN", "Chưa dựng trạng thái thiếu model/CUDA để kiểm màn hình 'chưa sẵn sàng'"),
    "AT-002-A": ("PASS", "Tải thật faster-whisper small.en qua model manager (SHA/git-sha1 khớp HF); test_real_catalog_pinned"),
    "AT-002-B": ("PASS", "test_download_consent_resume_and_checksum, test_download_checksum_mismatch_blocked (I/O tệp thật)"),
    "AT-003-A": ("PASS", "Native messaging thật trong " + E2E + "; test_hostile_origin_rejected_even_with_token; bridge MAIN world không nhận token"),
    "AT-003-B": ("PASS", "Native host đã cài: origin chrome-extension lạ → ORIGIN_DENIED (kiểm 2026-09-23)"),
    "AT-004-A": ("PARTIAL", "Thoát sạch không tiến trình mồ côi (Job Object, gỡ cài: 0 tiến trình); bật tự khởi động với Windows CHƯA chạy thật"),
    "AT-004-B": ("NOT_RUN", "Chưa thoát app khi đang thu âm tab (tabCapture chưa kiểm trên Chrome thật)"),
    "AT-005-A": ("PASS", E2E + " T1 (bắt json3 của player), T9 (SPA: video mới có phụ đề riêng); YouTube thật: player tải json3 46 KB trên Chrome của user"),
    "AT-005-B": ("PARTIAL", "Content bỏ kết quả khi video_id đổi (code + T9); chưa ép đổi video ĐÚNG lúc đang tải"),
    "AT-006-A": ("PASS", E2E + " T1: coverage full, available_until_ms từ json3"),
    "AT-006-B": ("NOT_RUN", "Dự phòng transcript DOM chỉ có unit test (cuesFromTranscript); chưa kiểm video dài render 10 dòng"),
    "AT-007-A": ("PASS", TS + " captions (BOM/CRLF, lỗi có số dòng); nhập SRT trên YouTube thật đã phát tiếng Việt"),
    "AT-007-B": ("PASS", TS + " 'reports errors with line numbers and never keeps markup'; test_subtitle_errors_have_line_numbers"),
    "AT-008-A": ("PARTIAL", ASR + " — nguồn là fixture qua broker, CHƯA kiểm tabCapture + AudioWorklet trên Chrome thật"),
    "AT-008-B": ("NOT_RUN", "Chưa kiểm từ chối quyền tabCapture trên Chrome thật"),
    "AT-009-A": ("PASS", ASR + ": 0 câu lặp; asr.draft tách khỏi commit; test_asr_worker_commits_stable_text_once (faster-whisper thật)"),
    "AT-009-B": ("PASS", "test_asr_worker_commits_stable_text_once (thật): chỉ commit ổn định, draft không đi TTS"),
    "AT-010-A": ("PASS", "test_fragmented_srt_builds_one_unit_in_order, test_cap_split_prefers_comma_and_keeps_all_words"),
    "AT-010-B": ("PASS", "test_no_split_after_negation_on_pause"),
    "AT-011-A": ("PASS", "test_prompt_context_separate_and_reduced_before_source; ctx 4096"),
    "AT-011-B": ("PARTIAL", "Prompt tách context là dữ liệu (test); chưa có ca đo mô hình thật với context chứa lệnh"),
    "AT-012-A": ("BLOCKED", "Cần người chấm theo rubric (benchmarks/human_review.template.csv) — chưa có kết quả người chấm"),
    "AT-012-B": ("BLOCKED", "Cần người chấm lỗi nghĩa critical"),
    "AT-013-A": ("PASS", "test_protect_and_restore_glossary; " + BENCH_A + " (placeholder khôi phục đủ)"),
    "AT-013-B": ("NOT_RUN", "Chưa có ca 'margin' theo domain chạy mô hình thật + người chấm"),
    "AT-014-A": ("PASS", "test_spoken_does_not_change_display_and_escapes_tags"),
    "AT-014-B": ("PASS", "test_validator_blocks_bad_structures (placeholder còn sót → chặn TTS)"),
    "AT-015-A": ("PASS", "test_validator_blocks_bad_structures; " + BENCH_A),
    "AT-015-B": ("PASS", "test_translate_repair_once_then_block (tối đa 1 repair rồi BLOCKED)"),
    "AT-016-A": ("PASS", E2E + " T12: sửa → revision mới, 409 khi xung đột, audio tạo lại (10,1 s), hoàn tác về bản máy; test_override_survives_reopening_video"),
    "AT-016-B": ("PASS", "test_full_pipeline_epoch_and_revision; engine minRevision + broker bỏ audio revision cũ (T12)"),
    "AT-017-A": ("BLOCKED", "Chỉ tải Qwen Q5 theo lựa chọn user; chưa có model thứ hai để đổi"),
    "AT-017-B": ("BLOCKED", "Như trên"),
    "AT-018-A": ("PARTIAL", NET + "; llama --offline, HF_HUB_OFFLINE=1; chưa chặn mạng bằng firewall rồi chạy lại"),
    "AT-018-B": ("PARTIAL", "Không có đường gọi VieNeu cloud trong code (ADR); chưa ngắt mạng thật khi đang chạy"),
    "AT-019-A": ("PARTIAL", "Danh sách giọng thật từ VieNeu (tab Cài đặt, ảnh panel-shots); nút Nghe thử chưa kiểm E2E"),
    "AT-019-B": ("PARTIAL", "test_invalid_saved_voice_reports_and_never_switches_silently (runtime giả; logic resolve_voice giống runtime thật)"),
    "AT-020-A": ("PASS", "PCM 48k s16le frame v1 thật qua WS trong " + E2E + "; audio.test.ts"),
    "AT-020-B": ("PASS", "test_audio_frame_roundtrip_and_rejects; audio.test.ts 'roundtrips and validates'"),
    "AT-021-A": ("PASS", E2E + " T10: không còn tiếng sau 150 ms, âm lượng gốc trả về 1.0"),
    "AT-021-B": ("PARTIAL", "Dừng tại consumer không chờ kernel (T10); chưa ép tắt đúng lúc worker đang infer câu dài"),
    "AT-022-A": ("PARTIAL", "Âm lượng Việt/gốc độc lập (T2: gốc 0.15); phần ASR chưa kiểm trên Chrome thật"),
    "AT-022-B": ("NOT_RUN", "Chưa kiểm ASR khi tiếng gốc = 0 trên Chrome thật"),
    "AT-023-A": ("PARTIAL", "Phụ đề song ngữ trên video (ảnh T2-overlay); chưa kiểm fullscreen/theater"),
    "AT-023-B": ("PARTIAL", "Markup bị gỡ/escape (test); chưa kiểm câu dài ở fullscreen"),
    "AT-024-A": ("PASS", E2E + " T3–T6: pause dừng ≤150 ms, seek tăng epoch, tua nhanh 3 lần epoch cuối thắng"),
    "AT-024-B": ("PARTIAL", "T3 user pause thắng; chưa ghép cùng auto-resume ngay sau seek"),
    "AT-025-A": ("PASS", TS + " 'no double speed'; " + E2E + " T7 (1.5x vẫn đọc)"),
    "AT-025-B": ("PARTIAL", "WSOLA giữ cao độ (test), stop+re-stretch khi đổi rate (code); chưa E2E đổi 2x giữa câu dài"),
    "AT-026-A": ("PASS", E2E + " T8: AD_HOLD, im tiếng Việt, trả âm lượng gốc, hết QC chạy tiếp"),
    "AT-026-B": ("PARTIAL", "Quảng cáo giữa lúc phát PASS (T8); trạng thái stalled chưa kiểm"),
    "AT-027-A": ("PASS", "Bảng bên phân biệt Đang nạp/Đang chuẩn bị/Đang thuyết minh (ảnh P1-watch)"),
    "AT-027-B": ("PASS", E2E + " T15: câu dài + câu sau sát ngay → xếp hàng (tối đa 1 giọng), trễ > 3 s → hold CATCHUP có owner, TỰ phát lại, câu sau vẫn đọc (không bỏ câu, không đổi sang live)"),
    "AT-028-A": ("PARTIAL", ASR + " (live_delayed, không bỏ câu); chưa kiểm trên luồng live thật"),
    "AT-028-B": ("PASS", "test_live_queue_overflow_stops_and_can_resume (logic broker tất định: dừng + báo LIVE_QUEUE_OVERFLOW + nối lại có epoch mới)"),
    "AT-029-A": ("PASS", E2E + " T11: bấm Học kỹ trên bảng bên, video tự dừng cuối câu để đọc hết (23 mẫu giữ hình) rồi tự chạy tiếp; T3 user pause thắng"),
    "AT-029-B": ("PASS", E2E + " T11b: đang giữ hình Học kỹ, người dùng pause → đọc xong video vẫn đứng, engine userPaused=true"),
    "AT-030-A": ("PASS", E2E + " T13: bật ở tab 2 → phiên mới cho video tab 2, tab 1 nhả phiên (nút tắt, âm lượng gốc 1.0), không phát chồng"),
    "AT-030-B": ("PARTIAL", "T13 kiểm 2 tab lần lượt; chưa ép 2 tab xin active GẦN ĐỒNG THỜI"),
    "AT-031-A": ("PASS", E2E + " T9 (chuyển video không dùng transcript cũ), T14 (đóng tab → phiên đóng, không tiếng)"),
    "AT-031-B": ("PASS", E2E + " T14: đóng tab ngay sau khi phiên mới bắt đầu dịch → phiên đóng ~1 s, speaking=false"),
    "AT-032-A": ("PASS", E2E + ": mở/đóng bảng bên (P1, P3) trong lúc phát, audio vẫn đúng (T3–T11)"),
    "AT-032-B": ("PASS", "Như trên; engine nằm ở offscreen, không phụ thuộc panel"),
    "AT-033-A": ("PASS", "test_settings_reset_keeps_overrides_and_glossary"),
    "AT-033-B": ("PASS", "test_settings_reset_keeps_overrides_and_glossary (phải confirm; removed=[])"),
    "AT-034-A": ("PASS", "test_errors_have_vietnamese_message_no_trace; strings.ts ERROR_ACTION_VI"),
    "AT-034-B": ("PASS", "test_errors_have_vietnamese_message_no_trace; security.redact"),
    "AT-035-A": ("PASS", "test_cache_key_differs_by_context_model_glossary; " + SMOKE + " (cache hit lượt 2)"),
    "AT-035-B": ("PASS", "test_cache_key_differs_by_context_model_glossary; audio key gồm voice/fingerprint"),
    "AT-036-A": ("PASS", "test_export_uses_source_timeline_and_needs_ack"),
    "AT-036-B": ("PASS", "test_export_uses_source_timeline_and_needs_ack (sau AUTO_SENTENCE pause vẫn mốc nguồn)"),
    "AT-037-A": ("PARTIAL", "test_private_mode_writes_nothing_to_disk, test_private_mode_cache_ram_only (runtime giả)"),
    "AT-037-B": ("NOT_RUN", "Chưa kiểm crash trong private mode"),
    "AT-038-A": ("PARTIAL", "test_tts_oom_twice_stops_safely (OOM giả lập); chưa gây OOM GPU thật"),
    "AT-038-B": ("PARTIAL", "Như trên"),
    "AT-039-A": ("PASS", BENCH_A + "; " + BENCH_B + "; chất lượng ghi NOT_REVIEWED, không tự chấm; " + NET),
    "AT-039-B": ("PARTIAL", "Diagnostics preview/export có tuỳ chọn payload (mặc định không); chưa có test reference leak"),
    "AT-040-A": ("PARTIAL", INST + " — trên máy dev, CHƯA cài trên tài khoản Windows sạch"),
    "AT-040-B": ("PARTIAL", INST + ": bản hỏng → tự quay lại 0.1.0; migration có backup (test_migration_from_v1_with_backup); chưa ghép với schema DB mới"),
    "AT-041-A": ("PASS", "test_broker_security (18 test); " + NET + " (chỉ listen 127.0.0.1)"),
    "AT-041-B": ("PASS", "test_hostile_origin_rejected_even_with_token, test_bad_host_rejected, test_ws_rejects_foreign_origin_and_no_auth"),
    "AT-042-A": ("PASS", "test_invalid_video_id_and_injection_payload; không có đường tool/shell/eval trong broker/extension"),
    "AT-042-B": ("PASS", "test_full_pipeline_epoch_and_revision (câu 'Ignore previous instructions… rm -rf' được dịch như dữ liệu)"),
    "AT-043-A": ("PASS", NET + "; manifest không xin microphone"),
    "AT-043-B": ("PARTIAL", "Audit phát hiện được kết nối ngoài; chưa giả lập worker cố gọi cloud"),
    "AT-044-A": ("PARTIAL", "THIRD_PARTY_NOTICES.md (161 gói) + sbom/vietdub-sbom.cdx.json trong gói; checkbox quyền khi xuất phụ đề có, installer chưa có checkbox"),
    "AT-044-B": ("PARTIAL", "build_release.py dừng nếu thiếu THIRD_PARTY_NOTICES.md; chưa kiểm riêng thiếu notice model"),
    "AT-045-A": ("BLOCKED", "Gate chất lượng cần người chấm; release_ready=false"),
    "AT-045-B": ("PASS", "Báo cáo này + IMPLEMENTATION_STATUS.md: ca chưa chạy ghi NOT_RUN/BLOCKED"),
}


def main() -> None:
    p = ROOT / "tests/acceptance-cases.csv"
    rows = list(csv.DictReader(io.StringIO(p.read_text(encoding="utf-8-sig"))))
    missing = [r["test_id"] for r in rows if r["test_id"] not in S]
    assert not missing, missing
    for r in rows:
        r["status"], r["evidence"] = S[r["test_id"]]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    p.write_text(buf.getvalue(), encoding="utf-8-sig")
    t = ROOT / "tests/traceability.csv"
    trows = list(csv.DictReader(io.StringIO(t.read_text(encoding="utf-8-sig"))))
    by_fr: dict[str, list[str]] = {}
    for r in rows:
        by_fr.setdefault(r["requirement"], []).append(r["status"])
    for r in trows:
        st = by_fr.get(r["requirement"], ["NOT_RUN"])
        if all(s == "PASS" for s in st):
            r["status"] = "PASS"
        elif all(s == "BLOCKED" for s in st):
            r["status"] = "BLOCKED"
        elif all(s == "NOT_RUN" for s in st):
            r["status"] = "NOT_RUN"
        else:
            r["status"] = "PARTIAL"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(trows[0].keys()), lineterminator="\n")
    w.writeheader()
    w.writerows(trows)
    t.write_text(buf.getvalue(), encoding="utf-8-sig")
    write_report(rows, trows)
    from collections import Counter
    print("cases", Counter(s for s, _ in S.values()))
    print("FR", Counter(r["status"] for r in trows))


def write_report(rows: list[dict], trows: list[dict]) -> None:
    """Chèn bảng FR (sinh từ CSV) vào IMPLEMENTATION_STATUS.md giữa 2 dấu mốc."""
    import re
    prd = (ROOT / "docs/01_PRD.md").read_text(encoding="utf-8")
    titles = dict(re.findall(r"^### (FR-\d{3}) — (.+)$", prd, re.M))
    lines = ["| FR | Chức năng | Trạng thái | Ca nghiệm thu (trạng thái) |", "|---|---|---|---|"]
    for t in trows:
        cases = [f"{r['test_id']} {r['status']}" for r in rows if r["requirement"] == t["requirement"]]
        lines.append(f"| {t['requirement']} | {titles.get(t['requirement'], '')} | **{t['status']}** | {'; '.join(cases)} |")
    lines += ["", "Chi tiết bằng chứng từng ca: `tests/acceptance-cases.csv` (cột evidence)."]
    md = ROOT / "IMPLEMENTATION_STATUS.md"
    if not md.exists():
        return
    body = md.read_text(encoding="utf-8")
    a, b = "<!-- FR-TABLE:BEGIN -->", "<!-- FR-TABLE:END -->"
    if a in body and b in body:
        nl = chr(10)
        body = body[: body.index(a) + len(a)] + nl + nl.join(lines) + nl + body[body.index(b):]
        md.write_text(body, encoding="utf-8")


if __name__ == "__main__":
    main()
