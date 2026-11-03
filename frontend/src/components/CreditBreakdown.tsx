import { Statistic, Tag } from 'antd'

export type CreditLot = { available: number; frozen: number; source: string; expires_at: string | null }

export function CreditBreakdown({ lots, loading = false }: { lots?: CreditLot[]; loading?: boolean }) {
  const permanent = (lots ?? []).filter(lot => !lot.expires_at).reduce((sum, lot) => sum + lot.available, 0)
  const membership = (lots ?? []).filter(lot => lot.source === 'membership').reduce((sum, lot) => sum + lot.available, 0)
  return <div className="credit-breakdown">
    <div className="credit-bucket credit-bucket-permanent">
      <Tag color="success">永不过期</Tag>
      <Statistic title="通用可用积分" value={loading ? '—' : permanent} />
      <p>额外充值积分永久保留，会员到期不受影响。</p>
      <small>含注册赠送等永久有效积分。</small>
    </div>
    <div className="credit-bucket credit-bucket-membership">
      <Tag color="warning">会员到期作废</Tag>
      <Statistic title="会员赠送可用积分" value={loading ? '—' : membership} />
      <p>仅会员有效期内可用，到期未用完自动作废。</p>
      <small>优先使用会员赠送积分，再扣通用积分。</small>
    </div>
  </div>
}
