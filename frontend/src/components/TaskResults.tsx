import { Button, Empty, Image, Tag, Typography } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import type { TaskJob } from '../api/client'

export function TaskResults({ jobs }: { jobs: TaskJob[] }) {
  const results = jobs.filter((job) => job.output_url)
  const sourceIds = [...new Set(jobs.map((job) => job.source_id))]

  if (!results.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无生成结果，每个步骤完成后图片会自动显示在这里" />

  return <Image.PreviewGroup><div className="result-grid">
    {results.map((job, index) => <div className="result-card" key={job.id}>
      <Image src={job.output_url!} alt={`图片 ${sourceIds.indexOf(job.source_id) + 1} · ${job.step}`} />
      <Typography.Text strong>结果 {index + 1} · 原图 {sourceIds.indexOf(job.source_id) + 1}</Typography.Text>
      <Typography.Text ellipsis title={job.output_filename ?? job.step}>{job.output_filename ?? job.step}</Typography.Text>
      <Tag color="success">已生成</Tag>
      <Button icon={<DownloadOutlined />} href={job.output_url!} download={job.output_filename ?? `${job.id}.png`}>下载图片</Button>
    </div>)}
  </div></Image.PreviewGroup>
}
