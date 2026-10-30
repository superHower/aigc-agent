import { Alert, Button, Card, Col, Image, Progress, Row, Space, Table, Tag, Typography, message } from 'antd'
import { Link, useParams } from 'react-router-dom'
import { cancelTask, retryTask, promptError } from '../api/client'
import { useTaskProgress } from '../hooks/useTaskProgress'
import { AppHeader } from '../components/AppHeader'
import { TaskResults } from '../components/TaskResults'

const colors: Record<string, string> = { completed: 'success', partial_failed: 'warning', failed: 'error', cancelled: 'default', processing: 'processing', pending: 'blue', done: 'success' }
export function TaskDetail() {
  const { id = '' } = useParams()
  const { task: current, error, refresh } = useTaskProgress(id)
  if (!current) return <div className="app-shell"><AppHeader /><main className="workspace-content">{error ? <Alert type="error" message={error} action={<Button onClick={refresh}>重新加载</Button>} /> : <Card loading />}</main></div>
  const active = !['completed', 'partial_failed', 'failed', 'cancelled'].includes(current.status)
  const retry = async (jobId?: string) => { try { await retryTask(id, jobId); refresh(); message.success('已提交重试') } catch (reason) { message.error(promptError(reason)) } }
  const cancel = async () => { try { await cancelTask(id); message.success('已请求取消') } catch (reason) { message.error(reason instanceof Error ? reason.message : '取消失败') } }
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Space direction="vertical" size="large" className="page-stack">
    <Card title="任务详情" extra={<Space><Link to="/tasks"><Button>任务历史</Button></Link><Link to="/workspace"><Button>工作台</Button></Link></Space>}>
      <Space wrap><Typography.Text code>{current.id}</Typography.Text><Tag color={colors[current.status]}>{current.status}</Tag><Typography.Text>{current.completed_jobs}/{current.total_jobs} 已完成</Typography.Text><Button danger disabled={!active} onClick={() => void cancel()}>取消任务</Button><Button onClick={() => void retry()} disabled={active}>重试失败步骤</Button></Space>
      <Typography.Text>自动重试 {current.auto_retry_count ?? 0} / {current.auto_retry_limit ?? 3} 轮 · 已扣 {current.credit_summary?.settled ?? 0} · 冻结 {current.credit_summary?.frozen ?? 0} · 释放 {current.credit_summary?.released ?? 0} 积分</Typography.Text><Progress percent={Math.round(current.progress * 100)} status={current.status === 'failed' ? 'exception' : current.status === 'completed' ? 'success' : 'active'} />
      {error && <Alert type="error" message={error} />}
    </Card>
    <Card title="结果与步骤对比">
      <Button href={`/api/task/${id}/download`} disabled={!current.completed_jobs}>下载已生成图片 ZIP</Button>
      <Table rowKey="id" dataSource={current.jobs} pagination={false} columns={[
        { title: '步骤', dataIndex: 'step' }, { title: '渠道', dataIndex: 'channel_name' }, { title: '状态', dataIndex: 'status', render: (status: string) => <Tag color={colors[status]}>{status}</Tag> }, { title: '重试次数', dataIndex: 'retry_count' }, { title: '错误', dataIndex: 'error', ellipsis: true },
        { title: '结果', render: (_: unknown, job: typeof current.jobs[number]) => job.output_url ? <Space direction="vertical"><Image width={96} src={job.output_url} /><a href={job.output_url} download={job.output_filename ?? `${job.id}.png`}>下载图片</a></Space> : '-' },
        { title: '操作', render: (_: unknown, job: typeof current.jobs[number]) => <Button size="small" disabled={!['failed','cancelled'].includes(job.status) || active} onClick={() => void retry(job.id)}>重试</Button> },
      ]} />
    </Card>
    {current.error && <Alert type="error" message={current.error} />}
    <Row gutter={[16, 16]}><Col xs={24} lg={8}><Card title="原图输入"><Image.PreviewGroup>{[...new Set(current.jobs.map((job) => job.source_id))].map((sourceId) => <Image key={sourceId} width={150} src={`/api/files/${sourceId}`} />)}</Image.PreviewGroup></Card></Col><Col xs={24} lg={16}><Card title="已生成图片（可逐张下载）"><TaskResults jobs={current.jobs} /></Card></Col></Row>
  </Space></main></div>
}
