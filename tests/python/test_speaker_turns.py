"""Đổi người nói theo dấu '>>' của YouTube (học từ YouTube Dubbing) → luân phiên 2 giọng."""
from vietdub.broker.voices import pick_alt_voice
from vietdub.translation.segmenter import build_units
from vietdub.translation.text import TURN_SPEAKERS, Cue, assign_turn_speakers, split_turn


def test_split_turn_only_leading_marker():
    assert split_turn(">> So what do you think?") == ("So what do you think?", True)
    assert split_turn(">>Yes.") == ("Yes.", True)
    # code thật trong video lập trình: không coi là đổi người nói, không xóa
    assert split_turn("shift x >> 2 bits") == ("shift x >> 2 bits", False)
    assert split_turn("plain text") == ("plain text", False)


def _cue(i, start, text, turn):
    return Cue(f"c{i}", start, start + 1500, text, text, True, None, {"turn": turn})


def test_assign_turn_speakers_alternates_and_splits_units():
    cues = [_cue(1, 0, "Welcome to the show.", True),          # >> ở câu đầu: vẫn là người 1
            _cue(2, 1600, "Thanks for having me.", True),
            _cue(3, 3200, "It is great to be here.", False),
            _cue(4, 4800, "Let's start.", True)]
    assign_turn_speakers(cues)
    assert [c.speaker for c in cues] == [TURN_SPEAKERS[0], TURN_SPEAKERS[1], TURN_SPEAKERS[1], TURN_SPEAKERS[0]]
    units = build_units("src", cues, complete=True)
    assert [u.speaker for u in units] == [TURN_SPEAKERS[0], TURN_SPEAKERS[1], TURN_SPEAKERS[1], TURN_SPEAKERS[0]]


def test_assign_turn_speakers_keeps_webvtt_voice_tags_and_no_markers():
    tagged = [Cue("a", 0, 1000, "Hi.", "<v Anna>Hi.", True, "Anna", {"turn": False, "tag_speaker": True}),
              Cue("b", 1100, 2000, "Hello.", ">> Hello.", True, None, {"turn": True})]
    assign_turn_speakers(tagged)
    assert tagged[0].speaker == "Anna" and tagged[1].speaker is None
    plain = [_cue(1, 0, "One.", False), _cue(2, 1600, "Two.", False)]
    assign_turn_speakers(plain)
    assert all(c.speaker is None for c in plain)


VOICES = [{"voice_id": "Adam bựa", "label": "⭐ Adam bựa — Nam · Bắc · Phong cách tự nhiên"},
          {"voice_id": "Trúc Ly", "label": "⭐ Trúc Ly — Nữ · Bắc · Phong cách tự nhiên"},
          {"voice_id": "Minh Quân Pro", "label": "⭐ Minh Quân Pro — Nam · Bắc · Phong cách tự nhiên"},
          {"voice_id": "Minh Đức", "label": "Minh Đức — Nam · Bắc · Phong cách tin tức"}]


def test_pick_alt_voice_opposite_gender():
    assert pick_alt_voice("Minh Quân Pro", VOICES) == "Trúc Ly"
    assert pick_alt_voice("Trúc Ly", VOICES) == "Adam bựa"
    assert pick_alt_voice("Minh Quân Pro", []) is None
    only_men = [v for v in VOICES if "Nam ·" in v["label"]]
    assert pick_alt_voice("Minh Quân Pro", only_men) == "Adam bựa"     # không có khác giới → giọng khác cùng giới


def test_session_uses_second_voice_for_second_speaker(client, token, ctx):
    """Tích hợp broker (runtime giả): '>>' → 2 người nói → TTS gọi 2 giọng khác nhau; '>>' không lọt vào câu dịch."""
    from conftest import H
    from test_broker_pipeline import clock, collect, ws_auth
    ctx.rt.voices = VOICES
    r = client.post("/v1/sessions", headers=H(token), json={"video_id": "dQw4w9WgXcQ", "tab_id": 7, "mode": "vod_sync"})
    sid = r.json()["session_id"]
    ws, w = ws_auth(client, token)
    try:
        w.send_json({"type": "subscribe", "session_id": sid})
        cues = [{"cue_id": "a", "start_ms": 10000, "end_ms": 12000, "text": ">> How long have you been coding?", "committed": True},
                {"cue_id": "b", "start_ms": 12500, "end_ms": 15000, "text": ">> About ten years now.", "committed": True},
                {"cue_id": "c", "start_ms": 15500, "end_ms": 18000, "text": ">> That is impressive.", "committed": True}]
        client.post(f"/v1/sessions/{sid}/captions", headers=H(token), json={
            "session_id": sid, "timeline_epoch": 0, "source_id": "yt-en-auto", "source_revision": 1, "source_kind": "manual",
            "language": "en", "coverage": "full", "available_until_ms": 18000, "cues": cues})
        client.post(f"/v1/sessions/{sid}/clock", headers=H(token), json=clock(sid, 0, 9000))
        collect(w, lambda e, f: sum(1 for x in e if x["event"] == "audio.end") >= 3, timeout=15)
        segs = client.get(f"/v1/sessions/{sid}/segments", headers=H(token)).json()["segments"]
        assert [s["speaker"] for s in segs] == ["Người nói 1", "Người nói 2", "Người nói 1"]
        assert all(not s["source_text"].startswith(">>") for s in segs)
        voices_used = [v for _t, v in ctx.rt.synth_calls]
        assert voices_used[:3] == ["Minh Quân Pro", "Trúc Ly", "Minh Quân Pro"]
    finally:
        ws.__exit__(None, None, None)


def test_synthetic_speakers_cleared_when_markers_disappear():
    """Codex #9: kết quả chỉ phụ thuộc cue hiện tại, không phụ thuộc lịch sử cập nhật."""
    cues = [_cue(1, 0, "One.", False), _cue(2, 1600, "Two.", True)]
    assign_turn_speakers(cues)
    assert cues[1].speaker == TURN_SPEAKERS[1]
    cues[1].meta["turn"] = False
    assign_turn_speakers(cues)
    assert all(c.speaker is None for c in cues)


def test_rolling_dedupe_keeps_turn_boundary():
    """Codex #10: cụm chồng lấp giữa 2 người nói khác nhau không bị gộp/cắt."""
    from vietdub.translation.text import dedupe_rolling
    a = Cue("a", 0, 2000, "yes I think so", "yes I think so", True, None, {"turn": False})
    b = Cue("b", 1500, 3000, "I think so too", ">> I think so too", True, None, {"turn": True})
    out = dedupe_rolling([a, b])
    assert [c.text for c in out] == ["yes I think so", "I think so too"]


def test_alt_voice_equal_to_main_is_ignored(client, token, ctx):
    """Codex #12: giọng phụ trùng giọng chính → tự chọn giọng khác, không đọc 1 giọng âm thầm."""
    from vietdub.broker.session import Settings, UnitState
    from vietdub.translation.segmenter import build_units
    ctx.rt.voices = VOICES
    cues = [_cue(1, 0, "Hi.", False), _cue(2, 1600, "Hello.", True)]
    assign_turn_speakers(cues)
    units = build_units("s", cues, complete=True)
    from vietdub.broker.session import Session
    s = Session(video_id="dQw4w9WgXcQ", tab_id=1, mode="vod_sync", runtime=ctx.rt, db=ctx.db, cache=ctx.cache, hub=ctx.hub,
                settings=Settings(voice="Minh Quân Pro", voice_alt="Minh Quân Pro"), glossary=ctx.glossary())
    s.speaker_rank = {TURN_SPEAKERS[0]: 0, TURN_SPEAKERS[1]: 1}
    assert s.voice_for(UnitState(units[1])) == "Trúc Ly"
