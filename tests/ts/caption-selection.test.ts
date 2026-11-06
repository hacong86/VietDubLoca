import { describe, expect, it } from 'vitest';
import { pickTracks } from '../../apps/extension/src/content/captions';
import type { BridgePlayerInfo } from '../../packages/contracts/src';

const track = (language_code: string, kind?: string) => ({ language_code, kind, base_url: '' });
const info = (tracks: ReturnType<typeof track>[], original_track_index?: number): BridgePlayerInfo => ({
  ns: 'vietdub-bridge', type: 'player_info', nonce: 'test', video_id: '12345678901', tracks, original_track_index,
});

describe('caption language selection', () => {
  it('prefers Thai source captions over English translation, with author subtitles first', () => {
    const selected = pickTracks(info([track('en'), track('th', 'asr'), track('th')], 1));
    expect(selected.map((x) => [x.t.language_code, x.auto])).toEqual([['th', false], ['th', true], ['en', false]]);
  });
  it('uses auto captions as a source-language hint when no default is available', () => {
    expect(pickTracks(info([track('en'), track('th', 'asr')]))[0]?.t.language_code).toBe('th');
  });
  it('prefers original audio language to a viewer default in another language', () => {
    const player = { ...info([track('en'), track('th'), track('en', 'asr')], 0), original_language: 'th' };
    expect(pickTracks(player)[0]?.t.language_code).toBe('th');
  });
  it('rejects invalid tags and retains normal English behavior', () => {
    expect(pickTracks(info([track('bad instruction'), track('en', 'asr'), track('en-US')])).map((x) => x.t.language_code)).toEqual(['en-US', 'en']);
  });
});
