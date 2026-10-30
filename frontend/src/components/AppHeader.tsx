import { useEffect, useState } from 'react'
import { Button, Drawer, Layout, Popover, Space, Tag, Typography } from 'antd'
import { AppstoreOutlined, DownOutlined, MenuOutlined, UserOutlined } from '@ant-design/icons'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from './AuthProvider'

const management = [
  { key: '/admin', label: '经营总览' }, { key: '/admin/users', label: '用户管理' },
  { key: '/admin/orders', label: '充值审核' }, { key: '/admin/packages', label: '套餐设置' },
  { key: '/admin/payment-settings', label: '收款设置' }, { key: '/channels', label: '渠道管理' },
  { key: '/admin/attempts', label: '调用明细' }, { key: '/admin/audit', label: '操作审计' },
]
type Account = { available: number; frozen: number; active: boolean; expires_at: string | null; concurrency: number }

export function AppHeader() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const location = useLocation()
  const navigate = useNavigate()
  const [account, setAccount] = useState<Account>()
  const [unavailable, setUnavailable] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  useEffect(() => {
    if (!user || isAdmin) return
    let disposed = false
    const refresh = () => Promise.all([api.get('/account/credits'), api.get('/account/membership')]).then(([c, m]) => {
      if (!disposed) { setAccount({ ...c.data, ...m.data }); setUnavailable(false) }
    }).catch(() => { if (!disposed) setUnavailable(true) })
    void refresh()
    const timer = window.setInterval(() => void refresh(), 10000)
    window.addEventListener('focus', refresh)
    return () => { disposed = true; window.clearInterval(timer); window.removeEventListener('focus', refresh) }
  }, [user?.id, isAdmin, location.pathname])
  const items = isAdmin ? [
    { key: '/', label: '首页' }, { key: '/workspace', label: '工作台' },
    { key: '/tasks', label: '任务记录' }, { key: '/prompts', label: '提示词管理' },
  ] : [
    { key: '/', label: '首页' }, { key: '/workspace', label: '工作台' }, { key: '/tasks', label: '任务历史' },
    { key: '/account/credits', label: '我的积分' }, { key: '/account/membership', label: '会员套餐' },
    { key: '/orders', label: '我的订单' }, { key: '/prompts', label: '提示词管理' },
  ]
  const selected = (key: string) => key === '/' ? location.pathname === '/' : location.pathname === key || location.pathname.startsWith(key + '/')
  const currentManagement = management.find(item => item.key === location.pathname)
  const details = <div className="account-popover">
    <Space><UserOutlined /><Typography.Text strong>{user?.username}</Typography.Text><Tag color={isAdmin ? 'purple' : account?.active ? 'blue' : 'default'}>{isAdmin ? '超级管理员' : account?.active ? '会员' : '普通用户'}</Tag></Space>
    {isAdmin ? <><p>生图不限积分使用，无需购买套餐。</p><Typography.Text type="secondary">管理用户、充值、渠道和平台数据。</Typography.Text></> : <>
      {unavailable && <p>账户信息暂时无法更新，请稍后重试。</p>}
      <p>可用积分：{account?.available ?? '—'}　冻结：{account?.frozen ?? '—'}</p>
      <p>会员到期：{account?.expires_at ? new Date(account.expires_at).toLocaleString() : '未开通'}</p>
      <p>跨任务并发：{account?.concurrency ?? '—'} 张</p>
      <Button type="link" onClick={() => navigate('/account/credits')}>积分明细</Button><Button type="link" onClick={() => navigate('/account/membership')}>会员套餐</Button>
    </>}
    <div className="account-popover-footer"><Button block onClick={async () => { await api.post('/auth/logout'); window.location.assign('/login') }}>退出登录</Button></div>
  </div>
  const sidebar = <><NavLink to="/admin" className="brand-mark sidebar-brand" onClick={() => setSidebarOpen(false)}><span className="brand-symbol"><AppstoreOutlined /></span><span>AI 生图管理</span></NavLink><nav aria-label="管理导航" className="admin-sidebar-nav">{management.map(item => <NavLink key={item.key} to={item.key} onClick={() => setSidebarOpen(false)} className={`admin-sidebar-link${currentManagement?.key === item.key ? ' admin-sidebar-link-active' : ''}`} aria-current={currentManagement?.key === item.key ? 'page' : undefined}>{item.label}</NavLink>)}</nav></>
  return <>{isAdmin && <><aside className="admin-sidebar">{sidebar}</aside><Drawer placement="left" width={236} title="管理菜单" open={sidebarOpen} onClose={() => setSidebarOpen(false)}>{sidebar}</Drawer></>}<Layout.Header className={`app-header${isAdmin ? ' admin-header' : ''}`}>
    {isAdmin && <Button className="admin-sidebar-toggle" type="text" icon={<MenuOutlined />} aria-label="打开管理菜单" onClick={() => setSidebarOpen(true)} />}
    {!isAdmin && <NavLink to="/" className="brand-mark" aria-label="AI 生图首页"><span className="brand-symbol"><AppstoreOutlined /></span><span>AI 生图</span></NavLink>}
    <nav className="app-nav" aria-label="页面导航">
      {items.map(item => <NavLink key={item.key} to={item.key} className={`app-nav-link${selected(item.key) ? ' app-nav-link-active' : ''}`} aria-current={selected(item.key) ? 'page' : undefined}>{item.label}</NavLink>)}
    </nav>
    <div className="header-account">
      {isAdmin ? <span className="header-credit">不限使用</span> : <Button type="text" className="header-credit" onClick={() => navigate('/account/credits')}>{unavailable ? '积分待更新' : `积分 ${account?.available ?? '—'}`}</Button>}
      <Popover content={details} trigger={['hover', 'click']} placement="bottomRight"><Button type="text" className="header-username" icon={<UserOutlined />} aria-label={`${user?.username}的账户信息`}>{user?.username}<DownOutlined /></Button></Popover>
    </div>
  </Layout.Header></>
}
