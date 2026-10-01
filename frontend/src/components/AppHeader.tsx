import { Layout, Menu, Tag } from 'antd'
import { NavLink, useLocation } from 'react-router-dom'

const items = [
  { key: '/', label: <NavLink to="/">工作台</NavLink> },
  { key: '/tasks', label: <NavLink to="/tasks">任务历史</NavLink> },
  { key: '/composite', label: <NavLink to="/composite">长图拼接</NavLink> },
]

export function AppHeader() {
  const location = useLocation()
  const selectedKey = location.pathname.startsWith('/tasks') ? '/tasks' : location.pathname.startsWith('/composite') ? '/composite' : '/'
  return <Layout.Header className="app-header">
    <div className="brand-mark">ECOM IMAGE STUDIO</div>
    <Tag color="green">IMAGE EDITOR</Tag>
    <Menu className="app-nav" theme="dark" mode="horizontal" selectedKeys={[selectedKey]} items={items} />
  </Layout.Header>
}
