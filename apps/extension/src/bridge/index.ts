/**
 * Page bridge (MAIN world) — docs/03 §2, docs/05 §2.
 * CHỈ đọc dữ liệu trang cần cho caption: player response (captionTracks) và URL timedtext mà chính player gọi
 * (URL có tham số chống bot do YouTube thêm). Không có quyền backend/shell/token. Dữ liệu gửi về content là
 * KHÔNG tin cậy và được content kiểm lại (video_id, host/path allowlist).
 * Adapter version: yt-bridge-1 (không phụ thuộc lớp CSS duy nhất).
 */
(() => {
  const NS_IN = 'vietdub-content';
  const NS_OUT = 'vietdub-bridge';
  const w = window as unknown as Record<string, unknown> & { __vietdubBridge?: boolean };
  if (w.__vietdubBridge) return;
  w.__vietdubBridge = true;

  const captured: string[] = [];
  // Nội dung phản hồi timedtext mà CHÍNH player đã tải (YouTube chặn tải lại URL bằng tham số chống bot).
  const bodies: { video_id: string; lang: string; kind: string; body: string }[] = [];
  const MAX_BODY = 8 * 1024 * 1024;
  const isTimedtext = (url: string): URL | null => {
    try {
      const u = new URL(url, location.href);
      return u.hostname.endsWith('youtube.com') && u.pathname === '/api/timedtext' ? u : null;
    } catch {
      return null;
    }
  };
  const remember = (url: string) => {
    const u = isTimedtext(url);
    if (u) {
      captured.unshift(u.toString());
      captured.length = Math.min(captured.length, 20);
    }
  };
  const keep = (url: string, body: string) => {
    const u = isTimedtext(url);
    if (!u || !body || body.length > MAX_BODY) return;
    const item = { video_id: (u.searchParams.get('v') ?? '').slice(0, 20), lang: (u.searchParams.get('lang') ?? '').slice(0, 20),
      kind: (u.searchParams.get('kind') ?? '').slice(0, 10), body };
    const i = bodies.findIndex((b) => b.video_id === item.video_id && b.lang === item.lang && b.kind === item.kind);
    if (i >= 0) bodies.splice(i, 1);
    bodies.unshift(item);
    bodies.length = Math.min(bodies.length, 6);
  };
  // Chỉ ĐỌC request/response timedtext; không sửa gì.
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (this: XMLHttpRequest & { __vdUrl?: string }, method: string, url: string | URL, ...rest: unknown[]) {
    this.__vdUrl = String(url);
    remember(String(url));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (origOpen as any).call(this, method, url, ...rest);
  } as typeof XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.send = function (this: XMLHttpRequest & { __vdUrl?: string }, ...args: unknown[]) {
    const url = this.__vdUrl ?? '';
    if (isTimedtext(url)) {
      this.addEventListener('load', () => {
        try {
          const rt = this.responseType;
          const body = rt === '' || rt === 'text' ? this.responseText : rt === 'json' ? JSON.stringify(this.response)
            : rt === 'arraybuffer' ? new TextDecoder().decode(this.response as ArrayBuffer) : '';
          keep(url, body);
        } catch {
          /* bỏ qua */
        }
      });
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (origSend as any).apply(this, args);
  } as typeof XMLHttpRequest.prototype.send;
  const origFetch = window.fetch;
  window.fetch = function (this: typeof globalThis, input: RequestInfo | URL, init?: RequestInit) {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    remember(url);
    const p = origFetch.call(this, input, init);
    if (isTimedtext(url)) p.then((r) => r.clone().text()).then((t) => keep(url, t)).catch(() => undefined);
    return p;
  } as typeof window.fetch;

  interface PlayerLike {
    getPlayerResponse?: () => unknown;
    getVideoData?: () => { video_id?: string; title?: string; isLive?: boolean };
    loadModule?: (m: string) => void;
    unloadModule?: (m: string) => void;
    setOption?: (m: string, k: string, v: unknown) => void;
    getOption?: (m: string, k: string) => unknown;
  }
  const player = (): PlayerLike | null => {
    const el = document.getElementById('movie_player') ?? document.querySelector('#shorts-player');
    return (el as unknown as PlayerLike) ?? null;
  };

  function playerInfo() {
    const p = player();
    let resp: Record<string, unknown> | null = null;
    try {
      resp = (p?.getPlayerResponse?.() as Record<string, unknown>) ?? null;
    } catch {
      resp = null;
    }
    if (!resp) resp = (w.ytInitialPlayerResponse as Record<string, unknown>) ?? null;
    const details = (resp?.videoDetails ?? {}) as Record<string, unknown>;
    const tl = ((resp?.captions as Record<string, unknown> | undefined)?.playerCaptionsTracklistRenderer ?? {}) as Record<string, unknown>;
    const tracks = Array.isArray(tl.captionTracks) ? (tl.captionTracks as Record<string, unknown>[]) : [];
    const audioTracks = Array.isArray(tl.audioTracks) ? tl.audioTracks as Record<string, unknown>[] : [];
    const audioIndex = Number.isInteger(tl.defaultAudioTrackIndex) ? Number(tl.defaultAudioTrackIndex) : 0;
    const defaultIndex = audioTracks[audioIndex]?.defaultCaptionTrackIndex;
    const microformat = ((resp?.microformat as Record<string, unknown> | undefined)?.playerMicroformatRenderer ?? {}) as Record<string, unknown>;
    const originalLanguage = microformat.defaultAudioLanguage ?? details.defaultAudioLanguage;
    const vd = p?.getVideoData?.() ?? {};
    return {
      video_id: String(vd.video_id ?? details.videoId ?? '').slice(0, 20),
      title: String(vd.title ?? details.title ?? '').slice(0, 500),
      duration_s: Number(details.lengthSeconds ?? 0) || undefined,
      is_live: Boolean(vd.isLive ?? details.isLive ?? false),
      ...(typeof defaultIndex === 'number' && Number.isInteger(defaultIndex) && defaultIndex >= 0 && defaultIndex < Math.min(tracks.length, 100) ? { original_track_index: defaultIndex } : {}),
      ...(typeof originalLanguage === 'string' && originalLanguage.length <= 20 ? { original_language: originalLanguage } : {}),
      tracks: tracks.slice(0, 100).map((t) => ({
        base_url: String(t.baseUrl ?? '').slice(0, 4096),
        language_code: String(t.languageCode ?? '').slice(0, 20),
        kind: typeof t.kind === 'string' ? t.kind.slice(0, 10) : undefined,
        name: String(((t.name as Record<string, unknown>)?.simpleText ?? (((t.name as Record<string, unknown>)?.runs as { text?: string }[] | undefined)?.[0]?.text) ?? '')).slice(0, 200),
        vss_id: typeof t.vssId === 'string' ? t.vssId.slice(0, 100) : undefined,
      })),
      captured_timedtext: captured.slice(0, 20),
      captured_bodies: bodies.filter((b) => b.video_id === String(vd.video_id ?? details.videoId ?? '')),
    };
  }

  window.addEventListener('message', (ev: MessageEvent) => {
    if (ev.source !== window || !ev.data || ev.data.ns !== NS_IN || typeof ev.data.nonce !== 'string') return;
    const nonce = ev.data.nonce.slice(0, 64);
    if (ev.data.type === 'get_player_info') {
      window.postMessage({ ns: NS_OUT, type: 'player_info', nonce, ...playerInfo() }, location.origin);
    } else if (ev.data.type === 'trigger_captions') {
      // Bật caption tạm cho đúng track để player tự tải (kèm tham số hợp lệ), đợi bắt được nội dung, rồi trả trạng thái cũ.
      const p = player();
      const lang = typeof ev.data.lang === 'string' ? ev.data.lang.slice(0, 20) : 'en';
      const kind = ev.data.kind === 'asr' ? 'asr' : '';
      const vid = String(p?.getVideoData?.().video_id ?? '');
      let prev: unknown = null;
      try {
        prev = p?.getOption?.('captions', 'track') ?? null;
        p?.loadModule?.('captions');
        p?.setOption?.('captions', 'track', kind ? { languageCode: lang, kind } : { languageCode: lang });
      } catch {
        /* player không hỗ trợ */
      }
      const t0 = Date.now();
      const done = () => {
        const got = bodies.some((b) => b.video_id === vid && b.lang === lang && b.kind === kind);
        if (!got && Date.now() - t0 < 6000) return void setTimeout(done, 250);
        try {
          const prevLang = (prev as { languageCode?: string } | null)?.languageCode;
          if (prevLang) p?.setOption?.('captions', 'track', prev);
          else {
            p?.setOption?.('captions', 'track', {});
            p?.unloadModule?.('captions');
          }
        } catch {
          /* bỏ qua */
        }
        window.postMessage({ ns: NS_OUT, type: 'player_info', nonce, ...playerInfo() }, location.origin);
      };
      setTimeout(done, 300);
    }
  });
})();
