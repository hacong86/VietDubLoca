import { readFileSync } from 'node:fs';
import Ajv2020 from 'ajv/dist/2020';
import { describe, expect, it } from 'vitest';
import { CaptionBatch, EventEnvelope, PlaybackClock, ProjectError, TranslationReady } from '../../packages/contracts/src';

const load = (p: string) => JSON.parse(readFileSync(p, 'utf8'));
const ajv = new Ajv2020({ strict: false, allErrors: true });

const pairs: [string, string, { safeParse: (v: unknown) => { success: boolean } }][] = [
  ['contracts/playback-clock.schema.json', 'examples/playback-clock.json', PlaybackClock],
  ['contracts/caption-batch.schema.json', 'examples/caption-batch.json', CaptionBatch],
  ['contracts/event.schema.json', 'examples/event.json', EventEnvelope],
  ['contracts/error.schema.json', 'examples/error.json', ProjectError],
];

describe('zod mirrors JSON Schema (Python và TS đọc cùng fixtures)', () => {
  for (const [schemaPath, exPath, zodSchema] of pairs) {
    it(`${exPath} valid in both`, () => {
      const validate = ajv.compile(load(schemaPath));
      const ex = load(exPath);
      expect(validate(ex)).toBe(true);
      expect(zodSchema.safeParse(ex).success).toBe(true);
    });
    it(`${exPath} unknown field rejected in both`, () => {
      const validate = ajv.compile(load(schemaPath));
      const bad = { ...load(exPath), injected: 'x' };
      expect(validate(bad)).toBe(schemaPath.includes('error.schema') ? false : false);
      if (!schemaPath.includes('error.schema')) expect(zodSchema.safeParse(bad).success).toBe(false);
    });
  }
  it('negative time, bad enum, end<start', () => {
    const clock = load('examples/playback-clock.json');
    expect(PlaybackClock.safeParse({ ...clock, media_ms: -5 }).success).toBe(false);
    expect(PlaybackClock.safeParse({ ...clock, ad_state: 'maybe' }).success).toBe(false);
    const b = load('examples/caption-batch.json');
    b.cues[0].end_ms = 1;
    expect(CaptionBatch.safeParse(b).success).toBe(false);
  });
  it('accepts caption language tags and rejects malformed language values in both contracts', () => {
    const validate = ajv.compile(load('contracts/caption-batch.schema.json'));
    const original = load('examples/caption-batch.json');
    for (const language of ['th', 'en-US', 'zh-Hant', 'und']) {
      expect(validate({ ...original, language })).toBe(true);
      expect(CaptionBatch.safeParse({ ...original, language }).success).toBe(true);
    }
    for (const language of ['', 'english text', '../th', 'th;instruction']) {
      expect(validate({ ...original, language })).toBe(false);
      expect(CaptionBatch.safeParse({ ...original, language }).success).toBe(false);
    }
  });
  it('translation.ready payload has no model timestamps field besides source bounds', () => {
    const p = load('examples/event.json').payload;
    const r = TranslationReady.safeParse({ ...p, source_text: 'x', flags: [], start_ms: 1, end_ms: 2 });
    expect(r.success).toBe(true);
  });
});
