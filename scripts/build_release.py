"""Tạo gói phát hành Windows (FR-040, docs/16): thư mục + zip + SHA256SUMS. Chỉ dùng stdlib.

python scripts/build_release.py [--version 0.1.0] [--out dist/release] [--uv <uv.exe>] [--rehash <thư mục gói>]
- Extension phải build trước (`node apps/extension/build.mjs`).
- `--rehash` tính lại release-manifest.json cho thư mục gói đã có (dùng trong test cập nhật/rollback).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import sys
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services"))
from vietdub import APP_VERSION  # noqa: E402

APP_TREES = ["services/vietdub", "config", "contracts", "data", "examples", "prompts", "THIRD_PARTY_LICENSES"]
APP_FILES = ["benchmarks/seed_envi.jsonl", "THIRD_PARTY_NOTICES.md", "assets/vietdub.ico", "assets/icon.svg",
             "requirements/broker.lock.txt", "requirements/tts.lock.txt", "requirements/asr.lock.txt", "LICENSE", "NOTICE"]
SKIP = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIX = {".pyc", ".pyo", ".todo.json"}


def extension_id(key: str) -> str:
    """Chrome ID from the public DER key; never reads a private key or local config."""
    raw = base64.b64decode(key, validate=True)
    if len(raw) < 64:
        raise ValueError("Invalid extension public key")
    return "".join(chr(ord("a") + int(c, 16)) for c in hashlib.sha256(raw).hexdigest()[:32])


def remove_build_dir(path: Path, out: Path) -> None:
    if path.is_symlink() or path.resolve().parent != out.resolve() or not path.name.startswith("VietDubLocal-"):
        raise ValueError("Refusing to remove directory outside release output")
    if path.exists():
        shutil.rmtree(path)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def copytree(src: Path, dst: Path) -> None:
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if any(part in SKIP for part in rel.parts) or any(p.name.endswith(s) for s in SKIP_SUFFIX):
            continue
        if p.is_file():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst / rel)


def write_manifest(pkg: Path, version: str, ext_ids: list[str]) -> dict:
    lock = json.loads((ROOT / "config/runtime-lock.json").read_text(encoding="utf-8"))
    files = [{"path": p.relative_to(pkg).as_posix(), "sha256": sha256(p)}
             for p in sorted(pkg.rglob("*")) if p.is_file() and p.name != "release-manifest.json"]
    man = {"name": "VietDub Local", "version": version, "python_version": lock["python_version"].split()[0],
           "extension_ids": ext_ids, "files": files, "llama": lock["llama_runtime"],
           "release_channel": "preview", "release_ready": False}
    (pkg / "release-manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    return man


def zipdir(src: Path, dst: Path) -> None:
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                z.write(p, Path(src.name) / p.relative_to(src))


def write_update_bootstrap(dst: Path) -> None:
    """Single downloadable file for users whose 0.1.1 install has no updater yet."""
    updater = (ROOT / "packaging/windows/update.ps1").read_text(encoding="utf-8-sig")
    source = """Add-Type -AssemblyName System.Windows.Forms
$dialog=New-Object Windows.Forms.FolderBrowserDialog
$dialog.Description='Chọn thư mục đã cài VietDub Local, nơi chứa thư mục app'
if ($dialog.ShowDialog() -ne 'OK') { exit 0 }
$homeDir=$dialog.SelectedPath
$dialog.Dispose()
& {
""" + updater + "\n} -HomeDir $homeDir\n"
    compressor = zlib.compressobj(level=9, wbits=-15)
    packed = base64.b64encode(compressor.compress(source.encode("utf-8")) + compressor.flush()).decode("ascii")
    cmd = ("@echo off\r\nsetlocal\r\npowershell.exe -NoProfile -STA -ExecutionPolicy Bypass -Command "
           '"$b=[Convert]::FromBase64String(\'' + packed + "');"
           "$m=New-Object IO.MemoryStream(,$b);$d=New-Object IO.Compression.DeflateStream($m,[IO.Compression.CompressionMode]::Decompress);"
           "$r=New-Object IO.StreamReader($d,[Text.Encoding]::UTF8);& ([scriptblock]::Create($r.ReadToEnd()))" + '"\r\n')
    if max(map(len, cmd.splitlines())) >= 8191:
        raise ValueError("Update bootstrap exceeds Windows command line limit")
    dst.write_text(cmd, encoding="ascii", newline="")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=APP_VERSION)
    ap.add_argument("--out", default=str(ROOT / "dist/release"))
    ap.add_argument("--uv", default=shutil.which("uv") or "")
    ap.add_argument("--rehash", default="")
    a = ap.parse_args()
    ext_dist = ROOT / "apps/extension/dist"
    ext_manifest = json.loads((ext_dist / "manifest.json").read_text(encoding="utf-8"))
    if "key" not in ext_manifest:
        print("LỖI: extension chưa có key → ID không cố định, native host sẽ từ chối.")
        return 1
    if ext_manifest.get("version") != a.version:
        raise ValueError("Extension version differs from release version; build extension again")
    ext_ids = [extension_id(ext_manifest["key"])]
    if a.rehash:
        man = write_manifest(Path(a.rehash), a.version, ext_ids)
        print("rehash", a.rehash, len(man["files"]), "files")
        return 0
    if not a.uv or not Path(a.uv).is_file():
        print("LỖI: không tìm thấy uv.exe (--uv)")
        return 1
    for f in APP_FILES:
        if not (ROOT / f).is_file():
            print("LỖI: thiếu", f)
            return 1
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    pkg = out / f"VietDubLocal-{a.version}-win-x64"
    remove_build_dir(pkg, out)
    app = pkg / "app"
    for t in APP_TREES:
        copytree(ROOT / t, app / t)
    for f in APP_FILES:
        (app / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, app / f)
    (app / "bin").mkdir(parents=True)
    shutil.copy2(a.uv, app / "bin/uv.exe")
    copytree(ext_dist, pkg / "extension")
    for f in ("Setup.cmd", "setup.ps1", "install.ps1", "install-common.ps1", "uninstall.ps1", "HUONG-DAN.html", "Cap-nhat-VietDub.cmd", "update.ps1"):
        shutil.copy2(ROOT / "packaging/windows" / f, pkg / f)
    shutil.copy2(ROOT / "packaging/windows/README-CAI-DAT.txt", pkg / "README-CAI-DAT.txt")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", pkg / "THIRD_PARTY_NOTICES.md")
    for name in ("LICENSE", "NOTICE"):
        shutil.copy2(ROOT / name, pkg / name)
    shutil.copy2(ROOT / "docs/CAI_MOI_TU_GITHUB.md", pkg / "CAI-MOI-TU-GITHUB.md")
    copytree(ROOT / "docs/images", pkg / "images")
    man = write_manifest(pkg, a.version, ext_ids)
    z_app = out / f"{pkg.name}.zip"
    zipdir(pkg, z_app)
    ext_stage = out / f"VietDubLocal-extension-{a.version}"
    remove_build_dir(ext_stage, out)
    shutil.copytree(ext_dist, ext_stage)
    z_ext = out / f"{ext_stage.name}.zip"
    zipdir(ext_stage, z_ext)
    bootstrap = out / "Cap-nhat-tu-0.1.1.cmd"
    write_update_bootstrap(bootstrap)
    remove_build_dir(ext_stage, out)
    sums = "".join(f"{sha256(z)}  {z.name}\n" for z in (z_app, z_ext, bootstrap))
    (out / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
    print(f"package {pkg} files={len(man['files'])}")
    print(sums, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
