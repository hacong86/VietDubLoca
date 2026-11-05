"""Native Messaging host ``com.vietdub.local`` (docs/08 §6, docs/11; FR-003).

Chrome khởi chạy với argv[1] = origin của extension gọi. Khung: uint32 native-endian + JSON UTF-8 (≤ 64 KiB).
stdout CHỈ chứa khung giao thức; log sang stderr/file. Lệnh cố định: hello, start, status, stop_owned_processes.
Không nhận exe/args/path từ extension.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

import httpx

from . import APP_VERSION, PROTOCOL_VERSION
from .paths import default_paths

MAX_MSG = 64 * 1024


def read_msg(stdin) -> dict | None:
    raw = stdin.read(4)
    if len(raw) < 4:
        return None
    n = struct.unpack("=I", raw)[0]
    if n > MAX_MSG:
        raise ValueError("message too large")
    data = stdin.read(n)
    obj = json.loads(data.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("not object")
    return obj


def write_msg(stdout, obj: dict) -> None:
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_MSG:
        data = json.dumps({"type": "error", "code": "PAYLOAD_TOO_LARGE"}).encode()
    stdout.write(struct.pack("=I", len(data)) + data)
    stdout.flush()


def allowed_origins(paths) -> set[str]:
    try:
        cfg = json.loads(paths.local_config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return set()
    ids = cfg.get("allowed_extension_ids") or []
    if isinstance(ids, str):  # PowerShell 5.1 ConvertTo-Json bóc mảng 1 phần tử
        ids = [ids]
    return {f"chrome-extension://{i}/" for i in ids if isinstance(i, str) and len(i) == 32}


def broker_state(paths) -> dict | None:
    try:
        st = json.loads(paths.broker_state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        r = httpx.get(f"http://127.0.0.1:{int(st['port'])}/health", timeout=1.5, trust_env=False,
                      headers={"Host": f"127.0.0.1:{int(st['port'])}"})
        if r.status_code == 200 and r.json().get("protocol_version") == PROTOCOL_VERSION:
            return st
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    return None


def launch_companion(paths) -> None:
    """Chạy tray/companion tách khỏi tiến trình host (host bị Chrome đóng khi port ngắt)."""
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    exe = pyw if pyw.exists() else py
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env["VIETDUB_HOME"] = str(paths.home)
    flags = 0x00000008 | 0x00000200 | 0x01000000 | 0x08000000  # DETACHED | NEW_GROUP | BREAKAWAY | NO_WINDOW
    try:
        subprocess.Popen([str(exe), "-B", "-m", "vietdub.companion.tray"], cwd=str(paths.home), env=env,
                         creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
    except OSError:
        subprocess.Popen([str(exe), "-B", "-m", "vietdub.companion.tray"], cwd=str(paths.home), env=env,
                         creationflags=flags & ~0x01000000, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)


def pair(st: dict, origin: str) -> dict:
    port = int(st["port"])
    r = httpx.post(f"http://127.0.0.1:{port}/internal/pair", timeout=5, trust_env=False,
                   headers={"X-VietDub-Pairing": st["pairing_secret"], "Host": f"127.0.0.1:{port}"},
                   json={"extension_origin": origin.rstrip("/")})
    if r.status_code != 200:
        return {"type": "error", "code": (r.json() or {}).get("code", "AUTH_REQUIRED")}
    d = r.json()
    return {"type": "paired", "broker_url": d["broker_url"], "session_token": d["session_token"],
            "expires_at": d["expires_at"], "protocol_version": d["protocol_version"]}


def handle(msg: dict, origin: str, paths) -> dict:
    t = msg.get("type")
    if t == "hello":
        return {"type": "hello", "protocol_version": PROTOCOL_VERSION, "app_version": APP_VERSION,
                "compatible": msg.get("protocol_version") == PROTOCOL_VERSION}
    if t == "status":
        st = broker_state(paths)
        return {"type": "status", "running": bool(st), "port": st["port"] if st else None}
    if t == "start":
        st = broker_state(paths)
        if not st:
            launch_companion(paths)
            deadline = time.time() + 90
            while time.time() < deadline and not st:
                time.sleep(0.5)
                st = broker_state(paths)
        if not st:
            return {"type": "error", "code": "CONNECT_FAILED"}
        return pair(st, origin)
    if t == "stop_owned_processes":
        st = broker_state(paths)
        if st:
            try:
                httpx.post(f"http://127.0.0.1:{int(st['port'])}/internal/shutdown", timeout=5, trust_env=False,
                           headers={"X-VietDub-Pairing": st["pairing_secret"], "Host": f"127.0.0.1:{int(st['port'])}"})
            except httpx.HTTPError:
                pass
        return {"type": "stopped"}
    return {"type": "error", "code": "VALIDATION_FAILED"}


def main() -> int:
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    sys.stdout = sys.stderr
    origin = sys.argv[1] if len(sys.argv) > 1 else ""
    paths = default_paths().ensure()
    if origin not in allowed_origins(paths):
        write_msg(stdout, {"type": "error", "code": "ORIGIN_DENIED"})
        return 1
    while True:
        try:
            msg = read_msg(stdin)
        except (ValueError, json.JSONDecodeError):
            write_msg(stdout, {"type": "error", "code": "VALIDATION_FAILED"})
            return 1
        if msg is None:
            return 0
        write_msg(stdout, handle(msg, origin, paths))


if __name__ == "__main__":
    raise SystemExit(main())
