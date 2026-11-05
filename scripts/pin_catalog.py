"""Ghim revision + SHA từ HuggingFace API cho danh mục model (không tải trọng số).

Chạy: .venv-broker/Scripts/python.exe scripts/pin_catalog.py
Ghi config/model-catalog.json. sha256 = LFS oid upstream; tệp nhỏ không-LFS dùng git blob sha1 + size.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]

MODELS = [
    {"id": "qwen35_4b_q5", "kind": "translation", "family": "qwen3.5", "role": "initial_default",
     "origin_model": "Qwen/Qwen3.5-4B", "repo": "unsloth/Qwen3.5-4B-GGUF", "files": ["Qwen3.5-4B-Q5_K_M.gguf"],
     "quant": "Q5_K_M", "license": "apache-2.0", "source_ids": ["S04", "S05"], "profile": "qwen_non_thinking",
     "label_vi": "Qwen3.5 4B — cân bằng (Q5_K_M)"},
    {"id": "qwen35_4b_q4", "kind": "translation", "family": "qwen3.5", "role": "light_candidate",
     "origin_model": "Qwen/Qwen3.5-4B", "repo": "unsloth/Qwen3.5-4B-GGUF", "files": ["Qwen3.5-4B-Q4_K_M.gguf"],
     "quant": "Q4_K_M", "license": "apache-2.0", "source_ids": ["S04", "S05"], "profile": "qwen_non_thinking",
     "label_vi": "Qwen3.5 4B — nhẹ (Q4_K_M)"},
    {"id": "gemma4_e4b_qat", "kind": "translation", "family": "gemma4", "role": "quality_challenger",
     "origin_model": "google/gemma-4-E4B-it", "repo": "google/gemma-4-E4B-it-qat-q4_0-gguf",
     "files": ["gemma-4-E4B_q4_0-it.gguf"], "quant": "QAT_Q4_0", "license": "apache-2.0",
     "source_ids": ["S01", "S02"], "profile": "gemma_non_thinking", "label_vi": "Gemma 4 E4B QAT — đối chứng"},
    {"id": "gemma4_e2b_qat", "kind": "translation", "family": "gemma4", "role": "optional_candidate",
     "origin_model": "google/gemma-4-E2B-it", "repo": "google/gemma-4-E2B-it-qat-q4_0-gguf",
     "files": ["gemma-4-E2B_q4_0-it.gguf"], "quant": "QAT_Q4_0", "license": "apache-2.0",
     "source_ids": ["S01", "S03"], "profile": "gemma_non_thinking", "label_vi": "Gemma 4 E2B QAT — tùy chọn"},
    {"id": "whisper_small_en", "kind": "asr", "family": "faster-whisper", "role": "asr_default",
     "origin_model": "openai/whisper-small.en", "repo": "Systran/faster-whisper-small.en",
     "files": ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"], "quant": "float16->int8 runtime",
     "license": "mit", "source_ids": ["S23"], "label_vi": "Nhận dạng tiếng Anh small.en (CPU)"},
    {"id": "vieneu_v3_turbo", "kind": "tts", "family": "vieneu", "role": "tts_default",
     "origin_model": "pnnbao-ump/VieNeu-TTS-v3-Turbo", "repo": "pnnbao-ump/VieNeu-TTS-v3-Turbo",
     "files": ["config.json", "denoiser.onnx", "speaker_encoder.onnx", "update/config.json", "update/model.safetensors",
               "update/special_tokens_map.json", "update/tokenizer.json", "update/tokenizer_config.json"],
     "hf_layout": True, "quant": "fp32/bf16", "license": "apache-2.0", "source_ids": ["S11", "S12"],
     "label_vi": "Giọng VieNeu v3 Turbo"},
    {"id": "moss_audio_tokenizer_nano", "kind": "tts_dep", "family": "moss", "role": "tts_codec",
     "origin_model": "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano", "repo": "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano",
     "files": ["config.json", "configuration_moss_audio_tokenizer.py", "model-00001-of-00001.safetensors",
               "model.safetensors.index.json", "modeling_moss_audio_tokenizer.py"],
     "hf_layout": True, "quant": "fp32", "license": "apache-2.0", "source_ids": ["S12"],
     "label_vi": "Bộ mã âm thanh MOSS (đi kèm VieNeu)"},
]


def main() -> int:
    cli = httpx.Client(timeout=30, follow_redirects=True)
    out = []
    for m in MODELS:
        info = cli.get(f"https://huggingface.co/api/models/{m['repo']}").json()
        rev = info["sha"]
        tree: dict[str, dict] = {}
        dirs = {str(Path(f).parent).replace("\\", "/") for f in m["files"]}
        for d in dirs:
            url = f"https://huggingface.co/api/models/{m['repo']}/tree/{rev}" + ("" if d == "." else f"/{d}")
            for e in cli.get(url).json():
                tree[e["path"]] = e
        files = []
        for f in m["files"]:
            e = tree[f]
            lfs = e.get("lfs") or {}
            files.append({"path": f, "size": e["size"], "sha256": lfs.get("oid"),
                          "git_sha1": None if lfs else e.get("oid")})
        total = sum(x["size"] for x in files)
        out.append({**m, "revision": rev, "files": files, "size_bytes": total,
                    "approx_decimal_gb": round(total / 1e9, 2), "verified_upstream": True})
        print(m["id"], rev, total, file=sys.stderr)
    cat = {"catalog_version": 2, "checked_date": date.today().isoformat(), "release_ready": False,
           "note_vi": "Revision + SHA lấy từ HuggingFace API lúc ghim; tệp tải về phải khớp mới được nạp. "
                      "Không tải mmproj cho text-only.", "models": out}
    (ROOT / "config" / "model-catalog.json").write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
