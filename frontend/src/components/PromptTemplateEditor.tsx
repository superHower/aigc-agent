import { useEffect, useState } from 'react'
import { Form, Input, Modal, Select, message } from 'antd'
import { promptError, savePromptTemplate, type PromptCategory, type PromptTemplate, type PromptTemplateInput } from '../api/client'
import { useAuth } from './AuthProvider'

type Props = { open: boolean; template?: PromptTemplate; initialContent?: string; categories: PromptCategory[]; onClose: () => void; onSaved: () => void }

export function PromptTemplateEditor({ open, template, initialContent = '', categories, onClose, onSaved }: Props) {
  const [form] = Form.useForm<PromptTemplateInput>()
  const [saving, setSaving] = useState(false)
  const { user } = useAuth()
  useEffect(() => {
    if (open) { form.resetFields(); form.setFieldsValue(template ?? { name: '', content: initialContent, category_id: null, visibility: 'private' }) }
  }, [open, template, initialContent, form])
  const save = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setSaving(true)
    try {
      await savePromptTemplate({ ...values, name: values.name.trim(), category_id: values.category_id ?? null }, template?.id)
      message.success('模板已保存')
      onSaved()
      onClose()
    } catch (reason) { message.error(promptError(reason)) }
    finally { setSaving(false) }
  }
  return <Modal title={template ? '编辑提示词模板' : '新建提示词模板'} open={open} onCancel={onClose} onOk={() => void save()} confirmLoading={saving} cancelButtonProps={{ disabled: saving }} closable={!saving} maskClosable={!saving} keyboard={!saving} okText="保存" cancelText="取消" width={720}>
    <Form form={form} layout="vertical" disabled={saving}>
      {user?.role === 'admin' && <Form.Item name="visibility" label="可见范围"><Select options={[{ value: 'private', label: '私有' }, { value: 'public', label: '公共（所有用户可读）' }]} /></Form.Item>}
      <Form.Item name="name" label="模板名称" rules={[{ required: true, whitespace: true, message: '请输入模板名称' }, { max: 100 }]}><Input maxLength={100} placeholder="例如：白色摄影棚背景" /></Form.Item>
      <Form.Item name="category_id" label="分类"><Select allowClear placeholder="未分类" options={categories.map((item) => ({ value: item.id, label: item.name }))} /></Form.Item>
      <Form.Item name="content" label="提示词内容" rules={[{ required: true, whitespace: true, message: '请输入提示词内容' }, { max: 32000 }]}><Input.TextArea rows={9} maxLength={32000} showCount placeholder="输入下次可以直接使用的完整提示词" /></Form.Item>
    </Form>
  </Modal>
}
