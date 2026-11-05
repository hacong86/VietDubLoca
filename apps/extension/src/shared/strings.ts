/** Chuỗi giao diện tiếng Việt (docs/10 §Các chuỗi trạng thái chuẩn; config/ui.vi.json). */
import ui from '../../../../config/ui.vi.json';

export const T = {
  ...ui,
  connecting: 'Đang kết nối chương trình trên máy…',
  preparing_next: 'Đang chuẩn bị câu tiếp theo…',
  reading_rest: 'Đang đọc hết câu',
  user_paused: 'Đã dừng theo thao tác của bạn',
  ad: 'Video đang phát quảng cáo',
  no_future_captions: 'Không lấy được phụ đề phía trước',
  tab_audio_delay: 'Dịch âm thanh tab sẽ có độ trễ',
  overflow: 'Máy đang xử lý không kịp — đã dừng thuyết minh, không bỏ câu âm thầm',
  blocked: 'Bản dịch câu này chưa đạt kiểm tra',
  model_missing: 'Mô hình bị thiếu hoặc tệp tải chưa hoàn tất',
  replay_current: 'Đọc lại câu hiện tại',
  click_to_resume_audio: 'Bấm để tiếp tục âm thanh',
  reconnecting: 'Mất kết nối với chương trình trên máy — đang thử lại…',
} as const;

export const STATE_VI: Record<string, string> = {
  IDLE: 'Chưa bật',
  CONNECTING: 'Đang kết nối chương trình trên máy…',
  DISCOVERING: 'Đang tìm phụ đề…',
  WARMING: 'Đang nạp mô hình dịch…',
  BUFFERING: 'Đang chuẩn bị câu tiếp theo…',
  PLAYING: 'Đang thuyết minh',
  PAUSED_USER: 'Đã dừng theo thao tác của bạn',
  PAUSED_AUTO: 'Đang đọc hết câu',
  SEEKING: 'Đang chuẩn bị vị trí mới…',
  AD_HOLD: 'Video đang phát quảng cáo',
  STALLED: 'Video đang tải…',
  SOURCE_LOST: 'Mất nguồn phụ đề',
  RECONNECTING: 'Đang kết nối lại…',
  ERROR: 'Có lỗi — xem hướng dẫn bên dưới',
  STOPPED: 'Đã tắt',
};

/** Nhãn chất lượng nguồn phụ đề (học từ YouTube Dubbing): giải thích vì sao có đoạn dịch kém. */
export type SourceKind = 'manual' | 'auto' | 'import' | 'asr';
export const SOURCE_QUALITY: Record<SourceKind, { label: string; hint: string; level: 'ok' | 'warn' | 'err'; dot: string }> = {
  manual: { label: 'Phụ đề của tác giả', hint: 'Nguồn tốt nhất cho bản dịch.', level: 'ok', dot: '#7ee2a8' },
  import: { label: 'Phụ đề bạn nhập', hint: 'Dùng đúng tệp bạn đã chọn.', level: 'ok', dot: '#7ee2a8' },
  auto: { label: 'Phụ đề YouTube tự tạo', hint: 'Có thể sai chữ, thiếu dấu câu nên bản dịch có thể kém hơn.', level: 'warn', dot: '#fdd663' },
  asr: { label: 'Máy bạn nghe và chép lại', hint: 'Chậm vài giây so với hình, đôi khi nghe sai.', level: 'warn', dot: '#fdd663' },
};

export const MODE_VI: Record<string, string> = {
  vod_sync: 'Đồng bộ theo phụ đề',
  live_delayed: 'Trực tiếp có độ trễ',
  study: 'Học kỹ',
};

export const ERROR_ACTION_VI: Record<string, string> = {
  CONNECT_FAILED: 'Mở VietDub Local trên khay hệ thống rồi bấm Kết nối lại.',
  AUTH_REQUIRED: 'Bấm Kết nối lại.',
  AUTH_EXPIRED: 'Bấm Kết nối lại.',
  MODEL_NOT_READY: 'Mở tab Mô hình để tải hoặc nạp mô hình.',
  GPU_OOM: 'Đóng bớt phần mềm dùng GPU hoặc chuyển Qwen nhẹ (Q4) đã tải.',
  LIVE_QUEUE_OVERFLOW: 'Bấm "Tiếp tục từ vị trí hiện tại" — đoạn giữa sẽ không được đọc.',
  PERMISSION_DENIED: 'Bấm biểu tượng VietDub trên thanh công cụ, rồi thử Dịch âm thanh tab lại.',
  VOICE_NOT_FOUND: 'Chọn giọng khác trong tab Cài đặt.',
  NATIVE_HOST_MISSING: 'Chưa cài chương trình VietDub Local trên máy (hoặc cài sai). Chạy lại bộ cài rồi bấm Kết nối lại.',
};
