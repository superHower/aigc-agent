import { Layout, Tag } from 'antd'
import { NavLink, useLocation } from 'react-router-dom'

const items = [
  { key: '/', label: '工作台' },
  { key: '/tasks', label: '任务历史' },
  { key: '/composite', label: '长图拼接' },
]

export function AppHeader() {
  const location = useLocation()
  const selectedKey = location.pathname.startsWith('/tasks') ? '/tasks' : location.pathname.startsWith('/composite') ? '/composite' : '/'
  return <Layout.Header className="app-header">
    <div className="brand-mark">ECOM IMAGE STUDIO</div>
    <Tag color="green">IMAGE EDITOR</Tag>
    <nav className="app-nav" aria-label="页面导航">{items.map((item) => <NavLink key={item.key} to={item.key} className={selectedKey === item.key ? 'app-nav-link app-nav-link-active' : 'app-nav-link'} aria-current={selectedKey === item.key ? 'page' : undefined}>{item.label}</NavLink>)}</nav>
  </Layout.Header>
}
