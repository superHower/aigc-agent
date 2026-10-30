import { Layout } from 'antd'
import { AppstoreOutlined } from '@ant-design/icons'
import { NavLink, useLocation } from 'react-router-dom'

const items = [
  { key: '/', label: '首页' },
  { key: '/workspace', label: '工作台' },
  { key: '/tasks', label: '任务历史' },
  { key: '/composite', label: '长图拼接' },
  { key: '/prompts', label: '提示词管理' },
  { key: '/channels', label: '渠道管理' },
]

export function AppHeader() {
  const location = useLocation()
  const selectedKey =
    items.find((item) => item.key !== '/' && location.pathname.startsWith(item.key))?.key ?? '/'
  return (
    <Layout.Header className="app-header">
      <NavLink to="/" className="brand-mark" aria-label="AI 生图首页">
        <span className="brand-symbol">
          <AppstoreOutlined />
        </span>
        <span>AI 生图</span>
      </NavLink>
      <nav className="app-nav" aria-label="页面导航">
        {items.map((item) => (
          <NavLink
            key={item.key}
            to={item.key}
            className={
              selectedKey === item.key ? 'app-nav-link app-nav-link-active' : 'app-nav-link'
            }
            aria-current={selectedKey === item.key ? 'page' : undefined}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </Layout.Header>
  )
}
