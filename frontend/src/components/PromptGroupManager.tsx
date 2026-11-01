import { useEffect, useState } from 'react'
import { Alert, Button, Form, Input, List, Modal, Popconfirm, Select, Space, Typography, message } from 'antd'
import { deletePromptGroup, listPromptGroups, promptError, savePromptGroup, type PromptGroup, type PromptTemplate } from '../api/client'

export function PromptGroupManager({ open, templates, onClose }: { open: boolean; templates: PromptTemplate[]; onClose: () => void }) {
  const [groups, setGroups] = useState<PromptGroup[]>([])
  const [editing, setEditing] = useState<PromptGroup>()
  const [editorOpen, setEditorOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [form] = Form.useForm<{ name: string; template_ids: string[] }>()
  const selected: string[] = Form.useWatch('template_ids', form) ?? []
  const refresh = async () => {
    try { setGroups(await listPromptGroups()); setError('') }
    catch (reason) { setError(promptError(reason)) }
  }
  useEffect(() => { if (open) void refresh() }, [open])
  const edit = (group?: PromptGroup) => {
    setEditing(group)
    form.setFieldsValue({ name: group?.name ?? '', template_ids: group?.template_ids ?? [] })
    setEditorOpen(true)
  }
  const move = (index: number, offset: number) => {
    const next = [...selected]
    ;[next[index], next[index + offset]] = [next[index + offset], next[index]]
    form.setFieldValue('template_ids', next)
  }
  const save = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setBusy(true)
    try { await savePromptGroup(values, editing?.id); message.success('提示词组已保存'); setEditorOpen(false); await refresh() }
    catch (reason) { message.error(promptError(reason)) }
    finally { setBusy(false) }
  }
  return <>
    <Modal title="管理提示词组" open={open} onCancel={onClose} width={720} footer={<Button type="primary" onClick={() => edit()}>新建提示词组</Button>}>
      <Typography.Paragraph type="secondary">组与分类独立，同一模板可以加入多个组。工作台选择“一图多提示词”后，组内每条提示词各生成一张图。删除组会保留模板。</Typography.Paragraph>
      {error && <Alert type="error" message={error} action={<Button onClick={() => void refresh()}>重试</Button>} />}
      <List dataSource={groups} locale={{ emptyText: '暂无提示词组' }} renderItem={group => <List.Item actions={[
        <Button key="edit" onClick={() => edit(group)}>编辑</Button>,
        <Popconfirm key="delete" title="删除这个提示词组？模板将保留。" onConfirm={async () => { setBusy(true); try { await deletePromptGroup(group.id); await refresh() } catch (reason) { message.error(promptError(reason)) } finally { setBusy(false) } }}><Button danger disabled={busy}>删除</Button></Popconfirm>,
      ]}><List.Item.Meta title={group.name} description={`${group.template_ids.length} 条提示词`} /></List.Item>} />
    </Modal>
    <Modal title={editing ? '编辑提示词组' : '新建提示词组'} open={editorOpen} onCancel={() => setEditorOpen(false)} onOk={() => void save()} confirmLoading={busy} closable={!busy} maskClosable={!busy} keyboard={!busy} cancelButtonProps={{ disabled: busy }} width={720} okText="保存" cancelText="取消">
      <Form form={form} layout="vertical" disabled={busy}>
        <Form.Item name="name" label="组名" rules={[{ required: true, whitespace: true, message: '请输入组名' }, { max: 100 }]}><Input maxLength={100} placeholder="例如：商品场景套图" /></Form.Item>
        <Form.Item name="template_ids" label="组内提示词（最多 50 条）"><Select mode="multiple" maxCount={50} showSearch optionFilterProp="label" placeholder="选择提示词模板" options={templates.map(item => ({ value: item.id, label: item.name }))} /></Form.Item>
      </Form>
      <Typography.Paragraph type="secondary">下面的顺序用于生成和命名。删除模板后会自动从组中移除；空组可以保存，但不能提交生成。</Typography.Paragraph>
      <List dataSource={selected} renderItem={(id, index) => <List.Item actions={[<Space key="order"><Button disabled={busy || index === 0} onClick={() => move(index, -1)}>上移</Button><Button disabled={busy || index === selected.length - 1} onClick={() => move(index, 1)}>下移</Button></Space>]}><List.Item.Meta title={`${index + 1}. ${templates.find(item => item.id === id)?.name ?? '模板已不可访问，请移除'}`} description={<Typography.Paragraph ellipsis={{ rows: 2 }}>{templates.find(item => item.id === id)?.content}</Typography.Paragraph>} /></List.Item>} />
    </Modal>
  </>
}
