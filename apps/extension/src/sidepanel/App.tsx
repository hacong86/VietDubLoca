import { useCallback, useEffect, useState } from 'react';
import { api, ApiError, getPairing } from '../shared/api';
import { isNs, type PanelStatus } from '../shared/messages';
import { ERROR_ACTION_VI, T } from '../shared/strings';
import { DiagTab } from './DiagTab';
import { GlossaryTab } from './GlossaryTab';
import { ModelsTab } from './ModelsTab';
import { SettingsTab } from './SettingsTab';
import { TranscriptTab } from './TranscriptTab';
import { Card, ErrorBox, sendBg } from './ui';
import { WatchTab, useActiveInfo } from './WatchTab';

type Tab = 'watch' | 'transcript' | 'glossary' | 'models' | 'settings' | 'diag';
const TABS: [Tab, string][] = [['watch', 'Xem'], ['transcript', 'Bản dịch'], ['glossary', 'Thuật ngữ'], ['models', 'Mô hình'], ['settings', 'Cài đặt'], ['diag', 'Chẩn đoán']];

export function App({ initialTab = 'watch', standalone = false }: { initialTab?: Tab; standalone?: boolean }) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [status, setStatus] = useState<PanelStatus | null>(null);
  const [stats, setStats] = useState<null | Parameters<typeof DiagTab>[0]['stats']>(null);
  const [paired, setPaired] = useState<boolean | null>(null);
  const [pairErr, setPairErr] = useState<string | null>(null);
  const [pairing, setPairing] = useState(false);
  const [settings, setSettings] = useState<Record<string, Record<string, unknown>> | null>(null);
  const [settingsVersion, setSettingsVersion] = useState<number | null>(null);
  const { info, refresh } = useActiveInfo();

  useEffect(() => {
    const onMsg = (m: unknown) => {
      if (!isNs(m)) return;
      const x = m as { type: string; status?: PanelStatus; stats?: typeof stats };
      if (x.type === 'status' && x.status) {
        setStatus(x.status);
        if (x.stats) setStats(x.stats);
      }
    };
    chrome.runtime.onMessage.addListener(onMsg);
    void sendBg<{ status: PanelStatus; stats: typeof stats } | undefined>({ type: 'offscreen.get_status' }).then((r) => {
      if (r?.status) {
        setStatus(r.status);
        setStats(r.stats);
      }
    }).catch(() => undefined);
    return () => chrome.runtime.onMessage.removeListener(onMsg);
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      const r = await api<{ version: number; value: Record<string, Record<string, unknown>> }>('GET', '/v1/settings');
      setSettings(r.value);
      setSettingsVersion(r.version);
      setPaired(true);
      const setup = await api<{ ready: boolean }>('GET', '/v1/setup');
      if (!setup.ready) setTab('models');
    } catch (e) {
      if (e instanceof ApiError && (e.code === 'AUTH_REQUIRED' || e.code === 'AUTH_EXPIRED' || e.code === 'CONNECT_FAILED')) setPaired(false);
    }
  }, []);

  useEffect(() => {
    void getPairing().then((p) => (p ? loadSettings() : setPaired(false)));
  }, [loadSettings]);

  const doPair = async () => {
    setPairing(true);
    setPairErr(null);
    try {
      const r = await sendBg<{ ok: boolean; code?: string }>({ type: 'panel.pair' });
      if (r?.ok) { await loadSettings(); refresh(); }
      else setPairErr(r?.code ?? 'CONNECT_FAILED');
    } catch { setPairErr('CONNECT_FAILED'); }
    finally { setPairing(false); }
  };

  const saveSettings = async (patch: Record<string, Record<string, unknown>>) => {
    if (Object.keys(patch).length === 0) return loadSettings();
    // cập nhật lạc quan để thanh trượt mượt; server kiểm allowlist/khoảng
    setSettings((s) => {
      const n = { ...(s ?? {}) };
      for (const [k, v] of Object.entries(patch)) n[k] = { ...(n[k] ?? {}), ...v };
      return n;
    });
    try {
      const r = await api<{ version: number; value: Record<string, Record<string, unknown>> }>('PUT', '/v1/settings', { version: settingsVersion, value: patch });
      setSettings(r.value);
      setSettingsVersion(r.version);
      await sendBg({ type: 'panel.settings_changed' });
    } catch (e) {
      await loadSettings();
      throw e;
    }
  };

  const title = status?.video?.title || info?.tab?.title || 'VietDub Local';
  const conn = status?.connection;
  return (
    <div className="app">
      <header className="top">
        <div className="title-row">
          <h1 title={title}>{title}</h1>
          <span className={`badge ${paired ? 'ok' : 'warn'}`} title="Toàn bộ AI chạy trên máy này">{T.local_only}</span>
        </div>
        {conn === 'reconnecting' && <div className="status err small" style={{ marginTop: 6 }} role="alert">{T.reconnecting}</div>}
        {paired && (
          <nav className="tabs" role="tablist" aria-label="Các mục">
            {TABS.map(([k, label]) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>
            ))}
          </nav>
        )}
      </header>
      <main>
        {paired === false && (
          <Card title="Kết nối chương trình VietDub Local trên máy">
            <div className="stack">
              <p className="small" style={{ margin: 0 }}>VietDub dịch phụ đề YouTube sang tiếng Việt và đọc thuyết minh bằng AI chạy <b>ngay trên máy tính của bạn</b>.
                Mạng chỉ dùng để xem YouTube và tải mô hình lần đầu — không gửi lời thoại cho dịch vụ AI nào.</p>
              <button className="btn big primary" onClick={() => void doPair()} disabled={pairing}>{pairing ? T.connecting : T.connect}</button>
              <p className="small" style={{ margin: 0 }}>Chưa cài chương trình trên máy? Giải nén gói Windows và nhấp đúp <b>Setup.cmd</b>. Sau khi kết nối, mở <b>Mô hình → Chuẩn bị để sử dụng</b>.</p>
              {pairErr && <ErrorBox error={new ApiError(pairErr, pairErr === 'NATIVE_HOST_MISSING' ? 'Chưa tìm thấy chương trình VietDub Local trên máy.' : 'Không kết nối được chương trình trên máy.', 0,
                { action_vi: ERROR_ACTION_VI[pairErr] ?? 'Mở VietDub Local rồi thử lại.' })} />}
              <p className="small muted" style={{ margin: 0 }}>Lần đầu kết nối có thể mất 30–60 giây để nạp mô hình. Khóa phiên chỉ nằm trong tiện ích, trang YouTube không đọc được.</p>
            </div>
          </Card>
        )}
        {paired && tab === 'watch' && <WatchTab status={status} info={info} refreshInfo={refresh} settings={settings} saveSettings={saveSettings} />}
        {paired && tab === 'transcript' && <TranscriptTab status={status} tabId={info?.tab_id ?? null} />}
        {paired && tab === 'glossary' && <GlossaryTab />}
        {paired && tab === 'models' && <ModelsTab />}
        {paired && tab === 'settings' && <SettingsTab settings={settings} saveSettings={saveSettings} videoId={info?.tab?.video_id ?? null} />}
        {paired && tab === 'diag' && <DiagTab status={status} stats={stats} />}
        {standalone && paired === null && <p className="muted">Đang tải…</p>}
      </main>
    </div>
  );
}
