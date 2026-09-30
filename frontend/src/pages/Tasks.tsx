import { useEffect, useState } from 'react'
import { Button, Card, Empty, Space, Table, Tag, Typography, message } from 'antd'
import { Link } from 'react-router-dom'
import { listTasks, type Task } from '../api/client'

const colors: Record<string, string> = { completed: 'success', partial_failed: 'warning', failed: 'error', cancelled: 'default', running: 'processing', queued: 'blue', cancelling: 'warning' }
export function Tasks() {
  const [tasks, setTasks] = useState<Task[]>([])
  useEffect(() => { void listTasks().then((result) => setTasks(result.items)).catch(() => message.error('任务列表加载失败')) }, [])
  return <Card title="任务历史" extra={<Space><Link to="/"><Button>返回工作台</Button></Link><Link to="/composite"><Button type="primary">长图拼接</Button></Link></Space>}>
    {tasks.length ? <Table rowKey="id" dataSource={tasks} pagination={false} columns={[
      { title: '任务 ID', dataIndex: 'id', ellipsis: true, render: (id: string) => <Link to={`/tasks/${id}`}>{id}</Link> },
      { title: '状态', dataIndex: 'status', render: (status: string) => <Tag color={colors[status]}>{status}</Tag> },
      { title: '进度', render: (_: unknown, task: Task) => `${task.completed_jobs}/${task.total_jobs}` },
      { title: '更新时间', dataIndex: 'updated_at', render: (value?: string) => value ? new Date(value).toLocaleString() : '-' },
    ]} /> : <Empty description="暂无任务" />}
    <Typography.Paragraph type="secondary" className="page-note">任务结果会保留在本地数据库，可进入详情页查看失败原因并重试。</Typography.Paragraph>
  </Card>
}
