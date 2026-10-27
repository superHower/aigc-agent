import { useState } from 'react'
import { Alert, Button, Input, List, Modal, Select, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { categoryOptions, filterTemplates, usePromptLibrary } from '../hooks/usePromptLibrary'
import { PromptTemplateEditor } from './PromptTemplateEditor'

export function PromptTemplatePicker({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const library = usePromptLibrary()
  const [open, setOpen] = useState(false)
  const [editorOpen, setEditorOpen] = useState(false)
  const [category, setCategory] = useState('all')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<string>()
  const [confirmReplace, setConfirmReplace] = useState(false)
  const templates = filterTemplates(library.templates, category, query)
  const selected = templates.find((item) => item.id === selectedId)
  const apply = () => { if (selected) { onChange(selected.content); setOpen(false); setConfirmReplace(false) } }
  return <>
    <Space wrap className="option-row">
      <Button onClick={() => { setSelectedId(undefined); setConfirmReplace(false); setOpen(true); void library.refresh() }}>选择提示词模板</Button>
      <Button disabled={!value.trim()} onClick={() => { setEditorOpen(true); void library.refresh() }}>保存为模板</Button>
      <Link to="/prompts" target="_blank" rel="noopener noreferrer">管理模板</Link>
    </Space>
    <Modal title="选择提示词模板" open={open} onCancel={() => setOpen(false)} width={800} okText="填入提示词" cancelText="取消" okButtonProps={{ disabled: !selected || library.loading || !!library.error }} onOk={() => { if (value.trim() && selected?.content !== value) setConfirmReplace(true); else apply() }}>
      {library.error && <Alert type="error" message={library.error} action={<Button onClick={() => void library.refresh()}>重试</Button>} />}
      <Space wrap className="option-row">
        <Select aria-label="按分类选择模板" value={category} onChange={(next) => { setCategory(next); setSelectedId(undefined) }} style={{ width: 200 }} options={categoryOptions(library.categories)} />
        <Input aria-label="搜索模板" placeholder="搜索名称或内容" value={query} maxLength={200} allowClear onChange={(event) => { setQuery(event.target.value); setSelectedId(undefined) }} />
      </Space>
      <List loading={library.loading} dataSource={templates} pagination={{ pageSize: 5, hideOnSinglePage: true }} locale={{ emptyText: '暂无匹配模板，可前往管理模板创建' }} renderItem={(item) => <List.Item actions={[<Button key="select" type={selectedId === item.id ? 'primary' : 'default'} onClick={() => setSelectedId(item.id)}>{selectedId === item.id ? '已选择' : '选择'}</Button>]}><List.Item.Meta title={<>{item.name} <Tag>{library.categories.find((category) => category.id === item.category_id)?.name ?? '未分类'}</Tag></>} description={<Typography.Paragraph ellipsis={{ rows: 2 }}>{item.content}</Typography.Paragraph>} /></List.Item>} />
      {selected && <div className="prompt-preview"><Typography.Text strong>模板预览 · {selected.name}</Typography.Text><p>{selected.content}</p></div>}
    </Modal>
    <Modal title="替换当前提示词？" open={confirmReplace && open} onCancel={() => setConfirmReplace(false)} onOk={apply} okText="替换" cancelText="取消"><p>当前输入框已有内容，填入模板将替换这些内容。</p></Modal>
    <PromptTemplateEditor open={editorOpen} initialContent={value} categories={library.categories} onClose={() => setEditorOpen(false)} onSaved={() => void library.refresh()} />
  </>
}
