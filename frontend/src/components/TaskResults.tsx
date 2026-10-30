import { Alert, Button, Empty, Image, Tag, Typography } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import type { TaskJob } from '../api/client'
import { RefineImageButton } from './RefineImageButton'

export function TaskResults({ jobs, active, onSubmitted }: { jobs: TaskJob[]; active?: boolean; onSubmitted?: () => void }) {
  const results = jobs.filter((job) => job.output_url)
  const sourceIds = [...new Set(jobs.map((job) => job.source_id))]
  const errors = [...new Set(jobs.filter((job) => job.status === 'failed' && job.error).map((job) => job.error!))]
  const alerts = errors.map((error) => <Alert key={error} type="error" showIcon message={error} style={{ marginBottom: 12 }} />)

  if (!results.length) return <>{alerts}<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无生成结果，每个步骤完成后图片会自动显示在这里" /></>

  return <>{alerts}<Image.PreviewGroup><div className="result-grid">
    {results.map((job, index) => <div className="result-card" key={job.id}>
      <Image src={job.output_url!} alt={`图片 ${sourceIds.indexOf(job.source_id) + 1} · ${job.step}`} />
      <Typography.Text strong>结果 {index + 1} · 原图 {sourceIds.indexOf(job.source_id) + 1}</Typography.Text>
      <Typography.Text ellipsis title={job.output_filename ?? job.step}>{job.output_filename ?? job.step}</Typography.Text>
      <Tag color="success">已生成</Tag>
      {job.channel_name && <Tag>{job.channel_name}</Tag>}
      <Button icon={<DownloadOutlined />} href={job.output_url!} download={job.output_filename ?? `${job.id}.png`}>下载图片</Button>
      <RefineImageButton job={job} disabled={active} onSubmitted={onSubmitted} />
    </div>)}
  </div></Image.PreviewGroup></>
}
