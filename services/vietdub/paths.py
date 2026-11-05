"""Vị trí dữ liệu. Mặc định KHÔNG dùng ổ C (ADR-010): mọi model/cache/db/log/tmp nằm dưới data root.

Thứ tự tìm data root:
1. biến môi trường ``VIETDUB_HOME``;
2. tệp ``vietdub-home.txt`` cạnh thư mục cài đặt (installer ghi);
3. ``D:\\VietDubLocal`` nếu ổ D tồn tại;
4. ``%LOCALAPPDATA%\\VietDubLocal``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_DIR = REPO_ROOT / "services"
HOME_POINTER = "vietdub-home.txt"


def _pointer_candidates() -> list[Path]:
    here = Path(__file__).resolve()
    return [p / HOME_POINTER for p in (here.parents[2], here.parents[3])]


def resolve_home() -> Path:
    env = os.environ.get("VIETDUB_HOME")
    if env:
        return Path(env)
    for cand in _pointer_candidates():
        try:
            text = cand.read_text(encoding="utf-8-sig").strip()
        except OSError:
            continue
        if text:
            return Path(text)
    if Path("D:/").exists():
        return Path("D:/VietDubLocal")
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "VietDubLocal"


@dataclass(frozen=True)
class AppPaths:
    home: Path

    @property
    def models(self) -> Path: return self.home / "models"
    @property
    def translation_models(self) -> Path: return self.models / "translation"
    @property
    def hf_home(self) -> Path: return self.models / "hf"
    @property
    def asr_models(self) -> Path: return self.models / "asr"
    @property
    def cache(self) -> Path: return self.home / "cache"
    @property
    def audio_cache(self) -> Path: return self.cache / "audio"
    @property
    def db_dir(self) -> Path: return self.home / "db"
    @property
    def db_file(self) -> Path: return self.db_dir / "vietdub.sqlite3"
    @property
    def logs(self) -> Path: return self.home / "logs"
    @property
    def runtime(self) -> Path: return self.home / "runtime"
    @property
    def tmp(self) -> Path: return self.home / "tmp"
    @property
    def exports(self) -> Path: return self.home / "exports"
    @property
    def diagnostics(self) -> Path: return self.home / "diagnostics"
    @property
    def backups(self) -> Path: return self.home / "backups"
    @property
    def broker_state(self) -> Path: return self.runtime / "broker.json"
    @property
    def llama_key(self) -> Path: return self.runtime / "llama.key"
    @property
    def local_config(self) -> Path: return self.home / "local-config.json"

    def ensure(self) -> "AppPaths":
        for d in (self.translation_models, self.hf_home, self.asr_models, self.audio_cache, self.db_dir,
                  self.logs, self.runtime, self.tmp, self.exports, self.diagnostics, self.backups,
                  self.cache / "cuda", self.cache / "torch", self.cache / "triton"):
            d.mkdir(parents=True, exist_ok=True)
        return self

    def inside(self, candidate: Path, root: Path | None = None) -> Path:
        """Resolve ``candidate`` và bảo đảm nằm trong ``root`` (mặc định home). Chặn .., UNC, junction."""
        base = (root or self.home).resolve()
        raw = str(candidate)
        if raw.startswith("\\\\") or raw.startswith("//"):
            raise ValueError("UNC/network path bị chặn")
        resolved = (base / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if resolved != base and base not in resolved.parents:
            raise ValueError("Đường dẫn nằm ngoài thư mục ứng dụng")
        return resolved


def worker_env(paths: AppPaths, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Env cho tiến trình con: mọi cache trỏ về data root trên ổ D, không đụng cache Hermes."""
    env = dict(os.environ)
    c = paths.cache
    env.update({
        "HF_HOME": str(paths.hf_home),
        "HF_HUB_OFFLINE": "1",          # sau provisioning không tải gì khi đang xem
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",  # không ghi __pycache__ vào venv mượn của Hermes
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "CUDA_CACHE_PATH": str(c / "cuda"),
        "TORCH_HOME": str(c / "torch"),
        "TORCHINDUCTOR_CACHE_DIR": str(c / "torch" / "inductor"),
        "TRITON_CACHE_DIR": str(c / "triton"),
        "XDG_CACHE_HOME": str(c),
        "TMP": str(paths.tmp),
        "TEMP": str(paths.tmp),
        "PYTHONPATH": str(SERVICES_DIR),
    })
    if extra:
        env.update(extra)
    return env


def default_paths() -> AppPaths:
    return AppPaths(resolve_home())
