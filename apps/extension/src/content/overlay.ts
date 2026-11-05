/**
 * Overlay phụ đề Việt/song ngữ (FR-023, UI-07): Shadow DOM + scoped CSS, gắn trong phần tử player để hiện cả
 * fullscreen/theater. Chỉ dùng textContent (không bao giờ innerHTML với dữ liệu caption/bản dịch).
 * pointer-events: none cho vùng chữ → không cản seek bar.
 */
import type { OverlayPrefs, OverlaySeg } from '../shared/messages';

const CSS = `
:host { all: initial; }
.wrap { position:absolute; left:0; right:0; z-index: 60; display:flex; flex-direction:column; align-items:center;
  pointer-events:none; font-family: "Segoe UI", system-ui, -apple-system, "Noto Sans", Arial, sans-serif; }
.wrap.bottom { bottom: 64px; } .wrap.top { top: 36px; }
.line { max-width: 86%; margin: 2px 0; padding: 4px 12px; border-radius: 8px; background: rgba(8,10,16,.78); color:#fff;
  text-align:center; line-height:1.35; white-space: pre-wrap; overflow-wrap:anywhere; text-shadow: 0 1px 2px #000; }
.en { color:#d9dde6; font-size: .78em; }
.vi { color:#fff; font-weight: 600; }
.draft { color:#ffe08a; font-style: italic; font-size:.8em; }
.status { font-size: 13px; padding: 3px 10px; border-radius: 999px; background: rgba(20,24,34,.85); color:#fff; margin-bottom:6px; }
.status.warn { background: rgba(120,90,10,.92); } .status.error { background: rgba(140,30,30,.92); }
.prep { position:absolute; left:50%; top:50%; transform:translate(-50%,-50%); z-index:61; pointer-events:auto;
  min-width: 260px; max-width: 80%; padding: 14px 18px; border-radius: 12px; background: rgba(12,14,20,.9); color:#fff;
  font: 500 14px/1.4 "Segoe UI", system-ui, sans-serif; text-align:center; box-shadow: 0 6px 24px rgba(0,0,0,.45); }
.prep .bar { height: 6px; border-radius: 3px; background: rgba(255,255,255,.18); margin: 10px 0 12px; overflow:hidden; }
.prep .fill { height: 100%; width: 0; background: #7ee2a8; }
.prep button { font: 600 13px "Segoe UI", system-ui, sans-serif; color:#fff; background: rgba(255,255,255,.14);
  border: 1px solid rgba(255,255,255,.35); border-radius: 999px; padding: 5px 14px; cursor: pointer; }
.prep button:hover, .prep button:focus-visible { background: rgba(255,255,255,.26); outline: 2px solid #7ee2a8; }
@media (prefers-reduced-motion: no-preference) { .prep .fill { transition: width .25s; } }
@media (prefers-reduced-motion: no-preference) { .line { transition: opacity .15s; } }
`;

export class Overlay {
  private host: HTMLDivElement;
  private root: ShadowRoot;
  private wrap: HTMLDivElement;
  private statusEl: HTMLDivElement;
  private enEl: HTMLDivElement;
  private viEl: HTMLDivElement;
  private draftEl: HTMLDivElement;
  private segs: OverlaySeg[] = [];
  prefs: OverlayPrefs = { subtitle_mode: 'bilingual', subtitle_size: 22, subtitle_position: 'bottom' };
  private statusTimer: number | undefined;
  private prepEl: HTMLDivElement;
  private prepText: HTMLDivElement;
  private prepFill: HTMLDivElement;
  private onSkip: () => void = () => undefined;

  constructor() {
    this.host = document.createElement('div');
    this.host.setAttribute('data-vietdub', 'overlay');
    this.host.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:60;';
    this.root = this.host.attachShadow({ mode: 'closed' });
    const style = document.createElement('style');
    style.textContent = CSS;
    this.wrap = document.createElement('div');
    this.wrap.className = 'wrap bottom';
    this.wrap.setAttribute('aria-live', 'polite');
    this.statusEl = document.createElement('div');
    this.statusEl.className = 'status';
    this.statusEl.hidden = true;
    this.enEl = document.createElement('div');
    this.enEl.className = 'line en';
    this.viEl = document.createElement('div');
    this.viEl.className = 'line vi';
    this.viEl.lang = 'vi';
    this.draftEl = document.createElement('div');
    this.draftEl.className = 'line draft';
    this.draftEl.hidden = true;
    this.wrap.append(this.statusEl, this.enEl, this.viEl, this.draftEl);
    // Thẻ "Đang chuẩn bị thuyết minh": luôn hiện kể cả khi tắt phụ đề; chỉ nút Xem luôn nhận chuột.
    this.prepEl = document.createElement('div');
    this.prepEl.className = 'prep';
    this.prepEl.setAttribute('role', 'status');
    this.prepEl.hidden = true;
    this.prepText = document.createElement('div');
    const bar = document.createElement('div');
    bar.className = 'bar';
    this.prepFill = document.createElement('div');
    this.prepFill.className = 'fill';
    bar.append(this.prepFill);
    const skip = document.createElement('button');
    skip.type = 'button';
    skip.textContent = 'Xem luôn';
    skip.addEventListener('click', (e) => { e.stopPropagation(); this.onSkip(); });
    this.prepEl.append(this.prepText, bar, skip);
    this.root.append(style, this.wrap, this.prepEl);
    this.applyPrefs(this.prefs);
  }

  attach(parent: HTMLElement | null): void {
    if (parent && this.host.parentElement !== parent) parent.appendChild(this.host);
  }

  detach(): void {
    this.host.remove();
  }

  applyPrefs(p: OverlayPrefs): void {
    this.prefs = p;
    this.wrap.className = `wrap ${p.subtitle_position}`;
    this.wrap.style.fontSize = `${Math.max(14, Math.min(48, p.subtitle_size))}px`;
    this.wrap.hidden = false;                                  // tắt phụ đề chỉ ẩn dòng chữ (render), không ẩn trạng thái/chuẩn bị
  }

  setSegments(segs: OverlaySeg[]): void {
    const by = new Map(this.segs.map((s) => [s.segment_id, s]));
    for (const s of segs) {
      const old = by.get(s.segment_id);
      if (!old || s.revision >= old.revision) by.set(s.segment_id, s);
    }
    this.segs = Array.from(by.values()).sort((a, b) => a.start_ms - b.start_ms);
  }

  clear(): void {
    this.segs = [];
    this.enEl.textContent = '';
    this.viEl.textContent = '';
    this.draftEl.hidden = true;
    this.setStatus('', 'info');
  }

  /** Tiến độ chuẩn bị (0..1); null = ẩn. */
  setProgress(pct: number | null, onSkip: () => void): void {
    this.onSkip = onSkip;
    if (pct === null) {
      this.prepEl.hidden = true;
      return;
    }
    const v = Math.round(Math.max(0, Math.min(1, pct)) * 100);
    this.prepText.textContent = `Đang chuẩn bị thuyết minh tiếng Việt… ${v}%`;
    this.prepFill.style.width = `${v}%`;
    this.prepEl.hidden = false;
  }

  setDraft(text: string): void {
    this.draftEl.textContent = text ? `(nháp) ${text}` : '';
    this.draftEl.hidden = !text;
  }

  setStatus(text: string, level: 'info' | 'warn' | 'error', ttlMs = 0): void {
    this.statusEl.textContent = text;
    this.statusEl.className = `status ${level}`;
    this.statusEl.hidden = !text;
    if (this.statusTimer) clearTimeout(this.statusTimer);
    if (text && ttlMs) this.statusTimer = window.setTimeout(() => this.setStatus('', 'info'), ttlMs);
  }

  render(mediaMs: number): string | null {
    let cur: OverlaySeg | undefined;
    for (const s of this.segs) {
      if (s.start_ms <= mediaMs && mediaMs < s.end_ms + 400) cur = s;
      if (s.start_ms > mediaMs) break;
    }
    const mode = this.prefs.subtitle_mode;
    const vi = cur && mode !== 'off' ? (cur.status === 'blocked' ? '[Chưa dịch được] Bản dịch câu này chưa đạt kiểm tra' : cur.target_display) : '';
    const en = cur && mode === 'bilingual' ? cur.source_text : '';
    if (this.viEl.textContent !== vi) this.viEl.textContent = vi;
    if (this.enEl.textContent !== en) this.enEl.textContent = en;
    this.viEl.hidden = !vi;
    this.enEl.hidden = !en;
    return cur?.segment_id ?? null;
  }
}
