import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Alert, Button, Card, Form, Input, InputNumber, Select, Space, Table, Tag, Typography } from 'antd'
import { api, idempotencyKey, promptError } from '../api/client'
import { AppHeader } from '../components/AppHeader'
import { useAuth } from '../components/AuthProvider'

export const orderLabels: Record<string, string> = { pending: '待付款', review: '待审核', needs_info: '需补充信息', cancelled: '已取消', credited: '已入账' }
type Order = { id: string; user_id: string; package_name: string; price_cents: number; credits: number; membership_days: number; status: string; created_at: string; credited_at: string | null }
type Detail = Order & { payment_code: { asset_id: string; channel: string; instructions: string }; evidence: { id: string; declared_transaction: string; paid_at: string; asset_id: string | null; note: string; created_at: string }[]; reviews: { id: string; action: string; reason: string; created_at: string }[]; receipt: { channel: string; verified_transaction: string; amount_cents: number } | null }

// Preserve keys after ambiguous network failures and across reloads.
export function financialKey(scope: string, payload: unknown) {
  const fingerprint = JSON.stringify(payload)
  const stored = sessionStorage.getItem(scope)
  if (stored) { const old = JSON.parse(stored); if (old.payload === fingerprint) return old.key as string }
  const key = idempotencyKey(); sessionStorage.setItem(scope, JSON.stringify({ payload: fingerprint, key })); return key
}

export function Orders({ admin = false }: { admin?: boolean }) {
  const [items, setItems] = useState<Order[]>([])
  const [status, setStatus] = useState<string | undefined>(admin ? 'review' : undefined)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState('')
  useEffect(() => { api.get(admin ? '/admin/orders' : '/orders', { params: { status, limit: 30, offset: (page - 1) * 30 } }).then(r => { setItems(r.data.items); setTotal(r.data.total); setError('') }).catch(e => setError(promptError(e))) }, [admin, status, page])
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Space direction="vertical" className="page-stack" size="large">
    {error && <Alert type="error" message={error} />}
    <Card title={admin ? '充值审核' : '我的订单'} extra={<Link to="/account/membership">查看套餐</Link>}><Select allowClear placeholder="全部状态" value={status} style={{ width: 180, marginBottom: 16 }} onChange={v => { setStatus(v); setPage(1) }} options={Object.entries(orderLabels).map(([value, label]) => ({ value, label }))} /><Table rowKey="id" dataSource={items} pagination={{ current: page, pageSize: 30, total, onChange: setPage }} columns={[
      { title: '套餐', dataIndex: 'package_name' }, { title: '金额（元）', dataIndex: 'price_cents', render: (v: number) => (v / 100).toFixed(2) }, { title: '积分', dataIndex: 'credits' }, { title: '状态', dataIndex: 'status', render: (v: string) => <Tag>{orderLabels[v]}</Tag> }, { title: '创建时间', dataIndex: 'created_at', render: (v: string) => new Date(v).toLocaleString() }, { title: '操作', render: (_, o: Order) => <Link to={`/orders/${o.id}`}>查看</Link> },
    ]} /></Card>
  </Space></main></div>
}

export function OrderDetail() {
  const { id } = useParams()
  const { user } = useAuth()
  const [order, setOrder] = useState<Detail>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [file, setFile] = useState<File>()
  const [assetId, setAssetId] = useState<string>()
  const [evidenceForm] = Form.useForm()
  const [reviewForm] = Form.useForm()
  const actionLock = useRef(false)
  const navigate = useNavigate()
  const load = () => api.get(`/orders/${id}`).then(r => { setOrder(r.data); reviewForm.setFieldsValue({ channel: r.data.payment_code.channel, amount_cents: r.data.price_cents }) })
  useEffect(() => { load().catch(e => setError(promptError(e))) }, [id])
  async function action(endpoint: string, payload: unknown) {
    if (actionLock.current) return
    actionLock.current = true; setBusy(true)
    try {
      const scope = `finance:${user?.id}:${id}:${endpoint}`
      await api.post(endpoint, payload, { headers: { 'Idempotency-Key': financialKey(scope, payload) } })
      sessionStorage.removeItem(scope); setError(''); await load()
    } catch (e) { setError(promptError(e)) } finally { actionLock.current = false; setBusy(false) }
  }
  async function submitEvidence() {
    try {
      const values = await evidenceForm.validateFields()
      let asset = assetId
      if (file && !asset) {
        setBusy(true)
        const data = new FormData(); data.append('file', file)
        asset = (await api.post('/order-evidence-assets', data)).data.id; setAssetId(asset)
      }
      await action(`/orders/${id}/evidence`, { declared_transaction: values.declared_transaction, paid_at: new Date(values.paid_at).toISOString(), note: values.note ?? '', asset_id: asset ?? null })
    } catch (e) { setError(promptError(e)); setBusy(false) }
  }
  async function verify(supplement: boolean) {
    try { const values = await reviewForm.validateFields(); await action(`/admin/orders/${id}/${supplement ? 'supplement-verify' : 'verify'}`, values) } catch (e) { setError(promptError(e)) }
  }
  const own = user?.id === order?.user_id
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Space direction="vertical" className="page-stack" size="large">
    {error && <Alert type="error" message={error} />}
    <Card title="订单详情" loading={!order} extra={<Button onClick={() => navigate(user?.role === 'admin' ? '/admin/orders' : '/orders')}>返回列表</Button>}>
      {order && <><Typography.Paragraph copyable>{order.id}</Typography.Paragraph><Space wrap><Typography.Text strong>{order.package_name}</Typography.Text><Tag>{orderLabels[order.status]}</Tag><Typography.Text>¥{(order.price_cents / 100).toFixed(2)} / {order.credits} 积分 / 会员 {order.membership_days} 天</Typography.Text></Space>
      <Typography.Paragraph>创建：{new Date(order.created_at).toLocaleString()}；入账：{order.credited_at ? new Date(order.credited_at).toLocaleString() : '尚未入账'}</Typography.Paragraph>
      {order.status !== 'credited' && <><Alert type="info" message="请按此订单金额付款，提交真实交易号和付款时间。截图仅作辅助，管理员核实实际收款后才会到账。请勿重复付款。" /><Typography.Paragraph>收款渠道：{order.payment_code.channel}；{order.payment_code.instructions}</Typography.Paragraph><img alt="此订单使用的收款码" src={`/api/payment-assets/${order.payment_code.asset_id}`} style={{ maxWidth: 280, width: '100%' }} />{order.status === 'cancelled' && <Alert type="warning" message="订单已取消，请勿继续付款。如已实际付款，请联系管理员补录核实。" />}</>}
      {order.receipt && <Alert type="success" message={`已核实 ${order.receipt.channel} 交易号 ${order.receipt.verified_transaction}，到账 ${order.credits} 积分${order.membership_days ? `，会员延长 ${order.membership_days} 天` : ''}。`} />}
      {own && order.status === 'pending' && <Button disabled={busy} onClick={() => void action(`/orders/${id}/cancel`, {})}>取消未付款订单</Button>}</>}
    </Card>
    {own && order && ['pending', 'review', 'needs_info'].includes(order.status) && <Card title="提交 / 补充付款信息"><Form form={evidenceForm} layout="vertical">
      <Form.Item name="declared_transaction" label="用户申报交易号（以管理员核实为准）" rules={[{ required: true, whitespace: true, max: 200 }]}><Input maxLength={200} /></Form.Item>
      <Form.Item name="paid_at" label="付款时间（本地时间）" rules={[{ required: true }]}><Input type="datetime-local" /></Form.Item>
      <Form.Item label="付款截图（可选，PNG/JPEG/WebP，最大 10 MB）"><input type="file" accept="image/png,image/jpeg,image/webp" onChange={e => { setFile(e.target.files?.[0]); setAssetId(undefined) }} /></Form.Item>
      <Form.Item name="note" label="补充说明"><Input.TextArea maxLength={1000} /></Form.Item>
      <Button type="primary" loading={busy} onClick={() => void submitEvidence()}>提交人工审核</Button>
    </Form></Card>}
    {user?.role === 'admin' && order && ['review', 'cancelled'].includes(order.status) && <Card title={order.status === 'cancelled' ? '取消后付款补录核实' : '核实实际收款'}><Alert type="warning" message="请在收款账户核对真实到账，勿仅凭截图入账。交易号与用户申报分开保存；金额必须与订单一致。" /><Form form={reviewForm} layout="vertical">
      <Form.Item name="channel" label="核实收款渠道" rules={[{ required: true, whitespace: true }]}><Input readOnly /></Form.Item>
      <Form.Item name="verified_transaction" label="管理员核实的交易号" rules={[{ required: true, whitespace: true, max: 200 }]}><Input maxLength={200} /></Form.Item>
      <Form.Item name="amount_cents" label="核实金额（整数分）" rules={[{ required: true }]}><InputNumber min={1} precision={0} /></Form.Item>
      <Form.Item name="reason" label="核实说明 / 补充材料原因" rules={[{ required: true, whitespace: true, max: 1000 }]}><Input.TextArea maxLength={1000} /></Form.Item>
      <Space><Button type="primary" loading={busy} onClick={() => void verify(order.status === 'cancelled')}>{order.status === 'cancelled' ? '确认实际收款并补录入账' : '确认实际收款并入账'}</Button>{order.status === 'review' && <Button disabled={busy} onClick={async () => { try { const reason = await reviewForm.validateFields(['reason']); await action(`/admin/orders/${id}/needs-info`, reason) } catch (e) { setError(promptError(e)) } }}>要求补充材料</Button>}</Space>
    </Form></Card>}
    <Card title="付款信息历史（用户申报）">{order?.evidence.map(e => <div key={e.id}><Typography.Paragraph>{new Date(e.created_at).toLocaleString()}：交易号 {e.declared_transaction}；付款时间 {new Date(e.paid_at).toLocaleString()}；{e.note}</Typography.Paragraph>{e.asset_id && <a href={`/api/payment-assets/${e.asset_id}`} target="_blank" rel="noreferrer">查看私有付款截图</a>}</div>)}</Card>
    <Card title="处理记录">{order?.reviews.map(r => <Typography.Paragraph key={r.id}>{new Date(r.created_at).toLocaleString()} · {({ create: '创建订单', evidence: '提交材料', cancel: '取消', needs_info: '需补充信息', verify: '核实入账', supplement_verify: '取消后补录入账' } as Record<string, string>)[r.action] ?? r.action}：{r.reason}</Typography.Paragraph>)}</Card>
  </Space></main></div>
}
