"""Benchmark tải B (docs/13): Qwen dịch 80 câu seed (tắt cache) TRONG KHI VieNeu tổng hợp liên tục; đo VRAM/RAM đỉnh thật.
Chạy khi broker đang chạy. Kết quả: benchmarks/results/load-b-<ts>.json (không tự chấm chất lượng)."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[1]
HOME = Path("D:/VietDubLocal")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    st = json.loads((HOME / "runtime/broker.json").read_text(encoding="utf-8"))
    ext = json.loads((HOME / "local-config.json").read_text(encoding="utf-8"))["allowed_extension_ids"][0]
    origin = f"chrome-extension://{ext}"
    base = f"http://127.0.0.1:{st['port']}"
    cli = httpx.Client(base_url=base, trust_env=False, timeout=60)
    tok = cli.post("/internal/pair", headers={"X-VietDub-Pairing": st["pairing_secret"]}, json={"extension_origin": origin}).json()["session_token"]
    H = {"Authorization": f"Bearer {tok}", "Origin": origin}
    samples: list[dict] = []
    stop = threading.Event()

    def sampler() -> None:
        while not stop.is_set():
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True).stdout.strip().split(",")
            rss = 0
            for p in psutil.process_iter(["name", "cmdline", "memory_info"]):
                try:
                    cmd = " ".join(p.info["cmdline"] or [])
                    if "llama-server" in (p.info["name"] or "") or "vietdub" in cmd:
                        rss += p.info["memory_info"].rss
                except (psutil.Error, TypeError):
                    pass
            samples.append({"t": time.time(), "vram_used_mb": int(out[0]), "gpu_util": int(out[1]), "vietdub_rss_mb": round(rss / 2**20)})
            time.sleep(1)

    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    while not samples:
        time.sleep(0.5)
    idle = samples[-1]
    job = cli.post("/v1/benchmark", headers=H, json={"limit": 80, "split": "all", "with_tts": True}).json()["job_id"]
    while True:
        j = cli.get(f"/v1/jobs/{job}", headers=H).json()
        if j["state"] != "running":
            break
        time.sleep(2)
    stop.set()
    th.join()
    res = j.get("result", {})
    peak = max(samples, key=lambda s: s["vram_used_mb"])
    out = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "load": "B: Qwen dịch + VieNeu tổng hợp liên tục cùng GPU",
           "hardware": "RTX 3060 12 GB, i9-11900K, 32 GB RAM, driver 616.92", "result": res, "state": j["state"], "error": j.get("error"),
           "vram_idle_before_mb": idle["vram_used_mb"], "vram_peak_mb": peak["vram_used_mb"],
           "vietdub_rss_peak_mb": max(s["vietdub_rss_mb"] for s in samples),
           "gpu_util_max": max(s["gpu_util"] for s in samples), "samples": len(samples),
           "note_vi": "VRAM đo toàn GPU (gồm ứng dụng khác đang mở). Chất lượng dịch CHƯA người chấm."}
    dst = ROOT / "benchmarks" / "results" / f"load-b-{time.strftime('%Y%m%dT%H%M%S')}.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "result"} | {"result": {k: v for k, v in res.items() if k != "sample"}}, ensure_ascii=False, indent=1))
    print("saved", dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
