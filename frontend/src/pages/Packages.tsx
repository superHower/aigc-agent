import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Typography } from 'antd'
import { api, promptError } from '../api/client'
import { AppHeader } from '../components/AppHeader'
import type { Package } from './Membership'

export function Packages() {
  const [items, setItems] = useState<Package[]>([])
  const [editing, setEditing] = useState<Package | null>()
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const load = () => api.get('/admin/packages').then(r => setItems(r.data.items)).catch(e => setError(promptError(e)))
  useEffect(() => { void load() }, [])
  function edit(p: Package | null) {
    setEditing(p); form.setFieldsValue(p ?? { name: '', kind: 'credits', price_cents: 600, credits: 30, membership_days: 0, status: 'draft', sort_order: 0 })
  }
  async function save() {
    try {
      const values = await form.validateFields(); setSaving(true)
      if (editing) await api.put(`/admin/packages/${editing.id}`, values)
      else await api.post('/admin/packages', values)
      setEditing(undefined); setError(''); await load()
    } catch (e) { setError(promptError(e)) } finally { setSaving(false) }
  }
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Space direction="vertical" size="large" className="page-stack">
    {error && <Alert type="error" message={error} />}
    <Card title="套餐设置" extra={<Button type="primary" onClick={() => edit(null)}>新增套餐</Button>}><Typography.Paragraph type="secondary">建议套餐默认草稿，确认价格后再上架。下架保留历史记录；会员卡天数须大于零，积分包天数为零。人工充值还需启用有效收款码。</Typography.Paragraph><Table rowKey="id" dataSource={items} pagination={false} columns={[
      { title: '名称', dataIndex: 'name' }, { title: '价格（元）', dataIndex: 'price_cents', render: (v: number) => (v / 100).toFixed(2) }, { title: '积分', dataIndex: 'credits' }, { title: '会员天数', dataIndex: 'membership_days' }, { title: '状态', dataIndex: 'status', render: (v: string) => ({ draft: '草稿', active: '上架', inactive: '下架' }[v]) }, { title: '排序', dataIndex: 'sort_order' }, { title: '操作', render: (_, p: Package) => <Button onClick={() => edit(p)}>编辑</Button> },
    ]} /></Card>
    <Modal title={editing ? '编辑套餐' : '新增套餐'} open={editing !== undefined} onCancel={() => setEditing(undefined)} onOk={() => void save()} confirmLoading={saving} destroyOnClose><Form form={form} layout="vertical">
      <Form.Item name="name" label="名称" rules={[{ required: true, whitespace: true, max: 100 }]}><Input maxLength={100} /></Form.Item>
      <Form.Item name="kind" label="类型"><Select options={[{ value: 'credits', label: '积分包' }, { value: 'membership', label: '会员卡' }]} /></Form.Item>
      <Form.Item name="price_cents" label="价格（整数分）" rules={[{ required: true }]}><InputNumber min={1} max={100000000} precision={0} /></Form.Item>
      <Form.Item name="credits" label="积分数" rules={[{ required: true }]}><InputNumber min={1} max={10000000} precision={0} /></Form.Item>
      <Form.Item name="membership_days" label="会员天数" rules={[{ required: true }]}><InputNumber min={0} max={3650} precision={0} /></Form.Item>
      <Form.Item name="status" label="状态"><Select options={[{ value: 'draft', label: '草稿' }, { value: 'active', label: '上架' }, { value: 'inactive', label: '下架' }]} /></Form.Item>
      <Form.Item name="sort_order" label="排序" rules={[{ required: true }]}><InputNumber min={0} max={100000} precision={0} /></Form.Item>
    </Form></Modal>
  </Space></main></div>
}
