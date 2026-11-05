import asyncio
import json

import pytest

from vietdub.subtitles import SubtitleError, parse, write_srt
from vietdub.translation.glossary import Glossary, protect, restore
from vietdub.translation.llm import LlmResult
from vietdub.translation.prompt import build_request, UnitInput
from vietdub.translation.segmenter import build_units
from vietdub.translation.service import (ModelFingerprint, UnitRequest, plan_batches, translate_batch,
                                         translation_cache_key)
from vietdub.translation.spoken import to_spoken
from vietdub.translation.text import Cue, dedupe_rolling, normalize_text
from vietdub.translation.validate import parse_and_check
from vietdub.contracts import REPO_ROOT


def cues_from(path: str) -> list[Cue]:
    out = []
    for p in parse((REPO_ROOT / path).read_bytes()):
        t, sp = normalize_text(p.text)
        out.append(Cue(f"c{p.index}", p.start_ms, p.end_ms, t, p.text, True, sp))
    return out


def test_fragmented_srt_builds_one_unit_in_order():
    units = build_units("src", cues_from("examples/fragmented.srt"), complete=True)
    assert units[0].source_text == "Make sure you don't delete the original file before checking the copy."
    assert units[0].cue_ids == ["c1", "c2", "c3"]
    assert (units[0].start_ms, units[0].end_ms) == (10000, 16000)
    assert units[1].source_text == "Open the Inspector and uncheck Apply Root Motion."
    assert units[1].start_ms == 17000


def test_rolling_vtt_dedup_keeps_real_repetition():
    cues = dedupe_rolling(cues_from("examples/rolling.vtt"))
    units = build_units("src", cues, complete=True)
    texts = [u.source_text for u in units]
    assert texts[0] == "Do not delete the original file."
    assert "No, no, no." in texts[1]


def test_no_split_after_negation_on_pause():
    cues = [Cue("a", 0, 1000, "You should not"), Cue("b", 2500, 3500, "delete it."),
            Cue("c", 5000, 6000, "Next one.")]
    units = build_units("s", cues, complete=True)
    assert units[0].source_text == "You should not delete it."


def test_pause_split_and_pending_tail():
    cues = [Cue("a", 0, 1000, "first part here"), Cue("b", 2000, 3000, "second part here")]
    units = build_units("s", cues, complete=False)
    assert units[0].boundary_reason == "pause" and units[0].final
    assert units[-1].final is False


def test_cap_split_prefers_comma_and_keeps_all_words():
    words = " ".join(f"w{i}" for i in range(40)) + ", " + " ".join(f"x{i}" for i in range(40)) + "."
    units = build_units("s", [Cue("a", 0, 11000, words)], complete=True)
    assert len(units) >= 2
    assert units[0].boundary_reason == "cap_comma"
    joined = " ".join(u.source_text for u in units)
    assert joined == words
    assert all(u.word_count() <= 60 for u in units)


def test_decimal_and_abbreviation_not_split():
    units = build_units("s", [Cue("a", 0, 5000, "Set it to 0.5 seconds, e.g. for tests. Done.")], complete=True)
    assert [u.source_text for u in units] == ["Set it to 0.5 seconds, e.g. for tests.", "Done."]


def test_normalize_strips_markup_and_entities():
    t, sp = normalize_text("<v Bob>Hello &amp; <b>world</b><00:00:01.000> <script>x</script>")
    assert sp == "Bob"
    assert "<" not in t and "&amp;" not in t and "Hello & world" in t


def test_subtitle_errors_have_line_numbers():
    with pytest.raises(SubtitleError) as e:
        parse("1\n00:00:05,000 --> 00:00:01,000\nbad\n")
    assert e.value.line == 2
    assert parse(b"\xef\xbb\xbf1\r\n00:00:01,000 --> 00:00:02,000\r\nhi\r\n")[0].text == "hi"


def test_protect_and_restore_glossary():
    g = Glossary.from_dict(json.loads((REPO_ROOT / "data/glossary.example.json").read_text(encoding="utf-8")))
    p = protect("Open the Inspector and uncheck Apply Root Motion, then run git reset --hard.", g, "unity")
    assert "Apply Root Motion" not in p.text and "Inspector" not in p.text
    assert "git reset --hard" not in p.text
    assert restore(p.text, p.mapping).startswith("Open the Inspector and uncheck Apply Root Motion")
    p2 = protect("Increase the margin of the page.", g, "business")
    assert p2.hints == []           # "gross margin" không áp cho "margin"
    p3 = protect("The gross margin fell.", g, "business")
    assert p3.hints and p3.hints[0]["target"] == "biên lợi nhuận gộp"


def test_validator_blocks_bad_structures():
    exp = {"u1": {"source": "uncheck VDTERM_0001", "counts": {"VDTERM_0001": 1}, "mapping": {"VDTERM_0001": "Apply Root Motion"}}}
    ok = parse_and_check('{"translations":[{"segment_id":"u1","target_text":"bỏ chọn VDTERM_0001"}]}', "stop", exp)
    assert ok.ok
    lit = parse_and_check('{"translations":[{"segment_id":"u1","target_text":"bỏ chọn Apply Root Motion"}]}', "stop", exp)
    assert lit.ok   # literal chính xác tương đương placeholder
    assert not parse_and_check('{"translations":[{"segment_id":"u1","target_text":"bỏ chọn"}]}', "stop", exp).ok
    assert not parse_and_check('{"translations":[{"segment_id":"u9","target_text":"x"}]}', "stop", exp).ok
    assert not parse_and_check('<think>hm</think>{"translations":[]}', "stop", exp).ok
    assert not parse_and_check('{"translations":[{"segment_id":"u1","target_text":"bỏ chọn VDTERM_0001"}]}', "length", exp).ok
    assert not parse_and_check('{"translations":[{"segment_id":"u1","target_text":"a VDTERM_0001","extra":1}]}', "stop", exp).ok


def test_spoken_does_not_change_display_and_escapes_tags():
    disp = "Tắt GPU [cười] rồi mở Inspector"
    sp = to_spoken(disp, {"GPU": "gờ pê u"})
    assert "gờ pê u" in sp and "[" not in sp and disp == "Tắt GPU [cười] rồi mở Inspector"


def test_prompt_context_separate_and_reduced_before_source():
    g = Glossary()
    long_ctx = ["x " * 6000]
    req = build_request([UnitInput("u1", "Hello world.")], context_before=long_ctx + ["prev"], context_after=["next"],
                        topic="general", glossary=g, model_alias="m", sampling={"temperature": 0.7,
                                                                             "chat_template_kwargs": {"enable_thinking": False}})
    body = json.loads(req.user_json)
    assert body["segments"] == [{"segment_id": "u1", "source_text": "Hello world."}]
    assert long_ctx[0] not in body["context_before"]
    assert req.payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert req.payload["response_format"]["json_schema"]["schema"]["properties"]["translations"]["maxItems"] == 1


class FakeBackend:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def chat(self, payload):
        self.calls.append(payload)
        r = self.replies.pop(0)
        return LlmResult(r, "stop", False, None, 10.0)


FP = ModelFingerprint("qwen35_4b_q5", "qwen35_4b_q5", "a" * 64, "b11126", {"temperature": 0.7})


def _u(sid, text, before=None):
    return UnitRequest(sid, text, "h" + sid, before or [], [])


def test_translate_repair_once_then_block():
    g = Glossary()
    bad = '{"translations":[{"segment_id":"u1","target_text":""}]}'
    be = FakeBackend(["nope", bad])
    [r] = asyncio.run(translate_batch(be, [_u("u1", "Hi.")], topic="general", glossary=g, fp=FP))
    assert r.status == "BLOCKED" and len(be.calls) == 2
    be2 = FakeBackend(["nope", '{"translations":[{"segment_id":"u1","target_text":"Chào."}]}'])
    [r2] = asyncio.run(translate_batch(be2, [_u("u1", "Hi.")], topic="general", glossary=g, fp=FP))
    assert r2.status == "READY" and "REPAIRED" in r2.flags


def test_cache_key_differs_by_context_model_glossary():
    a = translation_cache_key(_u("u1", "It works.", ["The app"]), topic="general", glossary_version=1, fp=FP)
    b = translation_cache_key(_u("u1", "It works.", ["The car"]), topic="general", glossary_version=1, fp=FP)
    c = translation_cache_key(_u("u1", "It works.", ["The app"]), topic="general", glossary_version=2, fp=FP)
    fp2 = ModelFingerprint("gemma", "gemma", "c" * 64, "b11126", {"temperature": 1.0})
    d = translation_cache_key(_u("u1", "It works.", ["The app"]), topic="general", glossary_version=1, fp=fp2)
    assert len({a, b, c, d}) == 4


def test_plan_batches_limits():
    us = [_u(f"u{i}", "word " * 50) for i in range(5)]
    bs = plan_batches(us)
    assert all(len(b) <= 3 and sum(len(x.source_text.split()) for x in b) <= 120 for b in bs)


def test_write_srt_roundtrip():
    s = write_srt([(1000, 2500, "Xin chào"), (3000, 4000, "Tạm biệt")])
    cues = parse(s)
    assert [(c.start_ms, c.end_ms, c.text) for c in cues] == [(1000, 2500, "Xin chào"), (3000, 4000, "Tạm biệt")]
