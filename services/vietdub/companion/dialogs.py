"""Hộp thoại chọn tệp trên máy (companion) — đường dẫn đến từ người dùng máy, không từ trình duyệt."""
from __future__ import annotations

from pathlib import Path


def pick_file(title: str, types: list[tuple[str, str]]) -> Path | None:
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        p = filedialog.askopenfilename(title=title, filetypes=types + [("Tất cả", "*.*")])
    finally:
        root.destroy()
    return Path(p) if p else None
