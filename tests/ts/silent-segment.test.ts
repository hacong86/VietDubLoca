import { afterEach, describe, expect, it, vi } from 'vitest';
import { AudioEngine } from '../../apps/extension/src/offscreen/engine';

describe('silent sound captions during playback', () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
  it('counts sound-only captions as prepared and never pauses to wait for speech', () => {
    vi.useFakeTimers();
    const gain = () => ({ connect: vi.fn(), gain: { setTargetAtTime: vi.fn() } });
    vi.stubGlobal('AudioContext', class {
      currentTime = 0;
      destination = {};
      state = 'running';
      createGain() { return gain(); }
    });
    const pauseVideo = vi.fn();
    const engine = new AudioEngine({ pauseVideo, playVideo: vi.fn(), status: vi.fn(), stopped: vi.fn(),
      replayPrompt: vi.fn(), progress: vi.fn(), notice: vi.fn() });
    engine.sourceComplete = true;
    engine.mode = 'study';
    engine.segments.set('sound', { segment_id: 'sound', revision: 1, start_ms: 0, end_ms: 5000, status: 'silent' });
    engine.beginPreload('start');
    expect(engine.preloadPct()).toBe(1);
    engine.endPreload(false);
    engine.anchor = { mediaMs: 0, audioTime: 0, rate: 1, playing: true, epoch: 0 };
    engine.tick();
    expect(pauseVideo).not.toHaveBeenCalled();
    expect(engine.stats.underruns).toBe(0);
  });
});
