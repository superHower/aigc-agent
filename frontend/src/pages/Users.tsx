import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tag } from 'antd'
import { api, promptError } from '../api/client'
import { AppHeader } from '../components/AppHeader'
import { financialKey } from './Orders'
import { useAuth } from '../components/AuthProvider'

type User = { id: string; username: string; email: string | null; role: string; disabled: number; membership_expires_at: string | null; available: number; frozen: number }
type Action = 'credit' | 'membership' | 'email' | 'status' | 'password'
const titles = { credit: '充值积分', membership: '设置会员', email: '绑定邮箱', status: '更改用户状态', password: '重置密码' }
export function Users() {
  const [items, setItems] = useState<User[]>([])
  const [plans, setPlans] = useState<{ id: string; name: string; newcomer_only: boolean }[]>([])
  useEffect(() => { api.get('/admin/membership-plans').then(r => setPlans(r.data.items)).catch(e => setError(promptError(e))) }, [])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<User>()
  const [action, setAction] = useState<Action>('credit')
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm()
  const { user } = useAuth()
  const load = () => api.get('/admin/users', { params: { limit: 30, offset: (page - 1) * 30, email: query } }).then(r => { setItems(r.data.items); setTotal(r.data.total) })
  useEffect(() => { load().catch(e => setError(promptError(e))) }, [page, query])
  function open(row: User, mode: Action) { setSelected(row); setAction(mode); form.resetFields(); if (mode === 'email') form.setFieldValue('email', row.email) }
  async function save() {
    try {
      const values = await form.validateFields(); setBusy(true)
      const base = `/admin/users/${selected?.id}`
      if (action === 'email') await api.put(base + '/email', values)
      else if (action === 'status') await api.post(base + '/status', { ...values, disabled: !selected?.disabled })
      else if (action === 'password') await api.post(base + '/reset-password', values)
      else {
        const scope = `${action}:${user?.id}:${selected?.id}`
        await api.post(base + (action === 'credit' ? '/credit-adjustments' : '/membership'), values, { headers: { 'Idempotency-Key': financialKey(scope, values) } }); sessionStorage.removeItem(scope)
      }
      setSelected(undefined); setError(''); await load()
    } catch (e) { setError(promptError(e)) } finally { setBusy(false) }
  }
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Card title="用户管理" extra={<Input.Search placeholder="按完整邮箱查找" allowClear onSearch={value => { setQuery(value.trim()); setPage(1) }} />}>
    {error && <Alert type="error" message={error} />}<Table rowKey="id" dataSource={items} scroll={{ x: 1200 }} pagination={{ current: page, pageSize: 30, total, onChange: setPage }} columns={[
      { title: '用户', dataIndex: 'username' }, { title: '邮箱', dataIndex: 'email' }, { title: '角色', dataIndex: 'role' }, { title: '状态', dataIndex: 'disabled', render: (v: number) => <Tag>{v ? '已禁用' : '启用'}</Tag> },
      { title: '会员剩余', dataIndex: 'membership_expires_at', render: (v: string | null) => v && new Date(v).getTime() > Date.now() ? `${Math.ceil((new Date(v).getTime() - Date.now()) / 86400000)} 天（${new Date(v).toLocaleString()} 到期）` : '普通用户' },
      { title: '可用积分', dataIndex: 'available' }, { title: '冻结', dataIndex: 'frozen' }, { title: '操作', render: (_, row: User) => <Space wrap><Button onClick={() => open(row, 'credit')}>充值积分</Button><Button onClick={() => open(row, 'membership')}>设置会员</Button><Button onClick={() => open(row, 'email')}>绑定邮箱</Button>{row.role !== 'admin' && <><Button onClick={() => open(row, 'status')}>{row.disabled ? '启用' : '禁用'}</Button><Button onClick={() => open(row, 'password')}>重置密码</Button></>}</Space> },
    ]} /></Card><Modal title={`${selected?.email ?? selected?.username ?? ''} · ${titles[action]}`} open={!!selected} onCancel={() => setSelected(undefined)} onOk={() => void save()} confirmLoading={busy}><Form form={form} layout="vertical">
      {action === 'credit' && <><Alert type="info" message="充值为永久通用积分，1 元=100 积分。请确认上方邮箱。" /><Form.Item name="amount" label="充值积分" rules={[{ required: true }]}><InputNumber min={1} max={10000000} precision={0} /></Form.Item></>}
      {action === 'membership' && <><Alert type="warning" message="立即替换当前会员，旧会员未用赠送积分作废。通用积分保留。新人体验卡请先核实付款，系统将校验锁定资格、首单及终身限购规则。" /><Form.Item name="plan_id" label="套餐" rules={[{ required: true }]}><Select options={plans.map(p => ({ value: p.id, label: p.name + (p.newcomer_only ? ' (new)' : '') }))} /></Form.Item></>}
      {action === 'email' && <Form.Item name="email" label="登录邮箱（修改后该用户需重新登录）" rules={[{ required: true }, { type: 'email' }]}><Input maxLength={254} /></Form.Item>}
      {action === 'password' && <Form.Item name="password" label="新密码" rules={[{ required: true, min: 8, max: 64 }]}><Input.Password autoComplete="new-password" /></Form.Item>}
      {(action === 'status' || action === 'password') && <Form.Item name="reason" label="原因" rules={[{ required: true, whitespace: true, max: 500 }]}><Input.TextArea /></Form.Item>}
    </Form></Modal></main></div>
}
