"""local-config.json do installer PowerShell 5.1 ghi: có thể có BOM và mảng 1 phần tử bị bóc thành chuỗi."""
from __future__ import annotations

import json
from types import SimpleNamespace

from vietdub import native_host
from vietdub.broker.main import load_allowed_extensions

EXT = "caeomkgooiaafanackdgfaebcidkfbom"


def _paths(tmp_path, cfg: dict, bom: bool):
    p = tmp_path / "local-config.json"
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + json.dumps(cfg).encode("utf-8"))
    return SimpleNamespace(local_config=p)


def test_single_id_string_and_bom(tmp_path):
    paths = _paths(tmp_path, {"allowed_extension_ids": EXT}, bom=True)
    assert load_allowed_extensions(paths) == {EXT}
    assert native_host.allowed_origins(paths) == {f"chrome-extension://{EXT}/"}


def test_list_and_invalid_ids_filtered(tmp_path):
    paths = _paths(tmp_path, {"allowed_extension_ids": [EXT, "short", 5]}, bom=False)
    assert load_allowed_extensions(paths) == {EXT}
    assert native_host.allowed_origins(paths) == {f"chrome-extension://{EXT}/"}
