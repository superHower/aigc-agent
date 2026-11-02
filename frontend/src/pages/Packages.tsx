import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Space, Table, Typography, Upload } from 'antd'
import { api, promptError } from '../api/client'
import { AppHeader } from '../components/AppHeader'
import { issuance, type Plan } from './Credits'

export function Packages() {
  const [items, setItems] = useState<Plan[]>([])
  const [editing, setEditing] = useState<Plan>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [serviceUrl, setServiceUrl] = useState<string>()
  const [form] = Form.useForm()
  const [riskForm] = Form.useForm()
  useEffect(() => { api.get('/admin/risk-settings').then(r => riskForm.setFieldsValue(r.data)).catch(e => setError(promptError(e))) }, [])
  const load = () => api.get('/admin/membership-plans').then(r => setItems(r.data.items))
  useEffect(() => { Promise.all([load(), api.get('/recharge').then(r => setServiceUrl(r.data.customer_service_url))]).catch(e => setError(promptError(e))) }, [])
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Space direction="vertical" size="large" className="page-stack">
    {error && <Alert type="error" message={error} />}
    <Card title="防滥用风控（仅后台）"><Typography.Paragraph>0 表示关闭对应风控。单账号日消耗按 UTC 自然日统计积分，包含任务冻结预留；并发仍受系统及渠道容量约束。</Typography.Paragraph><Form form={riskForm} layout="inline" onFinish={async values => { setBusy(true); try { await api.put('/admin/risk-settings', values); setError('') } catch (e) { setError(promptError(e)) } finally { setBusy(false) } }}>{([['daily_limit', '单账号日消耗积分上限'], ['concurrency', '单账号并发上限'], ['retry_limit', '失败重试上限']] as const).map(([name, label]) => <Form.Item name={name} label={label} key={name} rules={[{ required: true }]}><InputNumber min={0} precision={0} /></Form.Item>)}<Button htmlType="submit" loading={busy}>保存风控设置</Button></Form></Card>
    <Card title="套餐配置"><Typography.Paragraph>周卡自开通起 7 天，月卡自开通起一个月，季卡自开通起 3 个月。赠送积分立即全额到账，会员期内有效，到期自动作废；额外充值 1 元=100 通用积分，永久有效。每日消耗、并发和失败重试限制属于后台风控设置，不作为用户权益限额展示。</Typography.Paragraph><Table rowKey="id" dataSource={items} pagination={false} scroll={{ x: 700 }} columns={[
      { title: '套餐', dataIndex: 'name' }, { title: '积分/张', dataIndex: 'cost' }, { title: '会员费（元）', dataIndex: 'price_cents', render: (v: number) => (v / 100).toFixed(2) }, { title: '赠送积分', dataIndex: 'credits' },{ title: '操作', render: (_, p: Plan) => <Button onClick={() => { setEditing(p); form.setFieldsValue(p) }}>编辑</Button> },
      { title: '有效期', render: (_, p: Plan) => p.duration_hours ? `${p.duration_hours} 小时` : ({ ordinary: '不限时', weekly: '7 天', monthly: '1 个月', quarterly: '3 个月' }[p.id] ?? '—') },
    ]} /></Card>
    <Card title="客服微信图片"><Typography.Paragraph>用户在充值中心添加此微信，由客服在用户管理中按邮箱充值积分、设置会员。</Typography.Paragraph>{serviceUrl && <img src={serviceUrl} alt="客服微信图片" style={{ width: 220, display: 'block', marginBottom: 16 }} />}<Upload accept="image/png,image/jpeg,image/webp" showUploadList={false} beforeUpload={file => { const data = new FormData(); data.append('file', file); setBusy(true); api.post('/admin/customer-service', data).then(r => { setServiceUrl(r.data.url); setError('') }).catch(e => setError(promptError(e))).finally(() => setBusy(false)); return false }}><Button loading={busy}>上传客服微信图片</Button></Upload></Card>
    <Modal title="编辑套餐" open={!!editing} onCancel={() => setEditing(undefined)} confirmLoading={busy} onOk={async () => { try { const values = await form.validateFields(); setBusy(true); await api.put(`/admin/membership-plans/${editing?.id}`, values); setEditing(undefined); setError(''); await load() } catch (e) { setError(promptError(e)) } finally { setBusy(false) } }}><Form form={form} layout="vertical">
      <Form.Item name="name" label="套餐名称" rules={[{ required: true }]}><Input /></Form.Item>
      {editing?.id === 'newcomer' && <><Alert type="info" message="限注册24小时内锁定资格的首单用户，终身限购一次；客服核实付款后在用户管理中开通，赠送积分到期作废。" /><Form.Item name="duration_hours" label="有效期（小时）" rules={[{ required: true }]}><InputNumber min={1} max={8760} precision={0} /></Form.Item></>}
      {([['cost', '单张消耗积分'], ['price_cents', '会员费（整数分）'], ['credits', '赠送积分']] as const).map(([name, label]) => <Form.Item key={name} name={name} label={label} rules={[{ required: true }]}><InputNumber min={name === 'cost' ? 1 : 0} precision={0} /></Form.Item>)}
    </Form></Modal>
  </Space></main></div>
}
