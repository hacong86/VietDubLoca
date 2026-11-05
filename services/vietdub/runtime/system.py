"""Kiểm tra môi trường (FR-001, UI-02): OS/RAM/ổ đĩa/GPU/driver/VRAM đo thật (nvidia-smi), runtime, model.
Không suy VRAM trống từ nhãn GPU. Mỗi mục có nguồn đo và hành động sửa."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

import psutil

def gpu_info() -> dict[str, Any]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {"available": False, "source": "nvidia-smi không có", "action_vi": "Cài driver NVIDIA mới."}
    try:
        out = subprocess.run([exe, "--query-gpu=name,driver_version,memory.total,memory.used,memory.free,utilization.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                             creationflags=0x08000000).stdout.strip().splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "source": "nvidia-smi lỗi", "action_vi": "Khởi động lại máy hoặc cài lại driver."}
    if not out:
        return {"available": False, "source": "nvidia-smi rỗng"}
    name, drv, tot, used, free, util = [x.strip() for x in out[0].split(",")]
    return {"available": True, "name": name, "driver": drv, "vram_total_mb": int(tot), "vram_used_mb": int(used),
            "vram_free_mb": int(free), "utilization_pct": int(util) if util.isdigit() else None,
            "source": "nvidia-smi (đo lúc này)"}


def gpu_processes() -> list[dict[str, Any]]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, creationflags=0x08000000).stdout.strip().splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return []
    res = []
    for line in out:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[0].isdigit():
            res.append({"pid": int(parts[0]), "name": Path(parts[1]).name, "used_mb": int(parts[2]) if parts[2].isdigit() else None})
    return res


def env_report(home: Path, runtimes: Any, model_states: dict[str, str]) -> dict[str, Any]:
    vm = psutil.virtual_memory()
    du = shutil.disk_usage(home)
    items: list[dict[str, Any]] = []

    def add(key: str, ok: bool, value: Any, source: str, action: str | None = None) -> None:
        items.append({"key": key, "ok": ok, "value": value, "source": source, "action_vi": None if ok else action})

    add("os", platform.machine().lower() in ("amd64", "x86_64"), f"{platform.system()} {platform.release()} {platform.machine()}",
        "platform", "Cần Windows 64-bit.")
    add("ram", vm.total >= 16 * 1024 ** 3, {"total_gb": round(vm.total / 1024 ** 3, 1), "free_gb": round(vm.available / 1024 ** 3, 1)},
        "psutil", "Cần ít nhất 16 GB RAM.")
    add("disk", du.free > 5 * 1024 ** 3, {"path": str(home.drive or home), "free_gb": round(du.free / 1024 ** 3, 1)},
        "shutil.disk_usage", "Giải phóng ổ chứa dữ liệu VietDub (ít nhất 5 GB).")
    g = gpu_info()
    add("gpu", bool(g.get("available")), g, g.get("source", ""), g.get("action_vi") or "Cần GPU NVIDIA có driver.")
    add("llama_runtime", bool(runtimes.llama_server), str(runtimes.llama_server) if runtimes.llama_server else None,
        runtimes.source.get("llama_server", ""), "Cài lại VietDub Local (thiếu llama-server).")
    add("tts_runtime", bool(runtimes.tts_python), bool(runtimes.tts_python), runtimes.source.get("tts_python", ""),
        "Cài lại VietDub Local (thiếu môi trường giọng đọc).")
    add("asr_runtime", bool(runtimes.asr_python), bool(runtimes.asr_python), runtimes.source.get("asr_python", ""),
        "Cài lại VietDub Local (thiếu môi trường nhận dạng giọng nói).")
    for mid, st in model_states.items():
        add(f"model:{mid}", st == "verified", st, "model manager (sha256)", "Mở Quản lý mô hình để tải hoặc kiểm tra lại.")
    procs = gpu_processes()
    others = [p for p in procs if p["pid"] != os.getpid()]
    items.append({"key": "gpu_processes", "ok": True, "value": others, "source": "nvidia-smi --query-compute-apps",
                  "action_vi": None})
    required = {"os", "ram", "disk", "gpu", "llama_runtime", "tts_runtime"}
    has_translation = any(i["ok"] for i in items if i["key"].startswith("model:") and
                          ("qwen" in i["key"] or "gemma" in i["key"]))
    ready = all(i["ok"] for i in items if i["key"] in required) and has_translation
    return {"ready": ready, "items": items, "process_rss_mb": round(psutil.Process(os.getpid()).memory_info().rss / 2 ** 20)}
