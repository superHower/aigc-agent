import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, Space, Tag, Typography } from 'antd'
import { api, promptError } from '../api/client'
import { AppHeader } from '../components/AppHeader'

type Code = { id: string; asset_id: string; channel: string; instructions: string; active: number; created_at: string }
export function PaymentSettings() {
  const [items, setItems] = useState<Code[]>([])
  const [file, setFile] = useState<File>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [reason, setReason] = useState('')
  const [form] = Form.useForm()
  const load = () => api.get('/admin/payment-codes').then(r => setItems(r.data.items))
  useEffect(() => { load().catch(e => setError(promptError(e))) }, [])
  async function upload() {
    try {
      const values = await form.validateFields()
      if (!file) { setError('请选择收款码图片'); return }
      setBusy(true)
      const data = new FormData(); data.append('file', file)
      await api.post('/admin/payment-codes', data, { params: values }); await load(); setError('')
    } catch (e) { setError(promptError(e)) } finally { setBusy(false) }
  }
  async function toggle(code: Code) {
    if (!reason.trim()) { setError('请填写收款设置变更原因'); return }
    setBusy(true)
    try { await api.post(`/admin/payment-codes/${code.id}/status`, { active: !code.active, reason }); await load(); setError('') } catch (e) { setError(promptError(e)) } finally { setBusy(false) }
  }
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Space direction="vertical" className="page-stack" size="large">
    {error && <Alert type="error" message={error} />}
    <Card title="收款设置"><Alert type="info" message="上传产生新版本，默认不启用。启用后替换当前版本，旧订单仍保留原收款码、渠道和说明。无启用版本时禁止创建订单。" /><Form form={form} layout="vertical">
      <Form.Item name="channel" label="收款渠道标识（例如 wechat、alipay，同渠道交易号唯一）" rules={[{ required: true, whitespace: true, max: 100 }]}><Input maxLength={100} /></Form.Item>
      <Form.Item name="instructions" label="收款人及付款说明" rules={[{ required: true, whitespace: true, max: 1000 }]}><Input.TextArea maxLength={1000} /></Form.Item>
      <Form.Item label="收款码图片"><input type="file" accept="image/png,image/jpeg,image/webp" onChange={e => setFile(e.target.files?.[0])} /></Form.Item>
      <Button loading={busy} onClick={() => void upload()}>上传新版本</Button>
    </Form><Input.TextArea placeholder="启用 / 停用原因（必填）" value={reason} onChange={e => setReason(e.target.value)} maxLength={1000} /></Card>
    {items.map(c => <Card key={c.id} title={<Space>{c.channel}<Tag color={c.active ? 'green' : 'default'}>{c.active ? '当前启用' : '未启用'}</Tag></Space>} extra={<Button disabled={busy} onClick={() => void toggle(c)}>{c.active ? '停用' : '启用此版本'}</Button>}><Typography.Paragraph>{new Date(c.created_at).toLocaleString()} · {c.instructions}</Typography.Paragraph><Typography.Text type="secondary">版本 {c.id}</Typography.Text><div><img src={`/api/payment-assets/${c.asset_id}`} alt="收款码版本" style={{ width: 180, maxWidth: '100%' }} /></div></Card>)}
  </Space></main></div>
}
