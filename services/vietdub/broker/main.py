"""Khởi động broker: 127.0.0.1 only, ghi runtime state (port + pairing secret) ACL chỉ user hiện tại.

python -m vietdub.broker.main [--port 8765] [--no-autoload]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import socket
import subprocess
import sys
import time

import uvicorn

from .. import APP_VERSION, PROTOCOL_VERSION
from ..paths import default_paths
from ..storage.audio_cache import AudioCache
from ..storage.db import Database
from .app import Ctx, create_app, set_exit_event
from .events import Hub
from .runtime import BrokerRuntime
from .security import TokenStore, redact
from .settings_store import merged

log = logging.getLogger("vietdub.main")


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging(logs_dir) -> None:
    h = logging.handlers.RotatingFileHandler(logs_dir / "broker.log", maxBytes=5 * 1024 ** 2, backupCount=3,
                                             encoding="utf-8")
    h.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def restrict_acl(path) -> None:
    """Tệp chứa bí mật: chỉ user hiện tại đọc được (không cần admin)."""
    user = os.environ.get("USERNAME")
    if not user:
        return
    subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"], capture_output=True,
                   creationflags=0x08000000)


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def load_allowed_extensions(paths) -> set[str]:
    try:
        cfg = json.loads(paths.local_config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        cfg = {}
    ids = cfg.get("allowed_extension_ids") or []
    if isinstance(ids, str):  # PowerShell 5.1 ConvertTo-Json bóc mảng 1 phần tử
        ids = [ids]
    return {i for i in ids if isinstance(i, str) and len(i) == 32}


async def amain(args: argparse.Namespace) -> None:
    paths = default_paths().ensure()
    setup_logging(paths.logs)
    port = args.port
    if not port_free(port):
        for p in range(port + 1, port + 20):
            if p != 8766 and port_free(p):
                port = p
                break
    db = Database(paths.db_file, paths.backups)
    settings = merged(db.get_setting("app_settings"))
    if settings["storage"]["private_mode"]:
        db.set_private(True)
    cache = AudioCache(paths.audio_cache, db, limit_bytes=settings["storage"]["cache_limit_bytes"],
                       ttl_days=settings["storage"]["cache_ttl_days"])
    hub = Hub()

    def emit_global(event: str, payload: dict) -> object:
        return hub.send_event(event, payload, session_id=None, epoch=0)

    rt = BrokerRuntime(paths, emit=emit_global)
    tokens = TokenStore(load_allowed_extensions(paths))
    ctx = Ctx(paths=paths, db=db, cache=cache, rt=rt, hub=hub, tokens=tokens, port=port)
    app = create_app(ctx)

    state = {"port": port, "pairing_secret": tokens.pairing_secret, "pid": os.getpid(), "app_version": APP_VERSION,
             "protocol_version": PROTOCOL_VERSION, "started_at": int(time.time())}
    tmp = paths.broker_state.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    restrict_acl(tmp)
    os.replace(tmp, paths.broker_state)

    exit_ev = asyncio.Event()
    set_exit_event(exit_ev)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws_max_size=512 * 1024,
                            ws_ping_interval=10, ws_ping_timeout=10, lifespan="off", access_log=False)
    server = uvicorn.Server(config)

    async def startup_tasks() -> None:
        try:
            await asyncio.to_thread(cache.enforce)
            await rt.verify_models(["qwen35_4b_q5", "qwen35_4b_q4", "gemma4_e4b_qat", "gemma4_e2b_qat",
                                    "vieneu_v3_turbo", "moss_audio_tokenizer_nano", "whisper_small_en"])
            if not args.no_autoload:
                mid = settings["translation"]["model_id"]
                if rt.verified.get(mid):
                    await rt.activate_translation(mid)
                await rt.start_tts(settings["tts"]["device"])
        except Exception as e:  # noqa: BLE001
            log.warning("autoload: %s", redact(repr(e))[:300])

    async def janitor() -> None:
        while True:
            await asyncio.sleep(600)
            try:
                await asyncio.to_thread(cache.enforce)
            except Exception:
                pass

    serve = asyncio.create_task(server.serve())
    boot = asyncio.create_task(startup_tasks())
    ctx.startup_task = boot
    jan = asyncio.create_task(janitor())
    stop_waiter = asyncio.create_task(exit_ev.wait())
    await asyncio.wait({serve, stop_waiter}, return_when=asyncio.FIRST_COMPLETED)
    log.info("shutting down")
    if ctx.session:
        await ctx.session.close("companion_exit")
    boot.cancel()
    if ctx.setup:
        await ctx.setup.close()
    jan.cancel()
    await rt.shutdown()
    server.should_exit = True
    try:
        await asyncio.wait_for(serve, 5)
    except Exception:
        pass
    db.checkpoint()
    db.close()
    try:
        paths.broker_state.unlink()
    except OSError:
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-autoload", action="store_true")
    args = ap.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
