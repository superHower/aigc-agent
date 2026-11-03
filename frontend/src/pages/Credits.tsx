import { useEffect, useState } from 'react'
import { Alert, Button, Card, Empty, Space, Statistic, Table, Tag, Typography } from 'antd'
import { api, promptError } from '../api/client'
import { AppHeader } from '../components/AppHeader'
import { BrandIcon } from '../components/Brand'
import { FrozenCreditsNotice } from '../components/FrozenCreditsNotice'
import { CreditBreakdown } from '../components/CreditBreakdown'
import { NewcomerOffer, type NewcomerPromotion } from '../components/NewcomerOffer'

type Entry = { id: string; event: string; available_delta: number; frozen_delta: number; created_at: string }
type Lot = { id: string; source: string; available: number; frozen: number; expires_at: string | null }
export type Plan = { id: string; name: string; cost: number; price_cents: number; credits: number; duration_days: number; newcomer_only: boolean; image_limit: number; total_limit: number; risk_limit: number }
export const issuance = (id: string) => ({ ordinary: '无', weekly: '立即到账，会员期内有效', monthly: '立即到账，会员期内有效', quarterly: '立即到账，会员期内有效' }[id] ?? '')
const labels: Record<string, string> = { grant: '发放', freeze: '冻结', settle: '成功扣费', release: '释放', expire: '到期', adjust: '管理员调整' }
const sources: Record<string, string> = { membership: '会员赠送积分', paid: '通用积分包', adjustment: '客服充值通用积分', trial: '注册 / 体验赠送积分' }
export function Credits() {
  const [balance, setBalance] = useState<{ available: number; frozen: number; lots: Lot[] } | null>(null)
  const [entries, setEntries] = useState<Entry[]>([])
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState('')
  const [recharge, setRecharge] = useState<{ plans: Plan[]; current_plan: Plan; expires_at: string | null; customer_service_url: string | null; newcomer_offer: NewcomerPromotion; newcomer_offers: NewcomerPromotion[] }>()
  useEffect(() => {
    Promise.all([api.get('/account/credits'), api.get('/account/credit-entries', { params: { offset, limit: 50 } }), api.get('/recharge')]).then(([account, ledger, center]) => {
      setBalance(account.data); setEntries(ledger.data.items); setRecharge(center.data); setError('')
    }).catch(reason => setError(promptError(reason)))
  }, [offset])
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Space direction="vertical" className="page-stack" size="large">
    {error && <Alert type="error" message={error} />}
    <FrozenCreditsNotice amount={balance?.frozen ?? 0} />
    {recharge?.newcomer_offers.map(offer => <NewcomerOffer key={offer.plan.id} offer={offer} serviceUrl={recharge?.customer_service_url} />)}
    <Card title={<span className="branded-card-title"><BrandIcon />充值中心</span>} loading={!balance}>
      <div className="recharge-layout">
        <div className="recharge-summary">
          <CreditBreakdown lots={balance?.lots} loading={!balance} />
          <Space size="large" wrap>
            <Statistic title="可用积分" value={balance?.available ?? 0} />
            <Statistic title="任务冻结" value={balance?.frozen ?? 0} />
            <Statistic title="当前套餐" value={recharge?.current_plan.name ?? '—'} />
            <Statistic title="每张消耗积分" value={recharge?.current_plan.cost ?? 25} />
          </Space>
          <div className="recharge-topup-callout"><Typography.Text>积分可以随时充值</Typography.Text><strong>1 元 = 100 积分</strong></div>
          <Typography.Paragraph>会员到期：{recharge?.expires_at ? new Date(recharge.expires_at).toLocaleString() : '未开通'}</Typography.Paragraph>
        </div>
        <div className="recharge-service"><Typography.Title level={4}>联系客服微信</Typography.Title><Typography.Paragraph type="secondary">充值、开通会员或有任何问题，请添加客服微信。</Typography.Paragraph>{recharge?.customer_service_url ? <img src={recharge.customer_service_url} alt="客服微信二维码" /> : <Alert type="info" message="客服微信图片暂未配置，请联系管理员。" />}</div>
      </div>
    </Card>
    <Card title="套餐介绍" loading={!recharge && !error}>
      <div className="plan-grid">
        {recharge?.plans.map(plan => <article key={plan.id} className={`plan-card${plan.id === recharge.current_plan.id ? ' plan-card-current' : ''}`}>
          <div className="plan-card-heading">
            <Typography.Title level={3}>{plan.name}</Typography.Title>
            {plan.id === recharge.current_plan.id && <Tag color="processing">当前套餐</Tag>}
          </div>
          <Statistic className="plan-price" title="会员费" prefix="¥" value={plan.price_cents / 100} precision={2} />
          <dl className="plan-details">
            <div><dt>每张消耗</dt><dd>{plan.cost.toLocaleString()} <span>积分 / 张</span></dd></div>
            <div><dt>赠送积分</dt><dd>{plan.credits.toLocaleString()} <span>积分</span></dd></div>
            <div className="plan-output"><dt>预计可做</dt><dd>{plan.cost ? Math.floor(plan.credits / plan.cost).toLocaleString() : 0} <span>张图</span></dd></div>
            <div><dt>套餐内不额外充值</dt><dd>{Math.floor(plan.credits / plan.cost) > 0 ? `约 ¥${(plan.price_cents / 100 / Math.floor(plan.credits / plan.cost)).toFixed(4)}` : '—'} <span>/ 张</span></dd></div>
          </dl>
        </article>)}
      </div>
      {recharge && !recharge.plans.length && <Empty description="暂无套餐" />}
      <Typography.Paragraph className="plan-refund-note" type="secondary">退款按未使用会员积分比例计算；已使用积分不退，赠送积分不折现，到期作废。通用积分包按未使用积分 ÷ 100 折算退款，请联系客服处理。</Typography.Paragraph>
    </Card>
    <Card title="积分来源"><Table rowKey="id" dataSource={balance?.lots} pagination={false} columns={[{ title: '来源', dataIndex: 'source', render: (v: string) => sources[v] ?? v }, { title: '可用', dataIndex: 'available' }, { title: '冻结', dataIndex: 'frozen' }, { title: '到期时间', dataIndex: 'expires_at', render: (v: string | null) => v ? new Date(v).toLocaleString() : '永久有效' }]} /></Card>
    <Card title="积分明细"><Table rowKey="id" dataSource={entries} pagination={false} columns={[{ title: '事件', dataIndex: 'event', render: (v: string) => labels[v] ?? v }, { title: '可用变动', dataIndex: 'available_delta' }, { title: '冻结变动', dataIndex: 'frozen_delta' }, { title: '时间', dataIndex: 'created_at', render: (v: string) => new Date(v).toLocaleString() }]} /><Space><Button disabled={!offset} onClick={() => setOffset(offset - 50)}>上一页</Button><Button disabled={entries.length < 50} onClick={() => setOffset(offset + 50)}>下一页</Button></Space></Card>
  </Space></main></div>
}
