import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App'
import { ConfigProvider } from 'antd'
import 'antd/dist/reset.css'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#0071e3',
          colorSuccess: '#248a3d',
          colorWarning: '#b76b00',
          colorError: '#d93832',
          colorText: '#1d1d1f',
          colorTextSecondary: '#6e6e73',
          colorBgLayout: '#f5f5f7',
          colorBorder: '#d2d2d7',
          borderRadius: 10,
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
          controlHeight: 36,
        },
        components: {
          Card: { borderRadiusLG: 20, headerFontSize: 16, headerHeight: 60 },
          Button: { primaryShadow: 'none', defaultShadow: 'none', fontWeight: 500 },
          Table: { headerBg: '#fafafa', headerColor: '#6e6e73', borderColor: '#eeeef0' },
          Segmented: { trackBg: '#e8e8ed', itemSelectedBg: '#ffffff' },
          Tabs: { titleFontSize: 15, horizontalItemGutter: 30 },
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
)
