import { useEffect, useState } from 'react'
import { Alert, Button, Card, Space, Statistic, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { financialKey } from './Orders'
import { useAuth } from '../components/AuthProvider'
import { api, promptError } from '../api/client'
import { AppHeader } from '../components/AppHeader'

export type Package = { id: string; name: string; kind: 'credits' | 'membership'; price_cents: number; credits: number; membership_days: number; status: 'draft' | 'active' | 'inactive'; sort_order: number }

export function Membership() {
  const [member, setMember] = useState<{ active: boolean; expires_at: string | null; concurrency: number }>()
  const [balance, setBalance] = useState<number>()
  const [packages, setPackages] = useState<Package[]>([])
  const [error, setError] = useState('')
  const [available, setAvailable] = useState(false)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const { user } = useAuth()
  useEffect(() => {
    Promise.all([api.get('/account/membership'), api.get('/account/credits'), api.get('/packages'), api.get('/payment-availability')]).then(([m, c, p, a]) => {
      setMember(m.data); setBalance(c.data.available); setPackages(p.data.items); setAvailable(a.data.available)
    }).catch(e => setError(promptError(e)))
  }, [])
  async function purchase(package_id: string) {
    setBusy(true)
    const payload = { package_id }, scope = `order-create:${user?.id}:${package_id}`
    try { const r = await api.post('/orders', payload, { headers: { 'Idempotency-Key': financialKey(scope, payload) } }); sessionStorage.removeItem(scope); navigate(`/orders/${r.data.id}`) } catch (e) { setError(promptError(e)) } finally { setBusy(false) }
  }
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Space direction="vertical" size="large" className="page-stack">
    {error && <Alert type="error" message={error} />}
    <Card title="我的会员" loading={!member}><Space size="large" wrap><Tag color={member?.active ? 'blue' : 'default'}>{member?.active ? '会员' : '普通用户'}</Tag><Statistic title="可用积分" value={balance ?? 0} /><Statistic title="跨任务并发张数" value={member?.concurrency ?? 1} /></Space><Typography.Paragraph>会员到期时间：{member?.expires_at ? new Date(member.expires_at).toLocaleString() : '尚未开通'}</Typography.Paragraph><Typography.Paragraph type="secondary">会员到期后恢复普通用户额度，已开始的请求继续执行。付费积分永久有效；积分包只增加积分，会员卡增加积分并叠加会员天数。</Typography.Paragraph></Card>
    <Alert type="info" message={available ? '人工充值：创建订单后按订单付款并提交信息，管理员核实实际到账后发放积分和会员。' : '尚未配置有效收款码，暂不能创建充值订单。'} />
    {!packages.length && <Card>暂无上架套餐</Card>}
    {packages.map(p => <Card key={p.id} title={p.name} extra={<Button disabled={!available || busy} onClick={() => void purchase(p.id)}>创建充值订单</Button>}><Space size="large" wrap><Statistic title="价格（元）" value={p.price_cents / 100} precision={2} /><Statistic title="到账积分" value={p.credits} /><Typography.Text>{p.kind === 'membership' ? `会员 ${p.membership_days} 天，从当前有效期末叠加；已到期则从到账时开始。` : '积分包，不改变会员到期日。'}</Typography.Text></Space></Card>)}
  </Space></main></div>
}
