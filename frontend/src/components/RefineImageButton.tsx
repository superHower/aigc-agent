import { useRef, useState } from 'react'
import { Alert, Button, Image, Input, Modal, Typography, message } from 'antd'
import { api, idempotencyKey, promptError, type TaskJob } from '../api/client'
import { useAuth } from './AuthProvider'

export function RefineImageButton({ job, disabled, onSubmitted }: { job: TaskJob; disabled?: boolean; onSubmitted?: () => void }) {
  const [open, setOpen] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submission = useRef<{ prompt: string; key: string }>()
  const { user } = useAuth()
  return <><Button disabled={disabled || job.status !== 'done' || !job.output_url} onClick={() => { setOpen(true); setError('') }}>进一步优化</Button>
    <Modal title="进一步优化这张图片" open={open} confirmLoading={busy} okText="开始优化" cancelText="取消" okButtonProps={{ disabled: !prompt.trim() }} onCancel={() => { if (!busy) setOpen(false) }} onOk={async () => {
      if (busy || !prompt.trim()) return
      setBusy(true); setError('')
      if (submission.current?.prompt !== prompt.trim()) submission.current = { prompt: prompt.trim(), key: idempotencyKey() }
      try {
        await api.post(`/task/${job.task_id}/jobs/${job.id}/refine`, { prompt: prompt.trim() }, { headers: { 'Idempotency-Key': submission.current.key } })
        submission.current = undefined; setOpen(false); setPrompt(''); onSubmitted?.(); message.success('已在当前任务中提交优化，原结果保留')
      } catch (reason) { setError(promptError(reason)) } finally { setBusy(false) }
    }}>
      {job.output_url && <Image src={job.output_url} width={160} />}
      <Typography.Paragraph>以这张生成图为基础优化，其他图片保持不变，原结果保留供对比。{user?.role === 'admin' ? '超管不限积分。' : '每次优化需要 1 积分，成功扣费，失败释放。'}</Typography.Paragraph>
      {error && <Alert type="error" message={error} />}
      <Input.TextArea aria-label="优化提示词" placeholder="例如：修复右下角边缘瑕疵，保持主体、文字和其他内容不变" value={prompt} onChange={event => setPrompt(event.target.value)} maxLength={32000} autoSize={{ minRows: 4, maxRows: 10 }} />
    </Modal></>
}
