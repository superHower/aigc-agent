import { Layout } from 'antd'
import { AppstoreOutlined } from '@ant-design/icons'
import { NavLink, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import { Button } from 'antd'
import { useAuth } from './AuthProvider'

const items = [
  { key: '/', label: '首页' },
  { key: '/workspace', label: '工作台' },
  { key: '/tasks', label: '任务历史' },
  { key: '/account/credits', label: '我的积分' },
  { key: '/account/membership', label: '会员套餐' },
  { key: '/admin/packages', label: '套餐设置' },
  { key: '/admin/users', label: '用户管理' },
  { key: '/admin/audit', label: '操作审计' },
  { key: '/admin/attempts', label: '调用明细' },
  { key: '/admin', label: '经营总览' },
  { key: '/orders', label: '我的订单' },
  { key: '/admin/orders', label: '充值审核' },
  { key: '/admin/payment-settings', label: '收款设置' },
  { key: '/composite', label: '长图拼接' },
  { key: '/prompts', label: '提示词管理' },
  { key: '/channels', label: '渠道管理' },
]

export function AppHeader() {
  const { user } = useAuth()
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
        {items.filter((item) => (!item.key.startsWith('/admin') && item.key !== '/channels') || user?.role === 'admin').map((item) => (
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
      <Button type="text" onClick={async () => { await api.post('/auth/logout'); window.location.assign('/login') }}>退出登录</Button>
    </Layout.Header>
  )
}
