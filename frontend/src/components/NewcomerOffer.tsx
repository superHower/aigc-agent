import { useEffect, useState } from 'react'
import { Alert, Button, Card, Modal, Statistic, Typography } from 'antd'
import { api, promptError } from '../api/client'

export type NewcomerPromotion = {
  eligible: boolean; deadline: string; server_now: string; reserved: boolean; original_price_cents: number
  plan: { id: string; name: string; price_cents: number; credits: number; cost: number; duration_hours: number }
}

export function NewcomerOffer({ offer, serviceUrl }: { offer?: NewcomerPromotion; serviceUrl?: string | null }) {
  const [open, setOpen] = useState(false)
  const [contact, setContact] = useState(false)
  const [remaining, setRemaining] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!offer?.eligible) return
    const deadline = performance.now() + new Date(offer.deadline).getTime() - new Date(offer.server_now).getTime()
    const tick = () => setRemaining(Math.max(0, Math.ceil((deadline - performance.now()) / 1000)))
    tick(); setOpen(true)
    const timer = window.setInterval(tick, 1000)
    return () => window.clearInterval(timer)
  }, [offer?.deadline, offer?.eligible])
  if (!offer?.eligible || remaining <= 0) return null
  const plan = offer.plan
  const countdown = [Math.floor(remaining / 3600), Math.floor(remaining % 3600 / 60), remaining % 60].map(n => String(n).padStart(2, '0')).join(':')
  async function purchase() {
    setBusy(true); setError('')
    try { await api.post('/recharge/newcomer/reserve', null, { params: { plan_id: plan.id } }); setContact(true) }
    catch (e) { setError(promptError(e)) }
    finally { setBusy(false) }
  }
  const content = <>
    <Typography.Title level={3}>{plan.name} · ￥{plan.price_cents / 100}</Typography.Title>
    <Typography.Paragraph>立即到账 {plan.credits.toLocaleString()} 积分（可做 {Math.floor(plan.credits / plan.cost)} 张图），{plan.duration_hours / 24} 天内享受 {plan.cost} 积分/张的超低折扣！</Typography.Paragraph>
    <Statistic title="优惠倒计时，结束后恢复原价" value={countdown} />
    <Typography.Paragraph type="secondary">限新用户首单，终身限购 1 次。付款经客服核实开通后，积分立即到账，有效期 {plan.duration_hours} 小时，未使用的赠送积分到期作废。</Typography.Paragraph>
    {error && <Alert type="error" message={error} />}
    <Button type="primary" size="large" loading={busy} onClick={() => void purchase()}>立即抢购</Button>
    {contact && <div className="newcomer-contact">
      <Alert type="success" message="资格已锁定，请联系微信客服付款开通" />
      <Typography.Paragraph>请向客服提供账号邮箱及“{plan.name}”，支付 ￥{plan.price_cents / 100}，核实到账后开通。</Typography.Paragraph>
      {serviceUrl ? <img src={serviceUrl} alt="客服微信二维码" style={{ width: 220, maxWidth: '100%' }} /> : <Alert type="info" message="客服微信暂未配置，请联系管理员开通" />}
    </div>}
  </>
  return <>
    <Card title="新人专享特权" className="newcomer-offer" extra={<Button onClick={() => setOpen(true)}>查看优惠</Button>}>{content}</Card>
    <Modal title="新人专享特权" className="newcomer-modal" open={open} onCancel={() => setOpen(false)} footer={null}>{content}</Modal>
  </>
}
