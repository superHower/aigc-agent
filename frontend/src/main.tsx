import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App'
import { ConfigProvider, theme } from 'antd'
import 'antd/dist/reset.css'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#ccff00',
          colorInfo: '#ccff00',
          colorSuccess: '#02dba3',
          colorWarning: '#ffc453',
          colorError: '#ff7078',
          colorText: '#ffffff',
          colorTextSecondary: '#a3a3a3',
          colorTextTertiary: '#8b8b8b',
          colorBgBase: '#000000',
          colorBgLayout: '#000000',
          colorBgContainer: '#080808',
          colorBgElevated: '#171717',
          colorBorder: '#333333',
          colorBorderSecondary: '#262626',
          colorLink: '#ccff00',
          colorLinkHover: '#e0ff66',
          borderRadius: 6,
          fontFamily:
            'Inter, "Source Han Sans", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", system-ui, sans-serif',
          controlHeight: 36,
          boxShadow: 'none',
          boxShadowSecondary: '0 12px 40px rgba(0, 0, 0, 0.45)',
        },
        components: {
          Card: { borderRadiusLG: 10, headerFontSize: 16, headerHeight: 56 },
          Button: {
            colorPrimary: '#ccff00', colorPrimaryHover: '#e0ff66', colorPrimaryActive: '#b3e000',
            primaryColor: '#000000', primaryShadow: 'none', defaultShadow: 'none',
            borderRadius: 0, fontWeight: 500,
          },
          Table: { headerBg: '#171717', headerColor: '#d8d8d8', borderColor: '#262626', rowHoverBg: '#171717' },
          Segmented: { trackBg: '#171717', itemSelectedBg: '#333333', itemSelectedColor: '#ccff00' },
          Tabs: { titleFontSize: 14, horizontalItemGutter: 30, inkBarColor: '#ccff00', itemSelectedColor: '#ccff00' },
          Input: { activeBorderColor: '#ccff00', hoverBorderColor: '#666666', activeShadow: '0 0 0 2px rgba(204,255,0,0.1)' },
          InputNumber: { activeBorderColor: '#ccff00', hoverBorderColor: '#666666', activeShadow: '0 0 0 2px rgba(204,255,0,0.1)' },
          Select: { activeBorderColor: '#ccff00', hoverBorderColor: '#666666', optionSelectedBg: '#293300' },
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
)
