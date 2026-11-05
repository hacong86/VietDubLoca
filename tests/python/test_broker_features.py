"""Nghiệm thu mức broker (runtime giả — wiring, KHÔNG phải bằng chứng AI thật): AT-019, AT-033, AT-036."""
from conftest import H
from test_broker_pipeline import batch, clock, collect, start, ws_auth


def _ready(client, token, sid, w, n=2):
    client.post(f"/v1/sessions/{sid}/captions", headers=H(token), json=batch(sid, 0))
    client.post(f"/v1/sessions/{sid}/clock", headers=H(token), json=clock(sid, 0, 9000))
    return collect(w, lambda e, f: sum(1 for x in e if x["event"] == "translation.ready") >= n)


def test_settings_reset_keeps_overrides_and_glossary(client, token, ctx):
    """AT-033: reset chỉ settings → không xóa bản sửa, glossary, model."""
    sid = start(client, token)
    ws, w = ws_auth(client, token)
    try:
        w.send_json({"type": "subscribe", "session_id": sid})
        ev, _ = _ready(client, token, sid, w)
        seg = next(e["payload"] for e in ev if e["event"] == "translation.ready")
        client.patch(f"/v1/segments/{seg['segment_id']}", headers={**H(token), "If-Match": str(seg["revision"])},
                     json={"target_display": "Bản sửa giữ lại."})
        g = client.get("/v1/glossary", headers=H(token)).json()
        client.put("/v1/glossary", headers={**H(token), "If-Match": str(g["version"])},
                   json={"entries": [{"source": "Inspector", "target": "Inspector", "policy": "preserve"}]})
        client.put("/v1/settings", headers=H(token), json={"value": {"playback": {"original_gain": 0.4}}})
        assert client.get("/v1/settings", headers=H(token)).json()["value"]["playback"]["original_gain"] == 0.4
        assert client.post("/v1/settings/reset", headers=H(token), json={}).status_code == 400   # phải xác nhận
        r = client.post("/v1/settings/reset", headers=H(token), json={"confirm": True, "scope": "settings"})
        assert r.status_code == 200 and r.json()["removed"] == []
        assert r.json()["value"]["playback"]["original_gain"] == 0.15
        assert ctx.db.latest_override(seg["segment_id"])["target_display"] == "Bản sửa giữ lại."
        assert len(client.get("/v1/glossary", headers=H(token)).json()["value"]["entries"]) == 1
    finally:
        ws.__exit__(None, None, None)


def test_export_uses_source_timeline_and_needs_ack(client, token, ctx):
    """AT-036: mốc thời gian xuất = timeline nguồn (không phải lịch audio sau auto-hold); phải xác nhận quyền."""
    sid = start(client, token)
    ws, w = ws_auth(client, token)
    try:
        w.send_json({"type": "subscribe", "session_id": sid})
        _ready(client, token, sid, w)
        client.post(f"/v1/sessions/{sid}/control", headers=H(token), json={"op": "pause", "reason": "AUTO_SENTENCE"})
        body = {"session_id": sid, "format": "srt", "kind": "bilingual"}
        assert client.post("/v1/export/subtitles", headers=H(token), json=body).status_code == 400
        r = client.post("/v1/export/subtitles", headers=H(token), json={**body, "ack_rights": True})
        assert r.status_code == 202
        content = r.json()["content"]
        assert "00:00:10,000 --> 00:00:16,000" in content           # đúng bounds nguồn của câu ghép c1..c3
        assert "Make sure you don't delete the original file" in content and "VI: " in content
        vtt = client.post("/v1/export/subtitles", headers=H(token), json={**body, "format": "vtt", "kind": "vi", "ack_rights": True})
        assert vtt.json()["content"].startswith("WEBVTT") and "00:00:10.000 --> 00:00:16.000" in vtt.json()["content"]
    finally:
        ws.__exit__(None, None, None)


def test_invalid_saved_voice_reports_and_never_switches_silently(client, token, ctx):
    """AT-019-B: voice đã lưu không còn → báo VOICE_NOT_FOUND, không âm thầm đọc bằng giọng khác."""
    client.put("/v1/settings", headers=H(token), json={"value": {"tts": {"voice_id": "Giọng Đã Bị Gỡ"}}})
    sid = start(client, token)
    ws, w = ws_auth(client, token)
    try:
        w.send_json({"type": "subscribe", "session_id": sid})
        client.post(f"/v1/sessions/{sid}/captions", headers=H(token), json=batch(sid, 0))
        client.post(f"/v1/sessions/{sid}/clock", headers=H(token), json=clock(sid, 0, 9000))
        ev, fr = collect(w, lambda e, f: any(x["event"] == "error" and x["payload"].get("code") == "VOICE_NOT_FOUND" for x in e))
        err = next(x["payload"] for x in ev if x["event"] == "error")
        assert "Chọn giọng khác" in err.get("action_vi", "") + err.get("message_vi", "") + str(err)
        assert ctx.rt.synth_calls == [] and fr == []                 # không có audio giọng khác
    finally:
        ws.__exit__(None, None, None)


def test_live_queue_overflow_stops_and_can_resume(client, token, ctx):
    """AT-028-B: live_delayed vượt queue cap → dừng tiếng Việt + báo lỗi, không lặng lẽ bỏ câu; người dùng nối lại được."""
    r = client.post("/v1/sessions", headers=H(token), json={"video_id": "dQw4w9WgXcQ", "tab_id": 7, "mode": "live_delayed"})
    sid = r.json()["session_id"]
    ws, w = ws_auth(client, token)
    try:
        w.send_json({"type": "subscribe", "session_id": sid})
        client.post(f"/v1/sessions/{sid}/captions", headers=H(token), json=batch(sid, 0))
        client.post(f"/v1/sessions/{sid}/clock", headers=H(token), json=clock(sid, 0, 9000))
        w.send_json({"type": "queue.status", "queued_ms": 45_000})         # offscreen báo hàng đợi phát vượt cap 30 s
        ev, _ = collect(w, lambda e, f: any(x["event"] == "error" and x["payload"].get("code") == "LIVE_QUEUE_OVERFLOW" for x in e))
        assert any(x["event"] == "audio.stop" and x["payload"].get("reason") == "LIVE_QUEUE_OVERFLOW" for x in ev)
        st = client.get("/v1/status", headers=H(token)).json()["session"]
        assert st["state"] == "ERROR" and st["last_error"] == "LIVE_QUEUE_OVERFLOW"
        w.send_json({"type": "queue.status", "queued_ms": 0})
        r = client.post(f"/v1/sessions/{sid}/control", headers=H(token), json={"op": "resume_live"})
        assert r.status_code == 202 and r.json()["state"] != "ERROR"
    finally:
        ws.__exit__(None, None, None)


def test_override_survives_reopening_video(client, token, ctx):
    """AT-016-A: đóng phiên rồi mở lại cùng video → câu đã sửa vẫn là bản sửa, đánh dấu USER_OVERRIDE, không dịch lại."""
    sid = start(client, token)
    ws, w = ws_auth(client, token)
    try:
        w.send_json({"type": "subscribe", "session_id": sid})
        ev, _ = _ready(client, token, sid, w)
        seg = next(e["payload"] for e in ev if e["event"] == "translation.ready")
        client.patch(f"/v1/segments/{seg['segment_id']}", headers={**H(token), "If-Match": str(seg["revision"])},
                     json={"target_display": "Bản sửa vẫn còn."})
    finally:
        ws.__exit__(None, None, None)
    assert client.delete(f"/v1/sessions/{sid}", headers=H(token)).status_code == 204
    calls_before = ctx.rt.calls
    sid2 = start(client, token)
    client.post(f"/v1/sessions/{sid2}/captions", headers=H(token), json=batch(sid2, 0))
    segs = client.get(f"/v1/sessions/{sid2}/segments", headers=H(token)).json()["segments"]
    again = next(s for s in segs if s["segment_id"] == seg["segment_id"])
    assert again["override"] is True and again["target_display"] == "Bản sửa vẫn còn." and again["flags"] == ["USER_OVERRIDE"]
    assert again["status"] == "ready" and ctx.rt.calls == calls_before


def _patch(client, token, seg_id, rev, text):
    r = client.patch(f"/v1/segments/{seg_id}", headers={**H(token), "If-Match": str(rev)}, json={"target_display": text})
    assert r.status_code == 200, r.text
    return r.json()["version"]


def test_undo_twice_walks_history_with_monotonic_revisions(client, token, ctx):
    """Codex #4: hoàn tác nhiều lần đi lùi đúng lịch sử, revision luôn tăng, hết lịch sử → 404."""
    sid = start(client, token)
    ws, w = ws_auth(client, token)
    try:
        w.send_json({"type": "subscribe", "session_id": sid})
        ev, _ = _ready(client, token, sid, w)
        seg = next(e["payload"] for e in ev if e["event"] == "translation.ready")
        machine = seg["target_display"]
        r1 = _patch(client, token, seg["segment_id"], seg["revision"], "Bản A.")
        r2 = _patch(client, token, seg["segment_id"], r1, "Bản B.")
        u1 = client.post(f"/v1/segments/{seg['segment_id']}/undo", headers=H(token)).json()
        assert u1["value"]["target_display"] == "Bản A." and u1["value"]["override"] is True and u1["version"] > r2
        u2 = client.post(f"/v1/segments/{seg['segment_id']}/undo", headers=H(token)).json()
        assert u2["value"]["target_display"] == machine and u2["value"]["override"] is False and u2["version"] > u1["version"]
        assert client.post(f"/v1/segments/{seg['segment_id']}/undo", headers=H(token)).status_code == 404
    finally:
        ws.__exit__(None, None, None)


def test_undo_after_reopen_restores_machine_behind_playhead(client, token, ctx):
    """Codex #7: bản sửa nạp lại từ DB (không có cache_key) vẫn hoàn tác về bản máy dịch đã lưu."""
    sid = start(client, token)
    ws, w = ws_auth(client, token)
    try:
        w.send_json({"type": "subscribe", "session_id": sid})
        ev, _ = _ready(client, token, sid, w)
        seg = next(e["payload"] for e in ev if e["event"] == "translation.ready")
        machine = seg["target_display"]
        _patch(client, token, seg["segment_id"], seg["revision"], "Sửa rồi mở lại.")
    finally:
        ws.__exit__(None, None, None)
    client.delete(f"/v1/sessions/{sid}", headers=H(token))
    sid2 = start(client, token)
    client.post(f"/v1/sessions/{sid2}/captions", headers=H(token), json=batch(sid2, 0))
    client.post(f"/v1/sessions/{sid2}/clock", headers=H(token), json=clock(sid2, 0, 60000, paused=True))
    u = client.post(f"/v1/segments/{seg['segment_id']}/undo", headers=H(token)).json()
    assert u["value"]["status"] == "ready" and u["value"]["target_display"] == machine
