import { Alert, Button, Card, Col, Image, Progress, Row, Space, Table, Tag, Typography, message } from 'antd'
import { Link, useParams } from 'react-router-dom'
import { cancelTask, retryTask, promptError } from '../api/client'
import { useTaskProgress } from '../hooks/useTaskProgress'
import { AppHeader } from '../components/AppHeader'
import { RefineImageButton } from '../components/RefineImageButton'

const colors: Record<string, string> = { completed: 'success', partial_failed: 'warning', failed: 'error', cancelled: 'default', processing: 'processing', pending: 'blue', done: 'success' }
export function TaskDetail() {
  const { id = '' } = useParams()
  const { task: current, error, refresh } = useTaskProgress(id)
  if (!current) return <div className="app-shell"><AppHeader /><main className="workspace-content">{error ? <Alert type="error" message={error} action={<Button onClick={refresh}>重新加载</Button>} /> : <Card loading />}</main></div>
  const active = !['completed', 'partial_failed', 'failed', 'cancelled'].includes(current.status)
  const referenceUrls = [...new Set(current.jobs.flatMap(job => job.reference_urls ?? []))]
  const promptGroups = new Map<string, typeof current.jobs>()
  for (const job of current.jobs) {
    if (job.prompt) promptGroups.set(job.prompt, [...(promptGroups.get(job.prompt) ?? []), job])
  }
  const retry = async (jobId?: string) => { try { await retryTask(id, jobId); refresh(); message.success('已提交重试') } catch (reason) { message.error(promptError(reason)) } }
  const cancel = async () => { try { await cancelTask(id); message.success('已请求取消') } catch (reason) { message.error(reason instanceof Error ? reason.message : '取消失败') } }
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Space direction="vertical" size="large" className="page-stack">
    <Card title="任务详情" extra={<Space><Link to="/tasks"><Button>任务历史</Button></Link><Link to="/workspace"><Button>工作台</Button></Link></Space>}>
      <Space wrap><Typography.Text code>{current.id}</Typography.Text><Tag color={colors[current.status]}>{current.status}</Tag><Typography.Text>{current.completed_jobs}/{current.total_jobs} 已完成</Typography.Text><Button danger disabled={!active} onClick={() => void cancel()}>取消任务</Button><Button onClick={() => void retry()} disabled={active}>重试失败步骤</Button></Space>
      <Typography.Text>自动重试 {current.auto_retry_count ?? 0} / {current.auto_retry_limit ?? 3} 轮 · 已扣 {current.credit_summary?.settled ?? 0} · 冻结 {current.credit_summary?.frozen ?? 0} · 释放 {current.credit_summary?.released ?? 0} 积分</Typography.Text><Progress percent={Math.round(current.progress * 100)} status={current.status === 'failed' ? 'exception' : current.status === 'completed' ? 'success' : 'active'} />
      {error && <Alert type="error" message={error} />}
    </Card>
    <Card title="原参考图与模型提示词">
      <Row gutter={[24, 24]}>
        <Col xs={24} md={6}>
          <Typography.Title level={5}>原参考图</Typography.Title>
          {referenceUrls.length ? <Image.PreviewGroup><Space wrap>{referenceUrls.map(url => <Image key={url} width={150} src={url} alt="原参考图" />)}</Space></Image.PreviewGroup> : <Typography.Text type="secondary">此任务未使用参考图</Typography.Text>}
        </Col>
        <Col xs={24} md={18}>
          <Typography.Title level={5}>完整提示词</Typography.Title>
          {[...promptGroups.keys()].map(prompt => <div key={prompt}>
            <Typography.Paragraph copyable={{ text: prompt }} style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{prompt}</Typography.Paragraph>
          </div>)}
          {!promptGroups.size && <Typography.Text type="secondary">暂无提示词记录</Typography.Text>}
        </Col>
      </Row>
    </Card>
    <Card title="结果与步骤对比">
      <Button href={`/api/task/${id}/download`} disabled={!current.completed_jobs}>下载已生成图片 ZIP</Button>
      <Table rowKey="id" dataSource={current.jobs} pagination={false} scroll={{ x: 1100 }} columns={[
        { title: '文件名', dataIndex: 'source_filename', width: 180, render: (filename?: string | null) => <Typography.Text style={{ overflowWrap: 'anywhere' }}>{filename || '—'}</Typography.Text> },
        { title: '用时', dataIndex: 'duration_seconds', width: 120, render: (seconds?: number | null) => seconds == null ? '—' : seconds < 60 ? `${seconds.toFixed(1)} 秒` : `${Math.floor(seconds / 60)} 分 ${(seconds % 60).toFixed(1)} 秒` },
        // { title: '步骤', dataIndex: 'step' }, 
        { title: '渠道', dataIndex: 'channel_name' }, { title: '状态', dataIndex: 'status', render: (status: string) => <Tag color={colors[status]}>{status}</Tag> }, { title: '重试次数', dataIndex: 'retry_count' },
        { title: '原待处理图', render: (_: unknown, job: typeof current.jobs[number]) => <Image width={96} src={`/api/files/${job.source_id}`} alt="原待处理图" /> },
        { title: '结果', render: (_: unknown, job: typeof current.jobs[number]) => job.output_url ? <Image width={96} src={job.output_url} alt="生成结果" /> : '—' },
        { title: '操作', render: (_: unknown, job: typeof current.jobs[number]) => <Space wrap><Button size="small" href={job.output_url ?? undefined} download={job.output_filename ?? `${job.id}.png`} disabled={!job.output_url}>下载图片</Button>{job.status === 'done' ? <RefineImageButton job={job} disabled={active} onSubmitted={refresh} /> : <Button size="small" disabled={!['failed','cancelled'].includes(job.status) || active} onClick={() => void retry(job.id)}>重试</Button>}</Space> },
      ]} />
      <Typography.Text type="secondary">用时为累计处理时间，包含重试，不含排队；历史记录无执行时间时显示“—”。</Typography.Text>
    </Card>
    {current.error && <Alert type="error" message={current.error} />}
  </Space></main></div>
}
