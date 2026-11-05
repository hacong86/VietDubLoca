"""Sinh THIRD_PARTY_NOTICES.md + sbom/vietdub-sbom.cdx.json từ metadata THẬT (không tự điền license).

Chạy bằng từng interpreter để đọc importlib.metadata của môi trường đó (chỉ đọc, không cài gì):
  <broker py> scripts/gen_notices.py --collect broker  → sbom/_broker.json
  <tts py>    scripts/gen_notices.py --collect tts     → sbom/_tts.json     (venv Hermes, chỉ đọc)
  <asr py>    scripts/gen_notices.py --collect asr     → sbom/_asr.json
  python      scripts/gen_notices.py --render
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SBOM = ROOT / "sbom"
NPM_BUNDLED = ["react", "react-dom", "scheduler", "zod"]


def lic_of(dist) -> str:
    md = dist.metadata
    expr = md.get("License-Expression")
    if expr:
        return expr
    cls = [c.split("::")[-1].strip() for c in (md.get_all("Classifier") or []) if c.startswith("License ::")]
    if cls:
        return "; ".join(sorted(set(cls)))
    raw = (md.get("License") or "").strip().splitlines()
    return raw[0][:80] if raw and raw[0] else "UNKNOWN"


def collect(kind: str) -> None:
    from importlib import metadata
    lock = (ROOT / "requirements" / f"{kind}.lock.txt").read_text(encoding="utf-8")
    wanted = {l.split("==")[0].strip().lower().replace("_", "-") for l in lock.splitlines() if "==" in l and not l.startswith("#")}
    out = []
    for d in metadata.distributions():
        n = (d.metadata["Name"] or "").lower().replace("_", "-")
        if n in wanted:
            out.append({"name": d.metadata["Name"], "version": d.version, "license": lic_of(d),
                        "home": d.metadata.get("Home-page") or ""})
    SBOM.mkdir(exist_ok=True)
    (SBOM / f"_{kind}.json").write_text(json.dumps(sorted(out, key=lambda x: x["name"].lower()), ensure_ascii=False, indent=1), encoding="utf-8")
    print(kind, len(out), "/", len(wanted))


def npm() -> list[dict]:
    res = []
    for n in NPM_BUNDLED:
        pj = None
        for base in (ROOT / "node_modules", ROOT / "node_modules/.pnpm/node_modules"):
            if (base / n / "package.json").is_file():
                pj = json.loads((base / n / "package.json").read_text(encoding="utf-8"))
                break
        if pj:
            res.append({"name": n, "version": pj["version"], "license": pj.get("license", "UNKNOWN"), "home": pj.get("homepage", "")})
    return res


def render() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    groups = {k: json.loads((SBOM / f"_{k}.json").read_text(encoding="utf-8")) for k in ("broker", "tts", "asr")}
    groups["extension"] = npm()
    cat = json.loads((ROOT / "config/model-catalog.json").read_text(encoding="utf-8"))
    models = cat["models"] if isinstance(cat, dict) else cat
    lock = json.loads((ROOT / "config/runtime-lock.json").read_text(encoding="utf-8"))
    L = ["# THIRD_PARTY_NOTICES — VietDub Local", "",
         "Danh mục sinh từ metadata gói đã cài; `UNKNOWN` nghĩa là metadata chưa đủ, không phải không có giấy phép. "
         "Giấy phép đầy đủ cho uv và thư viện JavaScript đi kèm nằm trong `THIRD_PARTY_LICENSES/`. "
         "Dependencies Python, llama/CUDA và model được tải riêng từ upstream khi người dùng đồng ý.", "",
         "PolyForm chỉ áp dụng mã/tài liệu của VietDub; thành phần bên thứ ba giữ nguyên giấy phép và quyền do chủ sở hữu cấp. "
         "Danh mục metadata không thay nội dung giấy phép upstream.", "",
         "## Runtime và công cụ đi kèm", "",
         "| Thành phần | Phiên bản | License | Nguồn |", "|---|---|---|---|",
         f"| llama.cpp (llama-server, CUDA build) | {lock['llama_cpp_build']} | MIT | https://github.com/ggml-org/llama.cpp |",
         "| NVIDIA CUDA runtime (cudart/cublas, kèm bản llama.cpp) | 13.4 | NVIDIA CUDA Toolkit EULA (redistributable) | https://docs.nvidia.com/cuda/eula/ |",
         f"| CPython (uv-managed, python-build-standalone) | {lock['python_version'].split()[0]} | PSF-2.0 | https://www.python.org/ |",
         "| uv | 0.12.18 | MIT OR Apache-2.0 | https://github.com/astral-sh/uv |", "",
         "## Mô hình (tải theo đồng ý của người dùng, không đóng kèm gói)", "",
         "| Model ID | Repo | Revision | License (theo model card) |", "|---|---|---|---|"]
    for m in models:
        L.append(f"| {m['id']} | {m['repo']} | `{m.get('revision', '')[:12]}` | {m.get('license', 'UNKNOWN')} |")
    L += ["", "Người dùng tự chịu trách nhiệm tuân thủ điều khoản model card khi sử dụng. VieNeu v3 Turbo đi kèm watermark âm thanh khi SDK hỗ trợ.", ""]
    titles = {"broker": "Python — broker/companion (`requirements/broker.lock.txt`)",
              "tts": "Python — môi trường giọng đọc VieNeu (`requirements/tts.lock.txt`)",
              "asr": "Python — môi trường nhận dạng giọng nói (`requirements/asr.lock.txt`)",
              "extension": "JavaScript đóng gói trong extension"}
    comps = []
    for k, rows in groups.items():
        L += [f"## {titles[k]}", "", "| Gói | Phiên bản | License |", "|---|---|---|"]
        for r in rows:
            L.append(f"| {r['name']} | {r['version']} | {r['license'].replace('|', '/')} |")
            comps.append({"type": "library", "name": r["name"], "version": r["version"], "group": k,
                          "purl": (f"pkg:npm/{r['name']}@{r['version']}" if k == "extension" else f"pkg:pypi/{r['name'].lower()}@{r['version']}"),
                          "licenses": [{"license": {"name": r["license"]}}]})
        L.append("")
    unknown = sum(1 for c in comps if c["licenses"][0]["license"]["name"] == "UNKNOWN")
    L += [f"Tổng: {len(comps)} gói; {unknown} gói không khai báo license trong metadata.", ""]
    (ROOT / "THIRD_PARTY_NOTICES.md").write_text("\n".join(L), encoding="utf-8")
    for m in models:
        comps.append({"type": "machine-learning-model", "name": m["repo"], "version": m.get("revision", ""),
                      "licenses": [{"license": {"id": m.get("license", "")}}]})
    bom = {"bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": f"urn:uuid:{uuid.uuid4()}", "version": 1,
           "metadata": {"component": {"type": "application", "name": "VietDub Local", "version": "0.1.0"}}, "components": comps}
    (SBOM / "vietdub-sbom.cdx.json").write_text(json.dumps(bom, ensure_ascii=False, indent=1), encoding="utf-8")
    print("components", len(comps), "unknown", unknown)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect")
    ap.add_argument("--render", action="store_true")
    a = ap.parse_args()
    collect(a.collect) if a.collect else render()
