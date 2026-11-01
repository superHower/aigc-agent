import { useEffect, useState } from 'react'
import { Button, Card, Empty, Image, Pagination, Spin, Tag, Typography, message } from 'antd'
import { Link } from 'react-router-dom'
import { listTasks, type Task } from '../api/client'
import { AppHeader } from '../components/AppHeader'

const colors: Record<string, string> = { completed: 'success', partial_failed: 'warning', failed: 'error', cancelled: 'default', running: 'processing', queued: 'blue', cancelling: 'warning' }
export function Tasks() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const pageSize = 20
  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      try {
        const result = await listTasks(page, pageSize)
        if (active) { setTasks(result.items); setTotal(result.total) }
      } catch {
        if (active) message.error('任务列表加载失败，请刷新页面重试')
      } finally {
        if (active) setLoading(false)
      }
    }
    void load()
    return () => { active = false }
  }, [page])
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Card title="任务历史" extra={<Link to="/workspace"><Button>返回工作台</Button></Link>}>
    <Spin spinning={loading}>
      {tasks.length ? <div className="task-history-grid">{tasks.map(task => {
        const firstJob = task.jobs[0]
        return <article className="task-history-card" key={task.id}>
          <Link className="task-history-images" to={`/tasks/${task.id}`} aria-label={`查看任务 ${task.id} 详情`}>
              <div className="task-history-image">
                <span className="task-history-image-label">原待图</span>
                {firstJob ? <Image preview={false} src={`/api/files/${firstJob.source_id}`} alt={firstJob.source_filename ?? '原待图'} /> : <div className="task-history-placeholder">暂无原图</div>}
              </div>
              <div className="task-history-image">
                <span className="task-history-image-label">结果图</span>
                {firstJob?.output_url ? <Image preview={false} src={firstJob.output_url} alt="第一个步骤的结果图" /> : <div className="task-history-placeholder">{['failed', 'partial_failed'].includes(task.status) ? '暂无结果' : task.status === 'cancelled' ? '已取消' : '等待生成'}</div>}
              </div>
          </Link>
          <div className="task-history-footer">
            <dl className="task-history-meta">
              <div><dt>状态</dt><dd><Tag color={colors[task.status]}>{task.status}</Tag></dd></div>
              <div className="task-history-progress"><dt>进度</dt><dd>{task.completed_jobs}/{task.total_jobs}</dd></div>
              <div className="task-history-updated"><dt>更新时间</dt><dd>{task.updated_at ? <time dateTime={task.updated_at}>{new Date(task.updated_at).toLocaleString()}</time> : '—'}</dd></div>
              <div className="task-history-cost"><dt>预计费用</dt><dd>¥{(task.estimated_cost ?? 0).toFixed(2)}</dd></div>
            </dl>
          </div>
        </article>
      })}</div> : <Empty description={loading ? '正在加载任务' : '暂无任务'} />}
    </Spin>
    {!!total && <Pagination className="task-history-pagination" current={page} pageSize={pageSize} total={total} onChange={setPage} showSizeChanger={false} showTotal={value => `共 ${value} 条`} />}
    <Typography.Paragraph type="secondary" className="page-note">任务结果会保留在本地数据库，可进入详情页查看失败原因并重试。</Typography.Paragraph>
  </Card></main></div>
}
