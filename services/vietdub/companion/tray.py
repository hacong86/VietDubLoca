"""Companion trên khay hệ thống (FR-004): chạy broker (tiến trình con trong Job Object), trạng thái, thoát sạch.

Thoát → broker nhận /internal/shutdown → dừng thu/phát, worker con; Job Object bảo đảm không còn tiến trình mồ côi.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from ..paths import default_paths
from ..runtime import jobobject
from . import startup

_proc: subprocess.Popen | None = None


def _icon_image(color: tuple[int, int, int]):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, 60, 60), 14, fill=(28, 36, 52, 255))
    d.polygon([(22, 18), (22, 46), (46, 32)], fill=color + (255,))
    return img


def start_broker(paths) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    env["VIETDUB_HOME"] = str(paths.home)
    py = Path(sys.executable)
    exe = py.with_name("python.exe") if py.name.lower() == "pythonw.exe" and py.with_name("python.exe").exists() else py
    p = subprocess.Popen([str(exe), "-B", "-m", "vietdub.broker.main"], cwd=str(paths.home), env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=open(paths.logs / "broker-stderr.log", "ab"), creationflags=0x08000000)
    jobobject.assign(p.pid)
    return p


def broker_status(paths) -> str:
    try:
        st = json.loads(paths.broker_state.read_text(encoding="utf-8"))
        r = httpx.get(f"http://127.0.0.1:{st['port']}/health", timeout=1, trust_env=False)
        return "ok" if r.status_code == 200 else "down"
    except Exception:
        return "down"


def shutdown_broker(paths) -> None:
    global _proc
    try:
        st = json.loads(paths.broker_state.read_text(encoding="utf-8"))
        httpx.post(f"http://127.0.0.1:{st['port']}/internal/shutdown", timeout=5, trust_env=False,
                   headers={"X-VietDub-Pairing": st["pairing_secret"]})
    except Exception:
        pass
    if _proc:
        try:
            _proc.wait(15)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None


def main() -> None:
    global _proc
    paths = default_paths().ensure()
    lock = paths.runtime / "tray.lock"
    try:  # một instance
        fd = os.open(lock, os.O_CREAT | os.O_RDWR)
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError:
        return
    if broker_status(paths) != "ok":
        _proc = start_broker(paths)
    import pystray

    def on_quit(icon, _item):
        icon.title = "VietDub Local — đang thoát…"
        shutdown_broker(paths)
        icon.stop()

    def on_restart(icon, _item):
        global _proc
        shutdown_broker(paths)
        _proc = start_broker(paths)

    def on_startup(icon, _item):
        startup.set_enabled(not startup.is_enabled())

    def on_open_logs(icon, _item):
        os.startfile(str(paths.logs))  # noqa: S606 — thư mục cố định của app

    menu = pystray.Menu(
        pystray.MenuItem(lambda _i: f"Trạng thái: {'Đang chạy' if broker_status(paths) == 'ok' else 'Đang khởi động/tắt'}",
                         None, enabled=False),
        pystray.MenuItem("Khởi động lại bộ xử lý", on_restart),
        pystray.MenuItem("Khởi động cùng Windows", on_startup, checked=lambda _i: startup.is_enabled()),
        pystray.MenuItem("Mở thư mục nhật ký", on_open_logs),
        pystray.MenuItem("Thoát VietDub Local", on_quit),
    )
    icon = pystray.Icon("VietDubLocal", _icon_image((96, 200, 120)), "VietDub Local", menu)

    def watch():
        while True:
            time.sleep(3)
            ok = broker_status(paths) == "ok"
            icon.icon = _icon_image((96, 200, 120) if ok else (230, 180, 60))
            icon.title = "VietDub Local — AI chạy trên máy" if ok else "VietDub Local — bộ xử lý chưa sẵn sàng"

    threading.Thread(target=watch, daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()
