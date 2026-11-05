import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { cleanCueText, cuesFromTranscript, parseJson3, parseSubtitles } from '../../packages/captions/src';

describe('SRT/VTT parser (FR-007)', () => {
  it('parses fixtures with BOM/CRLF', () => {
    const srt = readFileSync('examples/fragmented.srt', 'utf8');
    const r = parseSubtitles('﻿' + srt.replace(/\n/g, '\r\n'));
    expect(r.format).toBe('srt');
    expect(r.cues.map((c) => c.startMs)).toEqual([10000, 12000, 14000, 17000]);
    expect(r.errors).toEqual([]);
    const vtt = parseSubtitles(readFileSync('examples/rolling.vtt', 'utf8'));
    expect(vtt.format).toBe('vtt');
    expect(vtt.cues.length).toBe(4);
    expect(vtt.warnings.some((w) => w.reason.includes('chồng'))).toBe(true);
  });
  it('reports errors with line numbers and never keeps markup', () => {
    const r = parseSubtitles('1\n00:00:05,000 --> 00:00:01,000\nbad\n\n2\n00:00:06,000 --> 00:00:07,000\n<script>alert(1)</script><b>ok</b> &amp; fine\n');
    expect(r.errors[0]).toEqual({ line: 2, reason: expect.any(String) });
    expect(r.cues[0]!.text).toBe('alert(1)ok & fine');
    expect(r.cues[0]!.text).not.toContain('<');
  });
  it('rejects garbage without crashing', () => {
    const r = parseSubtitles('this is not a subtitle file');
    expect(r.cues).toEqual([]);
    expect(r.errors.length).toBe(1);
  });
  it('voice labels kept as metadata', () => {
    expect(cleanCueText('<v Bob>Hi there')).toEqual({ text: 'Hi there', voice: 'Bob' });
  });
});

describe('YouTube json3 + transcript DOM', () => {
  it('parses json3 events and trims overlap', () => {
    const cues = parseJson3({ events: [
      { tStartMs: 0, dDurationMs: 3000, segs: [{ utf8: 'Hello ' }, { utf8: 'world' }] },
      { tStartMs: 2000, dDurationMs: 2000, aAppend: 1, segs: [{ utf8: '\n' }] },
      { tStartMs: 2500, dDurationMs: 2000, segs: [{ utf8: 'next &amp; line' }] },
    ] });
    expect(cues.map((c) => [c.startMs, c.endMs, c.text])).toEqual([[0, 2500, 'Hello world'], [2500, 4500, 'next & line']]);
    expect(() => parseJson3({})).toThrow();
  });
  it('transcript rows → cues', () => {
    const c = cuesFromTranscript([{ ts: '0:05', text: 'a' }, { ts: '0:07', text: 'b' }, { ts: '1:02:03', text: 'c' }]);
    expect(c.map((x) => [x.startMs, x.endMs])).toEqual([[5000, 7000], [7000, 15000], [3723000, 3727000]]);
  });
});

import { parseTimedtextBody } from '../../packages/captions/src';
describe('timedtext body formats', () => {
  it('json3, srv3 and srv1', () => {
    expect(parseTimedtextBody('{"wireMagic":"pb3","events":[{"tStartMs":100,"dDurationMs":900,"segs":[{"utf8":"Hi"}]}]}')[0]!.text).toBe('Hi');
    const s3 = parseTimedtextBody('<timedtext format="3"><body><p t="1000" d="2000">Hello &amp; <s>world</s></p><p t="3000" d="500">Two<br/>lines</p></body></timedtext>');
    expect(s3.map((c) => [c.startMs, c.endMs, c.text])).toEqual([[1000, 3000, 'Hello & world'], [3000, 3500, 'Two lines']]);
    const s1 = parseTimedtextBody('<transcript><text start="1.5" dur="2">It&#39;s ok</text></transcript>');
    expect(s1[0]).toMatchObject({ startMs: 1500, endMs: 3500, text: "It's ok" });
    expect(parseTimedtextBody('')).toEqual([]);
  });
});
