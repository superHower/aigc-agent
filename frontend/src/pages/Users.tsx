import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Space, Table, Tag } from 'antd'
import { api, promptError } from '../api/client'
import { AppHeader } from '../components/AppHeader'
import { financialKey } from './Orders'
import { useAuth } from '../components/AuthProvider'

type User = { id: string; username: string; phone: string | null; role: string; disabled: number; membership_expires_at: string | null; available: number; frozen: number }
export function Users() {
  const [items, setItems] = useState<User[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<User>()
  const [adjust, setAdjust] = useState(false)
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm()
  const { user } = useAuth()
  const load = () => api.get('/admin/users', { params: { limit: 30, offset: (page - 1) * 30 } }).then(r => { setItems(r.data.items); setTotal(r.data.total) })
  useEffect(() => { load().catch(e => setError(promptError(e))) }, [page])
  function open(row: User, adjustment: boolean) { setSelected(row); setAdjust(adjustment); form.resetFields() }
  async function save() {
    try {
      const values = await form.validateFields(); setBusy(true)
      if (adjust) {
        const scope = `adjust:${user?.id}:${selected?.id}`
        await api.post(`/admin/users/${selected?.id}/credit-adjustments`, values, { headers: { 'Idempotency-Key': financialKey(scope, values) } }); sessionStorage.removeItem(scope)
      } else await api.post(`/admin/users/${selected?.id}/status`, { reason: values.reason, disabled: !selected?.disabled })
      setSelected(undefined); setError(''); await load()
    } catch (e) { setError(promptError(e)) } finally { setBusy(false) }
  }
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Card title="用户管理">{error && <Alert type="error" message={error} />}<Table rowKey="id" dataSource={items} scroll={{ x: 1000 }} pagination={{ current: page, pageSize: 30, total, onChange: setPage }} columns={[
    { title: '用户', dataIndex: 'username' }, { title: '手机号', dataIndex: 'phone' }, { title: '角色', dataIndex: 'role' }, { title: '状态', dataIndex: 'disabled', render: (v: number) => <Tag>{v ? '已禁用' : '启用'}</Tag> }, { title: '会员到期', dataIndex: 'membership_expires_at', render: (v: string | null) => v ? new Date(v).toLocaleString() : '未开通' }, { title: '可用积分', dataIndex: 'available' }, { title: '冻结', dataIndex: 'frozen' }, { title: '操作', render: (_, row: User) => <Space>{row.role !== 'admin' && <Button onClick={() => open(row, false)}>{row.disabled ? '启用' : '禁用'}</Button>}<Button onClick={() => open(row, true)}>积分调整</Button></Space> },
  ]} /></Card><Modal title={`${selected?.username ?? ''} · ${adjust ? '积分调整' : selected?.disabled ? '启用用户' : '禁用用户'}`} open={!!selected} onCancel={() => setSelected(undefined)} onOk={() => void save()} confirmLoading={busy}><Form form={form} layout="vertical">{adjust && <><Alert type="info" message="正数补偿，负数扣减可用积分。冻结积分不能扣减，不形成收款订单。" /><Form.Item name="amount" label="调整积分（非零整数）" rules={[{ required: true }, { validator: (_, v) => v === 0 ? Promise.reject(new Error('不能为零')) : Promise.resolve() }]}><InputNumber min={-10000000} max={10000000} precision={0} /></Form.Item></>}<Form.Item name="reason" label="原因（记录审计）" rules={[{ required: true, whitespace: true, max: 500 }]}><Input.TextArea maxLength={500} /></Form.Item></Form></Modal></main></div>
}
