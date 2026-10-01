import { useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Image, Progress, Row, Space, Table, Tag, Typography, message } from 'antd'
import { Link, useParams } from 'react-router-dom'
import { cancelTask, getTask, retryTask, type Task } from '../api/client'
import { useTaskProgress } from '../hooks/useTaskProgress'
import { AppHeader } from '../components/AppHeader'

const colors: Record<string, string> = { completed: 'success', partial_failed: 'warning', failed: 'error', cancelled: 'default', processing: 'processing', pending: 'blue', done: 'success' }
export function TaskDetail() {
  const { id = '' } = useParams(); const [initial, setInitial] = useState<Task | null>(null)
  const { task, error } = useTaskProgress(id); const current = task ?? initial
  useEffect(() => { void getTask(id).then(setInitial).catch(() => message.error('任务加载失败')) }, [id])
  if (!current) return <Card loading />
  const active = !['completed', 'partial_failed', 'failed', 'cancelled'].includes(current.status)
  const retry = async (jobId?: string) => { try { await retryTask(id, jobId); message.success('已提交重试') } catch (reason) { message.error(reason instanceof Error ? reason.message : '重试失败') } }
  const cancel = async () => { try { await cancelTask(id); message.success('已请求取消') } catch (reason) { message.error(reason instanceof Error ? reason.message : '取消失败') } }
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Space direction="vertical" size="large" className="page-stack">
    <Card title="任务详情" extra={<Space><Link to="/tasks"><Button>任务历史</Button></Link><Link to="/"><Button>工作台</Button></Link></Space>}>
      <Space wrap><Typography.Text code>{current.id}</Typography.Text><Tag color={colors[current.status]}>{current.status}</Tag><Typography.Text>{current.completed_jobs}/{current.total_jobs} 已完成</Typography.Text><Button danger disabled={!active} onClick={() => void cancel()}>取消任务</Button><Button onClick={() => void retry()} disabled={active}>重试失败步骤</Button></Space>
      <Progress percent={Math.round(current.progress * 100)} status={current.status === 'failed' ? 'exception' : current.status === 'completed' ? 'success' : 'active'} />
      {error && <Alert type="error" message={error} />}
    </Card>
    <Card title="结果与步骤对比">
      <Table rowKey="id" dataSource={current.jobs} pagination={false} columns={[
        { title: '步骤', dataIndex: 'step' }, { title: '状态', dataIndex: 'status', render: (status: string) => <Tag color={colors[status]}>{status}</Tag> }, { title: '重试次数', dataIndex: 'retry_count' }, { title: '错误', dataIndex: 'error', ellipsis: true },
        { title: '结果', render: (_: unknown, job: typeof current.jobs[number]) => job.output_url ? <Space direction="vertical"><Image width={96} src={job.output_url} /><a href={job.output_url} download>下载图片</a></Space> : '-' },
        { title: '操作', render: (_: unknown, job: typeof current.jobs[number]) => <Button size="small" disabled={job.status !== 'failed' || active} onClick={() => void retry(job.id)}>重试</Button> },
      ]} />
    </Card>
    {current.error && <Alert type="error" message={current.error} />}
    <Row gutter={16}><Col span={12}><Card title="原图输入"><Image.PreviewGroup>{current.jobs.map((job) => <Image key={job.id} width={150} src={`/api/files/${job.source_id}`} />)}</Image.PreviewGroup></Card></Col><Col span={12}><Card title="已生成图片"><div className="result-grid">{current.jobs.filter((job) => job.output_url).map((job) => <div className="result-card" key={job.id}><Image width={150} src={job.output_url ?? ''} /><Typography.Text ellipsis>{job.step}</Typography.Text><a href={job.output_url ?? ''} download>下载图片</a></div>)}</div></Card></Col></Row>
  </Space></main></div>
}
