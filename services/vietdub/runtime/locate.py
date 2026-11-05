"""Định vị runtime ngoài Python broker: python TTS/ASR, llama-server. Cấu hình ở ``<home>/local-config.json``.

Bản cài có venv riêng dưới ``<home>/runtime``. Môi trường có sẵn chỉ được dùng khi cấu hình rõ đường dẫn.
Không nhận đường dẫn từ extension/page — chỉ từ tệp cấu hình cục bộ do installer/người dùng máy tạo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..paths import AppPaths

DEFAULTS = {
    "tts_python": ["{home}/runtime/venv-tts/Scripts/python.exe"],
    "asr_python": ["{home}/runtime/venv-asr/Scripts/python.exe"],
    "llama_server": ["{home}/runtime/llama/b11126-cuda13.4/llama-server.exe"],
}


@dataclass
class Runtimes:
    tts_python: Path | None
    asr_python: Path | None
    llama_server: Path | None
    llama_build: str | None
    source: dict[str, str]


def _first(cands: list[str], home: Path) -> Path | None:
    for c in cands:
        p = Path(c.replace("{home}", str(home)))
        if p.is_file():
            return p
    return None


def load(paths: AppPaths) -> Runtimes:
    cfg: dict = {}
    try:
        cfg = json.loads(paths.local_config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        cfg = {}
    src: dict[str, str] = {}
    out: dict[str, Path | None] = {}
    for key, cands in DEFAULTS.items():
        val = cfg.get(key)
        if isinstance(val, str) and Path(val).is_file():
            out[key] = Path(val)
            src[key] = "local-config"
        else:
            out[key] = _first(cands, paths.home)
            src[key] = "default" if out[key] else "missing"
    llama = out["llama_server"]
    build = cfg.get("llama_build") or (llama.parent.name if llama else None)
    return Runtimes(out["tts_python"], out["asr_python"], llama, build, src)
