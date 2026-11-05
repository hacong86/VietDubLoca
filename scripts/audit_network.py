"""Kiểm mạng (AT-018/AT-043): trong khi AI đang chạy, broker + mọi tiến trình con (llama-server, TTS/ASR worker)
KHÔNG được có kết nối tới địa chỉ ngoài loopback. Lấy mẫu psutil mỗi 0,3 s.

python scripts/audit_network.py --seconds 90 [--out benchmarks/results/network-audit-<ts>.json]
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import sys
import time
from pathlib import Path

import psutil

HOME = Path("D:/VietDubLocal")
ROOT = Path(__file__).resolve().parents[1]


def is_loopback(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip.split("%")[0]).is_loopback
    except ValueError:
        return False


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    pid = json.loads((HOME / "runtime/broker.json").read_text(encoding="utf-8"))["pid"]
    root = psutil.Process(pid)
    seen_procs: dict[int, str] = {}
    listens: set[str] = set()
    outside: list[dict] = []
    samples = conns_total = 0
    t0 = time.time()
    while time.time() - t0 < a.seconds:
        procs = [root] + root.children(recursive=True)
        for p in procs:
            try:
                seen_procs.setdefault(p.pid, " ".join(p.cmdline()[:3])[:120])
                for c in p.net_connections(kind="inet"):
                    conns_total += 1
                    if c.status == psutil.CONN_LISTEN and c.laddr:
                        listens.add(f"{c.laddr.ip}:{c.laddr.port}")
                    if c.raddr and not is_loopback(c.raddr.ip):
                        outside.append({"pid": p.pid, "proc": seen_procs[p.pid], "remote": f"{c.raddr.ip}:{c.raddr.port}", "t": round(time.time() - t0, 1)})
                    if c.laddr and c.status == psutil.CONN_LISTEN and not is_loopback(c.laddr.ip):
                        outside.append({"pid": p.pid, "proc": seen_procs[p.pid], "listen_non_loopback": f"{c.laddr.ip}:{c.laddr.port}"})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        samples += 1
        time.sleep(0.3)
    res = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": a.seconds, "samples": samples, "connections_seen": conns_total,
           "processes": seen_procs, "listen": sorted(listens), "non_loopback": outside[:50], "pass": not outside}
    out = Path(a.out) if a.out else ROOT / "benchmarks/results" / f"network-audit-{time.strftime('%Y%m%dT%H%M%S')}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "processes"}, ensure_ascii=False))
    print("processes:", json.dumps(seen_procs, ensure_ascii=False))
    print("saved", out)
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
