import { createRoot } from 'react-dom/client';
import { App } from '../sidepanel/App';
import '../sidepanel/styles.css';

// Trang cài đặt đầy đủ: cùng thành phần với bảng bên, mở sẵn tab Cài đặt.
createRoot(document.getElementById('root')!).render(<App initialTab="settings" standalone />);
