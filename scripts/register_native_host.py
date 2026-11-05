"""Đăng ký Native Messaging host com.vietdub.local cho user hiện tại (HKCU, không cần admin) — docs/16, S18.

python scripts/register_native_host.py [--python <python.exe>] [--home D:/VietDubLocal] [--unregister]
Ghi manifest + launcher .cmd vào <home>/runtime/native (không ghi vào ổ C). allowed_origins đúng extension ID.
"""
from __future__ import annotations

import argparse
import json
import sys
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "com.vietdub.local"
KEYS = [r"Software\Google\Chrome\NativeMessagingHosts", r"Software\Chromium\NativeMessagingHosts",
        r"Software\Microsoft\Edge\NativeMessagingHosts"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", default=str(ROOT / ".venv-broker" / "Scripts" / "python.exe"))
    ap.add_argument("--home", default="D:/VietDubLocal")
    ap.add_argument("--services", default=str(ROOT / "services"))
    ap.add_argument("--unregister", action="store_true")
    a = ap.parse_args()
    if a.unregister:
        for k in KEYS:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, k + "\\" + HOST)
                print("removed", k)
            except FileNotFoundError:
                pass
        return 0
    home = Path(a.home)
    cfg = json.loads((home / "local-config.json").read_text(encoding="utf-8"))
    ids = cfg.get("allowed_extension_ids") or []
    if not ids:
        print("local-config.json thiếu allowed_extension_ids", file=sys.stderr)
        return 2
    ndir = home / "runtime" / "native"
    ndir.mkdir(parents=True, exist_ok=True)
    launcher = ndir / "vietdub-native-host.cmd"
    # @echo off: stdout chỉ còn khung giao thức của Python
    launcher.write_text("@echo off\r\n"
                        f'set "PYTHONPATH={Path(a.services)}"\r\n'
                        f'set "VIETDUB_HOME={home}"\r\n'
                        "set PYTHONIOENCODING=utf-8\r\n"
                        f'"{Path(a.python)}" -B -m vietdub.native_host %*\r\n', encoding="utf-8")
    manifest = {"name": HOST, "description": "VietDub Local companion bootstrap", "path": str(launcher), "type": "stdio",
                "allowed_origins": [f"chrome-extension://{i}/" for i in ids]}
    mpath = ndir / f"{HOST}.json"
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for k in KEYS:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, k + "\\" + HOST) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(mpath))
        print("registered", k, "->", mpath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
