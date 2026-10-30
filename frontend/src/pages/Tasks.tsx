import { useEffect, useState } from 'react'
import { Button, Card, Empty, Table, Tag, Typography, message } from 'antd'
import { Link } from 'react-router-dom'
import { listTasks, type Task } from '../api/client'
import { AppHeader } from '../components/AppHeader'

const colors: Record<string, string> = { completed: 'success', partial_failed: 'warning', failed: 'error', cancelled: 'default', running: 'processing', queued: 'blue', cancelling: 'warning' }
export function Tasks() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const pageSize = 20
  useEffect(() => {
    let active = true
    let timer: number | undefined
    let errorShown = false
    const poll = async () => {
      try {
        const result = await listTasks(page, pageSize)
        if (active) { setTasks(result.items); setTotal(result.total); errorShown = false }
      } catch {
        if (active && !errorShown) { message.error('任务列表加载失败，正在自动重试'); errorShown = true }
      } finally {
        if (active) timer = window.setTimeout(poll, 2500)
      }
    }
    void poll()
    return () => { active = false; if (timer) window.clearTimeout(timer) }
  }, [page])
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Card title="任务历史" extra={<Link to="/workspace"><Button>返回工作台</Button></Link>}>
    {tasks.length || total ? <Table rowKey="id" dataSource={tasks} pagination={{ current: page, pageSize, total, onChange: setPage, showTotal: (value) => `共 ${value} 条` }} columns={[
      { title: '任务 ID', dataIndex: 'id', ellipsis: true, render: (id: string) => <Link to={`/tasks/${id}`}>{id}</Link> },
      { title: '状态', dataIndex: 'status', render: (status: string) => <Tag color={colors[status]}>{status}</Tag> },
      { title: '进度', render: (_: unknown, task: Task) => `${task.completed_jobs}/${task.total_jobs}` },
      { title: '预计费用', render: (_: unknown, task: Task) => `¥${(task.estimated_cost ?? 0).toFixed(2)}` },
      { title: '结果', render: (_: unknown, task: Task) => <Button href={`/api/task/${task.id}/download`} disabled={!task.completed_jobs}>下载 ZIP</Button> },
      { title: '更新时间', dataIndex: 'updated_at', render: (value?: string) => value ? new Date(value).toLocaleString() : '-' },
    ]} /> : <Empty description="暂无任务" />}
    <Typography.Paragraph type="secondary" className="page-note">任务结果会保留在本地数据库，可进入详情页查看失败原因并重试。</Typography.Paragraph>
  </Card></main></div>
}
