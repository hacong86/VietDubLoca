"""SYS-16, FR-041, FR-042: website lạ/Origin null/token trong URL/replay token hết hạn đều bị chặn."""
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from conftest import EXT_ID, H, ORIGIN, PORT


def test_health_minimal_no_auth(client):
    r = client.get("/health")
    assert r.status_code == 200 and set(r.json()) == {"protocol_version", "state"}


def test_v1_requires_bearer(client):
    r = client.get("/v1/status", headers={"Origin": ORIGIN})
    assert r.status_code == 401 and r.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "chrome-extension://" + "b" * 32, "http://127.0.0.1"])
def test_hostile_origin_rejected_even_with_token(client, token, origin):
    r = client.get("/v1/status", headers={"Authorization": f"Bearer {token}", "Origin": origin})
    assert r.status_code == 403 and r.json()["code"] == "ORIGIN_DENIED"
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_bad_host_rejected(client, token):
    r = client.get("/v1/status", headers={**H(token), "Host": "evil.example:8765"})
    assert r.status_code == 403


def test_token_in_query_rejected(client, token):
    r = client.get(f"/v1/status?token={token}", headers={"Origin": ORIGIN})
    assert r.status_code == 401


def test_valid_request_has_cors_for_extension_only(client, token):
    r = client.get("/v1/status", headers=H(token))
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ORIGIN


def test_expired_token(client, ctx, token):
    ctx.tokens._tokens[token].expires_at = time.time() - 1
    r = client.get("/v1/status", headers=H(token))
    assert r.status_code == 401 and r.json()["code"] == "AUTH_EXPIRED"


def test_pair_requires_secret_and_allowed_origin(client, ctx):
    r = client.post("/internal/pair", headers={"X-VietDub-Pairing": "wrong"}, json={"extension_origin": ORIGIN})
    assert r.status_code == 401
    r = client.post("/internal/pair", headers={"X-VietDub-Pairing": ctx.tokens.pairing_secret},
                    json={"extension_origin": "chrome-extension://" + "c" * 32})
    assert r.status_code == 403
    r = client.post("/internal/pair", headers={"X-VietDub-Pairing": ctx.tokens.pairing_secret, "Origin": ORIGIN},
                    json={"extension_origin": ORIGIN})
    assert r.status_code == 403          # từ trình duyệt (có Origin) không được pair
    r = client.post("/internal/pair", headers={"X-VietDub-Pairing": ctx.tokens.pairing_secret},
                    json={"extension_origin": ORIGIN})
    assert r.status_code == 200 and len(r.json()["session_token"]) >= 43


def test_body_too_large(client, token):
    r = client.put("/v1/settings", headers=H(token), content=b"{" + b" " * 70000 + b"}")
    assert r.status_code == 413


def test_ws_rejects_foreign_origin_and_no_auth(client, token):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/v1/events", headers={"Origin": "https://evil.example", "Host": f"127.0.0.1:{PORT}"}) as ws:
            ws.receive_json()
    with client.websocket_connect("/v1/events", headers={"Origin": ORIGIN, "Host": f"127.0.0.1:{PORT}"}) as ws:
        ws.send_json({"type": "auth", "token": "nope", "protocol_version": 1})
        m = ws.receive_json()
        assert m["event"] == "auth.error"
    with client.websocket_connect("/v1/events", headers={"Origin": ORIGIN, "Host": f"127.0.0.1:{PORT}"}) as ws:
        ws.send_json({"type": "auth", "token": token, "protocol_version": 1})
        m = ws.receive_json()
        assert m["event"] == "auth.ok" and m["protocol_version"] == 1


def test_ws_token_query_rejected(client, token):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/v1/events?token={token}", headers={"Origin": ORIGIN, "Host": f"127.0.0.1:{PORT}"}) as ws:
            ws.receive_json()


def test_errors_have_vietnamese_message_no_trace(client, token):
    r = client.get("/v1/sessions/nope", headers=H(token))
    j = r.json()
    assert r.status_code == 404 and j["message_vi"] and "Traceback" not in r.text and "action_vi" in j["details"]


def test_settings_allowlist(client, token):
    r = client.put("/v1/settings", headers=H(token), json={"value": {"runtime": {"bind_host": "0.0.0.0"}}})
    assert r.status_code == 400
    r = client.put("/v1/settings", headers=H(token), json={"value": {"playback": {"original_gain": 3}}})
    assert r.status_code == 400
    r = client.put("/v1/settings", headers=H(token), json={"value": {"playback": {"original_gain": 0.2}}, "version": 1})
    assert r.status_code == 200 and r.json()["version"] == 2
    r = client.put("/v1/settings", headers=H(token), json={"value": {"playback": {"original_gain": 0.3}}, "version": 1})
    assert r.status_code == 409 and r.json()["code"] == "REVISION_CONFLICT"


def test_session_idempotency_conflict(client, token):
    b = {"video_id": "dQw4w9WgXcQ", "tab_id": 1, "mode": "vod_sync", "request_id": "r1"}
    a = client.post("/v1/sessions", headers=H(token), json=b)
    assert a.status_code == 201
    again = client.post("/v1/sessions", headers=H(token), json=b)
    assert again.json()["session_id"] == a.json()["session_id"]
    diff = client.post("/v1/sessions", headers=H(token), json={**b, "tab_id": 2})
    assert diff.status_code == 409


def test_invalid_video_id_and_injection_payload(client, token):
    r = client.post("/v1/sessions", headers=H(token), json={"video_id": "../../etc", "tab_id": 1})
    assert r.status_code == 400
