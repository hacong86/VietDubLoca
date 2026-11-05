"""Error taxonomy ổn định (docs/08 §8). message_vi dành cho người dùng; không traceback/token/path."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# code -> (http_status, retryable, message_vi, action_vi)
CATALOG: dict[str, tuple[int, bool, str, str]] = {
    "CONNECT_FAILED": (503, True, "Không kết nối được chương trình trên máy.", "Mở VietDub Local trên khay hệ thống rồi bấm Kết nối lại."),
    "AUTH_REQUIRED": (401, True, "Cần ghép nối lại với chương trình trên máy.", "Bấm Kết nối lại trong bảng bên."),
    "AUTH_EXPIRED": (401, True, "Phiên ghép nối đã hết hạn.", "Bấm Kết nối lại để lấy phiên mới."),
    "ORIGIN_DENIED": (403, False, "Yêu cầu không đến từ tiện ích VietDub hợp lệ.", "Chỉ dùng tiện ích đã ghép nối."),
    "PROTOCOL_MISMATCH": (409, False, "Phiên bản tiện ích và chương trình không khớp.", "Cập nhật cả tiện ích và chương trình."),
    "STALE_EPOCH": (409, True, "Yêu cầu thuộc vị trí video cũ nên đã bị bỏ.", "Không cần làm gì; hệ thống đang chuẩn bị vị trí mới."),
    "SOURCE_UNAVAILABLE": (404, True, "Không lấy được phụ đề phía trước.", "Thử lại, Nhập phụ đề hoặc Dịch âm thanh tab."),
    "SOURCE_PARTIAL": (200, True, "Chỉ lấy được một phần phụ đề.", "Có thể tiếp tục; đoạn thiếu sẽ báo khi tới."),
    "PERMISSION_DENIED": (403, False, "Chưa được cấp quyền thu âm thanh tab.", "Bấm Dịch âm thanh tab và cho phép khi Chrome hỏi."),
    "INVALID_SUBTITLE": (400, False, "Tệp phụ đề không hợp lệ.", "Kiểm tra dòng lỗi được chỉ ra rồi nhập lại."),
    "MODEL_NOT_READY": (503, True, "Mô hình bị thiếu hoặc tệp tải chưa hoàn tất.", "Mở Quản lý mô hình để tải hoặc chọn mô hình đã có."),
    "MODEL_CHECKSUM_MISMATCH": (409, False, "Tệp mô hình không khớp mã kiểm tra, đã chặn nạp.", "Xóa tệp lỗi rồi tải lại."),
    "TRANSLATION_INVALID": (422, True, "Bản dịch câu này chưa đạt kiểm tra.", "Bấm Dịch lại hoặc sửa câu trong bảng bên."),
    "TRANSLATION_TRUNCATED": (422, True, "Bản dịch bị cắt ngắn.", "Bấm Dịch lại; hệ thống sẽ chia câu nhỏ hơn."),
    "VOICE_NOT_FOUND": (409, False, "Giọng đọc đã chọn không còn trong bộ cài.", "Chọn giọng khác trong danh sách."),
    "TTS_INVALID_AUDIO": (422, True, "Âm thanh tạo ra không hợp lệ nên không phát.", "Bấm Nghe lại câu; nếu lặp lại hãy đổi giọng."),
    "GPU_OOM": (503, True, "GPU đang bận hoặc thiếu bộ nhớ.", "Đóng bớt phần mềm dùng GPU hoặc chuyển cấu hình nhẹ."),
    "WORKER_CRASHED": (503, True, "Bộ xử lý AI bị dừng bất thường.", "Bấm Thử lại; nếu lặp lại mở Chẩn đoán."),
    "LIVE_QUEUE_OVERFLOW": (409, True, "Máy xử lý không kịp — đã dừng thuyết minh, không bỏ câu âm thầm.", "Bấm Tiếp tục từ vị trí hiện tại."),
    "AUDIO_CAPTURE_ENDED": (409, True, "Đã ngừng thu âm thanh tab.", "Bấm Dịch âm thanh tab để bắt đầu lại."),
    "CACHE_DISK_FULL": (507, False, "Ổ đĩa sắp đầy, đã ngừng lưu bộ nhớ đệm.", "Xóa bộ nhớ đệm hoặc giải phóng ổ D."),
    "REVISION_CONFLICT": (409, True, "Dữ liệu vừa được sửa ở nơi khác.", "Tải lại rồi sửa tiếp."),
    # bổ sung cho validation/giới hạn chung
    "VALIDATION_FAILED": (400, False, "Dữ liệu gửi lên không hợp lệ.", "Thử lại thao tác; nếu lặp lại mở Chẩn đoán."),
    "PAYLOAD_TOO_LARGE": (413, False, "Dữ liệu quá lớn.", "Chia nhỏ tệp hoặc thao tác."),
    "RATE_LIMITED": (429, True, "Quá nhiều yêu cầu trong thời gian ngắn.", "Đợi vài giây rồi thử lại."),
    "NOT_FOUND": (404, False, "Không tìm thấy dữ liệu yêu cầu.", "Tải lại bảng bên."),
    "SESSION_CONFLICT": (409, True, "Đã có phiên thuyết minh khác đang chạy.", "Tắt phiên cũ hoặc bấm Chuyển sang tab này."),
    "CONSENT_REQUIRED": (400, False, "Cần xác nhận trước khi tải mô hình.", "Đọc dung lượng/giấy phép rồi bấm Đồng ý tải."),
    "IDEMPOTENCY_CONFLICT": (409, False, "Mã yêu cầu bị dùng lại với nội dung khác.", "Thử lại thao tác."),
    "INTERNAL": (500, True, "Có lỗi nội bộ.", "Thử lại; nếu lặp lại hãy xuất gói Chẩn đoán."),
}

_DETAIL_ALLOW = {"line", "field", "segment_id", "model_id", "expected", "actual", "limit", "retry_after_ms",
                 "voice_id", "state", "reason", "coverage", "count"}


@dataclass
class AppError(Exception):
    code: str
    details: dict[str, Any] = field(default_factory=dict)
    message_override: str | None = None

    def __post_init__(self) -> None:
        if self.code not in CATALOG:
            raise ValueError(f"unknown error code {self.code}")
        super().__init__(self.code)

    @property
    def http_status(self) -> int:
        return CATALOG[self.code][0]

    @property
    def retryable(self) -> bool:
        return CATALOG[self.code][1]

    def to_dict(self, request_id: str, session_id: str | None = None) -> dict[str, Any]:
        _, retry, msg, action = CATALOG[self.code]
        details = {k: v for k, v in self.details.items() if k in _DETAIL_ALLOW and isinstance(v, (str, int, float, bool))}
        details["action_vi"] = action
        return {"code": self.code, "message_vi": self.message_override or msg, "retryable": retry,
                "request_id": request_id or "none", "session_id": session_id, "details": details}
