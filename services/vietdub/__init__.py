"""VietDub Local — companion: broker, translation, storage, model manager, worker IPC.

Workers (``vietdub.workers``) chạy bằng interpreter khác (venv TTS/ASR) nên chỉ được import
thư viện chuẩn + ``vietdub.workers.ipc``; không import module broker từ worker.
"""

APP_VERSION = "0.1.5"
PROTOCOL_VERSION = 1
