import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, InputNumber, Layout, Modal, Popconfirm, Select, Space, Switch, Table, Tag, message } from 'antd'
import { AppHeader } from '../components/AppHeader'
import { deleteChannel, listChannels, promptError, resetChannel, saveChannel, type Channel, type ChannelInput } from '../api/client'

export function Channels() {
  const [items, setItems] = useState<Channel[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Channel>()
  const [form] = Form.useForm<ChannelInput>()
  const load = async () => {
    setLoading(true)
    try { setItems(await listChannels()) } catch (reason) { message.error(promptError(reason)) }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])
  const edit = (channel?: Channel) => {
    setEditing(channel)
    form.resetFields()
    form.setFieldsValue(channel ? { ...channel, channel_type: channel.channel_type ?? 'image', enabled: Boolean(channel.enabled), api_key: '' } : { channel_type: 'image', concurrency: 3, timeout: 30, enabled: true, remark: '', api_key: '' })
    setOpen(true)
  }
  const save = async () => {
    const payload = await form.validateFields()
    setSaving(true)
    try { await saveChannel(payload, editing?.id); setOpen(false); message.success('渠道已保存'); await load() }
    catch (reason) { message.error(promptError(reason)) }
    finally { setSaving(false) }
  }
  const act = async (action: () => Promise<void>) => {
    try { await action(); await load() } catch (reason) { message.error(promptError(reason)) }
  }
  return <Layout className="app-shell"><AppHeader /><Layout.Content className="workspace-content">
    <Card title="渠道管理" extra={<Space><Button loading={loading} onClick={() => void load()}>刷新</Button><Button type="primary" onClick={() => edit()}>新增渠道</Button></Space>}>
      <Alert type="info" showIcon message="批量任务自动平均分配到所有可用渠道。每个渠道单独控制并发，多个任务共享该渠道额度。渠道异常后立即暂停使用，检查配置或充值后点击恢复。配置修改从后续任务生效。" style={{ marginBottom: 16 }} />
      <Table<Channel> rowKey="id" loading={loading} dataSource={items} scroll={{ x: 1050 }} columns={[
        { title: '渠道名称', dataIndex: 'name' },
        { title: '模型', dataIndex: 'model' },
        { title: '类型', dataIndex: 'channel_type', render: (value: Channel['channel_type']) => <Tag color={value === 'video' ? 'purple' : 'green'}>{value === 'video' ? '视频' : '图片'}</Tag> },
        { title: 'API 地址', dataIndex: 'base_url', ellipsis: true },
        { title: 'API Key', render: (_, row) => row.has_api_key ? '••••••••' : '未设置' },
        { title: '并发', dataIndex: 'concurrency', width: 70 },
        { title: '超时', render: (_, row) => `${row.timeout} 秒`, width: 90 },
        { title: '备注', dataIndex: 'remark', ellipsis: true },
        { title: '状态', render: (_, row) => <Space direction="vertical"><Tag color={row.last_error ? 'error' : row.enabled ? 'success' : 'default'}>{row.last_error ? '异常' : row.enabled ? '可用' : '已停用'}</Tag>{row.last_error && <span>{row.last_error}</span>}</Space> },
        { title: '操作', width: 210, render: (_, row) => <Space wrap><Button size="small" onClick={() => edit(row)}>编辑</Button>{row.last_error && <Button size="small" onClick={() => void act(() => resetChannel(row.id))}>恢复</Button>}<Popconfirm title="删除此渠道？" onConfirm={() => act(() => deleteChannel(row.id))}><Button size="small" danger>删除</Button></Popconfirm></Space> },
      ]} />
    </Card>
    <Modal title={editing ? '编辑渠道' : '新增渠道'} open={open} onCancel={() => setOpen(false)} onOk={() => void save()} confirmLoading={saving} okText="保存" cancelText="取消">
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="渠道名称" rules={[{ required: true, whitespace: true }]}><Input maxLength={100} /></Form.Item>
        <Form.Item name="model" label="模型名称" rules={[{ required: true, whitespace: true }]}><Input placeholder="例如 gpt-image-1" maxLength={200} /></Form.Item>
        <Form.Item name="channel_type" label="类型" rules={[{ required: true }]}><Select onChange={value => { if (value === 'video') form.setFieldsValue({ model: 'minimax-h3', base_url: 'https://api.88api.ai/v1', timeout: 120 }) }} options={[{ value: 'image', label: '图片' }, { value: 'video', label: '视频（MiniMax H3）' }]} /></Form.Item>
        <Form.Item name="base_url" label="API 地址" rules={[{ required: true }, { type: 'url' }]}><Input placeholder="https://example.com/v1" /></Form.Item>
        <Form.Item name="api_key" label="API Key" extra={editing ? '留空保留原有密钥' : undefined} rules={[{ required: !editing, whitespace: true }]}><Input.Password autoComplete="new-password" /></Form.Item>
        <Space align="start"><Form.Item name="concurrency" label="并发任务数" rules={[{ required: true }]}><InputNumber min={1} max={20} precision={0} /></Form.Item><Form.Item name="timeout" label="请求超时（秒）" rules={[{ required: true }]}><InputNumber min={1} max={300} precision={0} /></Form.Item><Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item></Space>
        <Form.Item name="remark" label="备注"><Input.TextArea maxLength={2000} rows={3} /></Form.Item>
        <Form.Item name="estimated_cost_cents" label="每次请求估算成本（整数分，可留空）" extra="只作配置估算，包含失败和重试请求，不代表上游实际账单。"><InputNumber min={0} max={1000000} precision={0} /></Form.Item>
      </Form>
    </Modal>
  </Layout.Content></Layout>
}
