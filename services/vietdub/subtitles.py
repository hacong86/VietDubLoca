"""Parse/ghi SRT & VTT (docs/05 §3, docs/09 §Export). Parser chính của extension nằm ở TS
(packages/captions); bản Python dùng cho export, test fixture và kiểm tra phía broker."""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_BYTES = 10 * 1024 * 1024
MAX_CUES = 100_000
_TS = re.compile(r"^\s*(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


class SubtitleError(ValueError):
    def __init__(self, line: int, reason: str) -> None:
        super().__init__(f"line {line}: {reason}")
        self.line = line
        self.reason = reason


@dataclass
class ParsedCue:
    index: int
    start_ms: int
    end_ms: int
    text: str
    line: int


def _ms(h: str | None, m: str, s: str, frac: str) -> int:
    return ((int(h or 0) * 60 + int(m)) * 60 + int(s)) * 1000 + int(frac.ljust(3, "0")[:3])


def parse(data: bytes | str) -> list[ParsedCue]:
    if isinstance(data, bytes):
        if len(data) > MAX_BYTES:
            raise SubtitleError(0, "file too large")
        text: str = data.decode("utf-8-sig")
    else:
        text = str(data).lstrip(chr(0xFEFF))
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues: list[ParsedCue] = []
    i = 0
    if lines and lines[0].startswith("WEBVTT"):
        i = 1
    while i < len(lines):
        line = lines[i]
        m = _TS.match(line)
        if not m:
            i += 1
            continue
        start = _ms(*m.group(1, 2, 3, 4))
        end = _ms(*m.group(5, 6, 7, 8))
        if end < start:
            raise SubtitleError(i + 1, "end before start")
        at = i + 1
        i += 1
        body = []
        while i < len(lines) and lines[i].strip() != "":
            if _TS.match(lines[i]):
                break
            body.append(lines[i])
            i += 1
        cues.append(ParsedCue(len(cues) + 1, start, end, "\n".join(body), at))
        if len(cues) > MAX_CUES:
            raise SubtitleError(at, "too many cues")
    return cues


def _fmt(ms: int, sep: str) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, frac = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{frac:03d}"


def write_srt(cues: list[tuple[int, int, str]]) -> str:
    out = []
    for n, (s, e, t) in enumerate(cues, 1):
        out.append(f"{n}\n{_fmt(s, ',')} --> {_fmt(e, ',')}\n{t}\n")
    return "\n".join(out)


def write_vtt(cues: list[tuple[int, int, str]]) -> str:
    out = ["WEBVTT", ""]
    for s, e, t in cues:
        safe = t.replace("-->", "→")
        out.append(f"{_fmt(s, '.')} --> {_fmt(e, '.')}\n{safe}\n")
    return "\n".join(out)
