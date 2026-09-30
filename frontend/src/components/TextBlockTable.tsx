import { Input, Switch, Table } from 'antd'
import type { TableColumnsType } from 'antd'
import type { TextBlock } from '../api/client'

type Props = {
  blocks: TextBlock[]
  replacements: Record<string, { replace: string; enabled: boolean }>
  activeId: string | null
  onHover: (id: string | null) => void
  onChange: (id: string, value: { replace: string; enabled: boolean }) => void
}

export function TextBlockTable({ blocks, replacements, activeId, onHover, onChange }: Props) {
  const columns: TableColumnsType<TextBlock> = [
    { title: 'ID', dataIndex: 'id', width: 58, render: (value: string) => <strong>{value}</strong> },
    { title: '位置', dataIndex: 'position', width: 100 },
    { title: '原文', dataIndex: 'original', width: 150, ellipsis: true },
    {
      title: '替换为',
      key: 'replace',
      render: (_, block) => (
        <Input
          size="small"
          placeholder="不修改"
          value={replacements[block.id]?.replace ?? ''}
          onChange={(event) => onChange(block.id, { replace: event.target.value, enabled: replacements[block.id]?.enabled ?? true })}
        />
      ),
    },
    {
      title: '启用',
      key: 'enabled',
      width: 64,
      render: (_, block) => (
        <Switch
          size="small"
          checked={replacements[block.id]?.enabled ?? true}
          onChange={(enabled) => onChange(block.id, { replace: replacements[block.id]?.replace ?? '', enabled })}
        />
      ),
    },
  ]
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={blocks}
      columns={columns}
      rowClassName={(record) => (activeId === record.id ? 'row-active' : '')}
      onRow={(record) => ({ onMouseEnter: () => onHover(record.id), onMouseLeave: () => onHover(null) })}
    />
  )
}
