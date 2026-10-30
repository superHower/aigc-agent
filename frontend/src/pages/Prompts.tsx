import { useState } from 'react'
import { Alert, Button, Card, Form, Input, Layout, List, Modal, Popconfirm, Select, Space, Table, Tag, Typography, message } from 'antd'
import { deletePromptCategory, deletePromptTemplate, promptError, savePromptCategory, type PromptCategory, type PromptTemplate } from '../api/client'
import { AppHeader } from '../components/AppHeader'
import { PromptTemplateEditor } from '../components/PromptTemplateEditor'
import { categoryOptions, filterTemplates, usePromptLibrary } from '../hooks/usePromptLibrary'
import { useAuth } from '../components/AuthProvider'

export function Prompts() {
  const library = usePromptLibrary()
  const { user } = useAuth()
  const [category, setCategory] = useState('all')
  const [query, setQuery] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<PromptTemplate>()
  const [preview, setPreview] = useState<PromptTemplate>()
  const [categoriesOpen, setCategoriesOpen] = useState(false)
  const [categoryEditorOpen, setCategoryEditorOpen] = useState(false)
  const [editingCategory, setEditingCategory] = useState<PromptCategory>()
  const [busy, setBusy] = useState(false)
  const [categoryForm] = Form.useForm<{ name: string; visibility: string }>()
  const mutate = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true)
    try { await action(); message.success(success); await library.refresh(); return true }
    catch (reason) { message.error(promptError(reason)); return false }
    finally { setBusy(false) }
  }
  const editCategory = (item?: PromptCategory) => {
    setEditingCategory(item)
    categoryForm.setFieldsValue({ name: item?.name ?? '', visibility: item?.visibility ?? 'private' })
    setCategoryEditorOpen(true)
  }
  const saveCategory = async () => {
    const values = await categoryForm.validateFields().catch(() => null)
    if (values && await mutate(() => savePromptCategory(values.name.trim(), editingCategory?.id, values.visibility), '分类已保存')) setCategoryEditorOpen(false)
  }
  return <Layout className="app-shell"><AppHeader /><Layout.Content className="workspace-content">
    <Card className="panel-card" title="提示词管理" extra={<Space wrap><Button onClick={() => setCategoriesOpen(true)}>管理分类</Button><Button type="primary" onClick={() => { setEditing(undefined); setEditorOpen(true) }}>新建模板</Button></Space>}>
      <Typography.Paragraph type="secondary">保存常用提示词，在工作台按分类选择模板后直接填入，也可继续修改。</Typography.Paragraph>
      {library.error && <Alert type="error" message={library.error} action={<Button onClick={() => void library.refresh()}>重试</Button>} />}
      <Space wrap className="option-row">
        <Select aria-label="模板分类" style={{ width: 220 }} value={category} onChange={setCategory} options={categoryOptions(library.categories)} />
        <Input aria-label="搜索提示词模板" style={{ width: 280 }} placeholder="搜索模板名称或内容" maxLength={200} allowClear value={query} onChange={(event) => setQuery(event.target.value)} />
        <Button onClick={() => void library.refresh()} loading={library.loading}>刷新</Button>
      </Space>
      <Table<PromptTemplate> rowKey="id" loading={library.loading} dataSource={filterTemplates(library.templates, category, query)} scroll={{ x: 760 }} pagination={{ pageSize: 10, showTotal: (total) => `共 ${total} 个模板` }} locale={{ emptyText: '暂无模板，请新建模板或调整筛选条件' }} columns={[
        { title: '模板名称', dataIndex: 'name', width: 180, render: (name, item) => <Button type="link" className="prompt-name" onClick={() => setPreview(item)}>{name}</Button> },
        { title: '分类', width: 140, render: (_, item) => <Tag>{library.categories.find((category) => category.id === item.category_id)?.name ?? '未分类'}</Tag> },
        { title: '范围', dataIndex: 'visibility', render: (v: string) => v === 'public' ? '公共' : '私有' },
        { title: '提示词内容', dataIndex: 'content', render: (content: string) => <Typography.Paragraph ellipsis={{ rows: 2 }} style={{ margin: 0 }}>{content}</Typography.Paragraph> },
        { title: '操作', width: 190, render: (_, item) => <Space><Button size="small" onClick={() => setPreview(item)}>查看</Button><Button size="small" onClick={() => { setEditing(item); setEditorOpen(true) }}>编辑</Button><Popconfirm title="删除这个提示词模板？" okText="删除" cancelText="取消" okButtonProps={{ loading: busy }} onConfirm={() => mutate(() => deletePromptTemplate(item.id), '模板已删除')}><Button size="small" danger disabled={busy}>删除</Button></Popconfirm></Space> },
      ]} />
    </Card>
    <PromptTemplateEditor open={editorOpen} template={editing} categories={library.categories} onClose={() => setEditorOpen(false)} onSaved={() => void library.refresh()} />
    <Modal title={preview?.name} open={!!preview} onCancel={() => setPreview(undefined)} footer={<Button onClick={() => setPreview(undefined)}>关闭</Button>} width={720}><div className="prompt-preview">{preview?.content}</div></Modal>
    <Modal title="管理分类" open={categoriesOpen} onCancel={() => setCategoriesOpen(false)} footer={<Button type="primary" onClick={() => editCategory()}>新增分类</Button>}>
      <Typography.Paragraph type="secondary">删除分类后，其中的模板会保留并移到“未分类”。</Typography.Paragraph>
      <List dataSource={library.categories} locale={{ emptyText: '暂无分类' }} renderItem={(item) => <List.Item actions={[<Button key="edit" size="small" onClick={() => editCategory(item)}>重命名</Button>, <Popconfirm key="delete" title="删除分类并将模板移至未分类？" okText="删除" cancelText="取消" okButtonProps={{ loading: busy }} onConfirm={async () => { if (await mutate(() => deletePromptCategory(item.id), '分类已删除') && category === item.id) setCategory('all') }}><Button danger size="small" disabled={busy}>删除</Button></Popconfirm>]}><Typography.Text>{item.name}</Typography.Text></List.Item>} />
    </Modal>
    <Modal title={editingCategory ? '重命名分类' : '新增分类'} open={categoryEditorOpen} onCancel={() => setCategoryEditorOpen(false)} onOk={() => void saveCategory()} confirmLoading={busy} cancelButtonProps={{ disabled: busy }} closable={!busy} maskClosable={!busy} keyboard={!busy} okText="保存" cancelText="取消">
      <Form form={categoryForm} layout="vertical" disabled={busy}><Form.Item name="name" label="分类名称" rules={[{ required: true, whitespace: true, message: '请输入分类名称' }, { max: 100 }]}><Input maxLength={100} placeholder="例如：背景替换、商品精修" /></Form.Item>{user?.role === 'admin' && <Form.Item name="visibility" label="可见范围"><Select options={[{ value: 'private', label: '私有' }, { value: 'public', label: '公共' }]} /></Form.Item>}</Form>
    </Modal>
  </Layout.Content></Layout>
}
