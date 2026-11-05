"""Model manager (FR-002, docs/16 §Lấy model, docs/11 §Giới hạn và đường dẫn).

- Chỉ tải artifact trong catalog đã ghim revision; host allowlist; redirect chỉ tới host allowlist.
- Ghi ``.part``, resume bằng HTTP Range, pause/cancel giữ ``.part``; ``.part`` KHÔNG bao giờ được nạp.
- Xác minh size + sha256 (LFS) hoặc git blob sha1 (tệp nhỏ) trước khi đổi tên thành tệp chính.
- Checksum sai → đổi thành ``.corrupt``, báo MODEL_CHECKSUM_MISMATCH, không nạp.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import ssl
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from ..errors import AppError
from ..hashing import file_sha256
from ..paths import REPO_ROOT, AppPaths

ALLOWED_DOMAINS = ("huggingface.co", "hf.co")


def host_allowed(host: str) -> bool:
    """Chỉ HuggingFace và CDN chính thức (*.hf.co, *.huggingface.co)."""
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)


def system_tls() -> ssl.SSLContext:
    """TLS xác minh bằng kho chứng chỉ của Windows (tin CA nội bộ/antivirus do người dùng cài), KHÔNG tắt verify."""
    return ssl.create_default_context()


CATALOG_FILE = REPO_ROOT / "config" / "model-catalog.json"
CHUNK = 1024 * 1024


def load_catalog() -> dict[str, dict[str, Any]]:
    cat = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    return {m["id"]: m for m in cat["models"]}


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


@dataclass
class DownloadJob:
    job_id: str
    model_id: str
    state: str = "queued"          # queued | running | paused | verifying | done | failed | cancelled
    bytes_done: int = 0
    bytes_total: int = 0
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    task: asyncio.Task | None = None
    pause_requested: bool = False
    error_detail: str | None = None


class ModelManager:
    def __init__(self, paths: AppPaths, *, on_progress: Callable[[dict[str, Any]], None] | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.paths = paths
        self.catalog = load_catalog()
        self.jobs: dict[str, DownloadJob] = {}
        self.on_progress = on_progress or (lambda _e: None)
        self._transport = transport

    # ---------- đường dẫn ----------
    def file_path(self, m: dict[str, Any], rel: str) -> Path:
        if ".." in Path(rel).parts or Path(rel).is_absolute():
            raise ValueError("bad catalog path")
        if m["kind"] == "translation":
            base = self.paths.translation_models
        elif m["kind"] == "asr":
            base = self.paths.asr_models / m["id"]
        else:  # tts/tts_dep: layout HF hub để SDK đọc offline
            org, name = m["repo"].split("/")
            base = self.paths.hf_home / "hub" / f"models--{org}--{name}" / "snapshots" / m["revision"]
        return self.paths.inside(base / rel, self.paths.models)

    def asr_dir(self, model_id: str) -> Path:
        return self.paths.asr_models / model_id

    def translation_file(self, model_id: str) -> Path:
        m = self.catalog[model_id]
        return self.file_path(m, m["files"][0]["path"])

    def _ensure_hf_refs(self, m: dict[str, Any]) -> None:
        if m["kind"] in ("tts", "tts_dep"):
            org, name = m["repo"].split("/")
            ref = self.paths.hf_home / "hub" / f"models--{org}--{name}" / "refs" / "main"
            ref.parent.mkdir(parents=True, exist_ok=True)
            ref.write_text(m["revision"], encoding="utf-8")

    # ---------- trạng thái ----------
    def verify_file(self, f: dict[str, Any], p: Path, *, full_hash: bool) -> tuple[bool, str]:
        if not p.is_file():
            return False, "missing"
        if p.stat().st_size != f["size"]:
            return False, "size_mismatch"
        if not full_hash:
            return True, "size_ok"
        if f.get("sha256"):
            return (file_sha256(p) == f["sha256"]), "sha256"
        if f.get("git_sha1"):
            return (git_blob_sha1(p) == f["git_sha1"]), "git_sha1"
        return False, "no_reference_hash"

    def status(self, model_id: str, *, full_hash: bool = False, verified_cache: dict[str, bool] | None = None) -> dict[str, Any]:
        m = self.catalog[model_id]
        files = []
        present = 0
        partial = 0
        for f in m["files"]:
            p = self.file_path(m, f["path"])
            ok, how = self.verify_file(f, p, full_hash=full_hash)
            if ok:
                present += 1
            if p.with_name(p.name + ".part").exists():
                partial += 1
            files.append({"path": f["path"], "ok": ok, "check": how})
        job = next((j for j in self.jobs.values() if j.model_id == model_id and j.state in
                    ("queued", "running", "paused", "verifying")), None)
        verified = bool(verified_cache.get(model_id)) if verified_cache else False
        if present == len(m["files"]):
            state = "verified" if (full_hash or verified) else "present_unverified"
        elif job:
            state = job.state
        elif partial:
            state = "partial"
        else:
            state = "not_downloaded"
        return {"model_id": model_id, "kind": m["kind"], "label_vi": m.get("label_vi"), "quant": m.get("quant"),
                "repo": m["repo"], "revision": m["revision"], "size_bytes": m["size_bytes"],
                "approx_decimal_gb": m.get("approx_decimal_gb"), "license": m.get("license"), "role": m.get("role"),
                "state": state, "files": files,
                "download": ({"job_id": job.job_id, "state": job.state, "bytes_done": job.bytes_done,
                              "bytes_total": job.bytes_total} if job else None)}

    def verify_full(self, model_id: str) -> bool:
        m = self.catalog[model_id]
        for f in m["files"]:
            ok, _ = self.verify_file(f, self.file_path(m, f["path"]), full_hash=True)
            if not ok:
                return False
        self._ensure_hf_refs(m)
        return True

    # ---------- tải ----------
    def start_download(self, model_id: str, *, consent: bool, accepted_size_bytes: int | None) -> DownloadJob:
        if model_id not in self.catalog:
            raise AppError("NOT_FOUND", {"model_id": model_id})
        m = self.catalog[model_id]
        if not consent or accepted_size_bytes != m["size_bytes"]:
            raise AppError("CONSENT_REQUIRED", {"model_id": model_id, "expected": m["size_bytes"]})
        for j in self.jobs.values():
            if j.model_id == model_id and j.state in ("queued", "running", "verifying"):
                return j
        free = shutil.disk_usage(self.paths.models).free
        if free < m["size_bytes"] * 1.1:
            raise AppError("CACHE_DISK_FULL", {"model_id": model_id})
        job = DownloadJob(f"dl-{model_id}-{int(time.time()*1000)}", model_id, bytes_total=m["size_bytes"])
        self.jobs[job.job_id] = job
        job.task = asyncio.create_task(self._run(job, m))
        return job

    def pause(self, job_id: str) -> None:
        j = self.jobs.get(job_id)
        if j and j.state in ("queued", "running"):
            j.pause_requested = True

    def _emit(self, j: DownloadJob) -> None:
        self.on_progress({"job_id": j.job_id, "model_id": j.model_id, "state": j.state, "bytes_done": j.bytes_done,
                          "bytes_total": j.bytes_total, "error": j.error})

    async def _run(self, j: DownloadJob, m: dict[str, Any]) -> None:
        j.state = "running"
        self._emit(j)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=120), follow_redirects=False,
                                         trust_env=False, transport=self._transport,
                                         verify=system_tls()) as cli:
                done_before = 0
                for f in m["files"]:
                    dst = self.file_path(m, f["path"])
                    ok, _ = self.verify_file(f, dst, full_hash=False)
                    if ok:
                        done_before += f["size"]
                        j.bytes_done = done_before
                        continue
                    await self._fetch(cli, j, m, f, dst, done_before)
                    if j.pause_requested:
                        j.state = "paused"
                        self._emit(j)
                        return
                    done_before += f["size"]
            j.state = "verifying"
            self._emit(j)
            ok = await asyncio.to_thread(self.verify_full, m["id"])
            if not ok:
                raise AppError("MODEL_CHECKSUM_MISMATCH", {"model_id": m["id"]})
            j.state = "done"
        except AppError as e:
            j.state, j.error = "failed", e.code
        except (httpx.HTTPError, OSError) as e:
            j.state, j.error = "failed", "CONNECT_FAILED"
            j.error_detail = f"{type(e).__name__}: {str(e)[:160]}"
        except asyncio.CancelledError:
            j.state = "cancelled"
            raise
        finally:
            self._emit(j)

    async def _fetch(self, cli: httpx.AsyncClient, j: DownloadJob, m: dict[str, Any], f: dict[str, Any],
                     dst: Path, done_before: int) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        part = dst.with_name(dst.name + ".part")
        have = part.stat().st_size if part.exists() else 0
        if have > f["size"]:
            part.unlink()
            have = 0
        url = f"https://huggingface.co/{m['repo']}/resolve/{m['revision']}/{f['path']}"
        headers = {"Range": f"bytes={have}-"} if have else {}
        for _ in range(5):                       # theo redirect thủ công, chỉ trong allowlist
            host = urlsplit(url).hostname or ""
            if urlsplit(url).scheme != "https" or not host_allowed(host):
                raise AppError("CONNECT_FAILED", {"reason": "host_not_allowed"})
            req = cli.build_request("GET", url, headers=headers)
            resp = await cli.send(req, stream=True)
            if resp.status_code in (301, 302, 303, 307, 308):
                url = httpx.URL(url).join(resp.headers["location"]).__str__()
                await resp.aclose()
                continue
            break
        else:
            raise AppError("CONNECT_FAILED", {"reason": "too_many_redirects"})
        try:
            if resp.status_code == 416 and have == f["size"]:
                pass
            elif resp.status_code == 200 and have:
                have = 0                         # server bỏ qua Range → tải lại từ đầu
                part.unlink(missing_ok=True)
            elif resp.status_code not in (200, 206):
                raise AppError("CONNECT_FAILED", {"reason": f"http_{resp.status_code}"})
            if resp.status_code != 416:
                with open(part, "ab") as out:
                    async for chunk in resp.aiter_bytes(CHUNK):
                        out.write(chunk)
                        have += len(chunk)
                        j.bytes_done = done_before + have
                        if have > f["size"]:
                            raise AppError("MODEL_CHECKSUM_MISMATCH", {"reason": "oversize"})
                        if j.pause_requested:
                            self._emit(j)
                            return
                        if int(time.time() * 4) % 4 == 0:
                            self._emit(j)
                    out.flush()
                    os.fsync(out.fileno())
        finally:
            await resp.aclose()
        if have != f["size"]:
            raise AppError("CONNECT_FAILED", {"reason": "short_read"})
        ok, _ = await asyncio.to_thread(self.verify_file, f, part, full_hash=True)
        if not ok:
            part.replace(dst.with_name(dst.name + ".corrupt"))
            raise AppError("MODEL_CHECKSUM_MISMATCH", {"model_id": m["id"]})
        os.replace(part, dst)

    # ---------- nhập tệp local ----------
    async def import_file(self, model_id: str, src: Path) -> bool:
        """Nhập tệp người dùng chọn bằng hộp thoại của companion (không nhận path từ trình duyệt)."""
        m = self.catalog[model_id]
        if m["kind"] != "translation" or len(m["files"]) != 1:
            raise AppError("VALIDATION_FAILED", {"model_id": model_id})
        f = m["files"][0]
        src = src.resolve()
        if str(src).startswith("\\\\") or src.is_symlink() or not src.is_file():
            raise AppError("VALIDATION_FAILED", {"field": "file"})
        ok, _ = await asyncio.to_thread(self.verify_file, f, src, full_hash=True)
        if not ok:
            raise AppError("MODEL_CHECKSUM_MISMATCH", {"model_id": model_id})
        dst = self.file_path(m, f["path"])
        tmp = dst.with_name(dst.name + ".part")
        await asyncio.to_thread(shutil.copyfile, src, tmp)
        ok, _ = await asyncio.to_thread(self.verify_file, f, tmp, full_hash=True)
        if not ok:
            tmp.unlink(missing_ok=True)
            raise AppError("MODEL_CHECKSUM_MISMATCH", {"model_id": model_id})
        os.replace(tmp, dst)
        return True

    def delete(self, model_id: str, *, active_ids: set[str]) -> None:
        if model_id in active_ids:
            raise AppError("REVISION_CONFLICT", {"model_id": model_id, "reason": "in_use"})
        m = self.catalog[model_id]
        for f in m["files"]:
            p = self.file_path(m, f["path"])
            for q in (p, p.with_name(p.name + ".part"), p.with_name(p.name + ".corrupt")):
                q.unlink(missing_ok=True)
