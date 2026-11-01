import { useEffect, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Image,
  Popconfirm,
  Input,
  Layout,
  Progress,
  Row,
  Select,
  Space,
  Switch,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import { InboxOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import type { UploadProps } from 'antd'
import {
  analyzeFiles,
  cancelTask,
  generateMultiImage,
  uploadFiles,
  api,
  promptError,
  idempotencyKey,
  type AnalysisFile,
  type UploadedFile,
} from '../api/client'
import { AnnotatedImage } from '../components/AnnotatedImage'
import { TextBlockTable } from '../components/TextBlockTable'
import { useTaskProgress } from '../hooks/useTaskProgress'
import { AppHeader } from '../components/AppHeader'
import { TaskResults } from '../components/TaskResults'
import { PromptTemplatePicker } from '../components/PromptTemplatePicker'
import { useAuth } from '../components/AuthProvider'

const ratioOptions = [
  { label: '原比例', value: 'original' },
  { label: '1:1', value: '1:1' },
  { label: '3:4', value: '3:4' },
  { label: '16:9', value: '16:9' },
]
const terminalStatuses = ['completed', 'partial_failed', 'failed', 'cancelled']

export function Workspace() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [available, setAvailable] = useState<number | null>(null)
  const submission = useRef<{ payload: string; key: string } | null>(null)
  useEffect(() => {
    if (isAdmin) {
      setAvailable(0)
      return
    }
    const refresh = () => api.get('/account/credits').then(r => setAvailable(r.data.available)).catch(() => setAvailable(null))
    void refresh()
    const timer = window.setInterval(() => void refresh(), 10000)
    return () => window.clearInterval(timer)
  }, [isAdmin])
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [analysis, setAnalysis] = useState<AnalysisFile[]>([])
  const [ocrEnabled, setOcrEnabled] = useState(false)
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [activeBlockId, setActiveBlockId] = useState<string | null>(null)
  const [replacements, setReplacements] = useState<
    Record<string, Record<string, { replace: string; enabled: boolean }>>
  >({})
  const [mode, setMode] = useState<'shared' | 'reference'>('shared')
  const [prompt, setPrompt] = useState('')
  const [ratios, setRatios] = useState<string[]>(['original'])
  const [targets, setTargets] = useState<string[]>([])
  const [referenceId, setReferenceId] = useState<string>()
  const [referencePrompt, setReferencePrompt] = useState('')
  const [quality, setQuality] = useState('high')
  const [rightsConfirmed, setRightsConfirmed] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const uploadInProgress = useRef(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const { task, error: taskError, refresh: refreshTask } = useTaskProgress(taskId)
  const currentFile = files.find((file) => file.file_id === selectedFile) ?? files[0]
  const currentAnalysis = analysis.find((item) => item.file_id === currentFile?.file_id)
  const sourceIds = mode === 'shared' ? files.map((file) => file.file_id) : targets
  const ocrSteps =
    ocrEnabled && mode === 'shared'
      ? analysis.reduce(
          (total, item) =>
            total +
            item.text_blocks.filter((block) => {
              const replacement = replacements[item.file_id]?.[block.id]
              return (
                replacement?.enabled &&
                replacement.replace.trim() &&
                replacement.replace.trim() !== block.original.trim()
              )
            }).length,
          0,
        )
      : 0
  const fileOptions = files.map((file) => ({ value: file.file_id, label: file.filename }))

  const removeFile = (fileId: string) => {
    setFiles((previous) => {
      const next = previous.filter((file) => file.file_id !== fileId)
      if (selectedFile === fileId) {
        setSelectedFile(next[0]?.file_id ?? null)
        setActiveBlockId(null)
      }
      return next
    })
    setAnalysis((previous) => previous.filter((item) => item.file_id !== fileId))
    setTargets((previous) => previous.filter((id) => id !== fileId))
    setReferenceId((previous) => previous === fileId ? undefined : previous)
  }

  const analyze = async (uploaded: UploadedFile[]) => {
    if (!uploaded.length) return
    setAnalyzing(true)
    try {
      const result = await analyzeFiles(uploaded.map((file) => file.file_id))
      setAnalysis((previous) => [
        ...previous.filter((item) => !uploaded.some((file) => file.file_id === item.file_id)),
        ...result.files,
      ])
      if (result.files.some((item) => item.error))
        message.warning('部分图片识别失败，请重新识别后再提交 OCR 编辑')
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : 'OCR 识别失败')
    } finally {
      setAnalyzing(false)
    }
  }

  const uploadProps: UploadProps = {
    multiple: true,
    fileList: [],
    accept: 'image/png,image/jpeg,image/webp',
    showUploadList: false,
    disabled: uploading || analyzing,
    beforeUpload: async (file, fileList) => {
      if (file !== fileList[fileList.length - 1] || uploadInProgress.current) return false
      if (files.length + fileList.length > 50) {
        message.warning('最多上传 50 张图片')
        return false
      }
      uploadInProgress.current = true
      setUploading(true)
      try {
        const result = await uploadFiles(
          [...fileList].sort((first, second) =>
            first.name.localeCompare(second.name, 'zh-CN', { numeric: true }),
          ),
        )
        const next = [...files, ...result.files].sort((first, second) =>
          first.filename.localeCompare(second.filename, 'zh-CN', { numeric: true }),
        )
        setFiles(next)
        setSelectedFile((previous) => previous ?? next[0]?.file_id ?? null)
        if (ocrEnabled && mode === 'shared') await analyze(result.files)
      } catch (reason) {
        message.error(reason instanceof Error ? reason.message : '上传失败')
      } finally {
        uploadInProgress.current = false
        setUploading(false)
      }
      return false
    },
  }

  const generate = async () => {
    if (!rightsConfirmed) {
      message.warning('请确认拥有素材使用权')
      return
    }
    if (!sourceIds.length || !ratios.length) {
      message.warning('请选择待处理图片和至少一种比例')
      return
    }
    if (mode === 'shared' && !prompt.trim()) {
      message.warning('请填写通用提示词')
      return
    }
    if (mode === 'reference' && (!referenceId || !referencePrompt.trim())) {
      message.warning('请选择参考图并填写编辑要求')
      return
    }
    const overrides = Object.fromEntries(
      sourceIds.map((sourceId) => [
        sourceId,
        {
          text_blocks: Object.entries(replacements[sourceId] ?? {}).map(([id, value]) => ({
            id,
            ...value,
          })),
        },
      ]),
    )
    setSubmitting(true)
    try {
      const payload = {
        source_ids: sourceIds,
        mode,
        prompt: mode === 'reference' ? referencePrompt : prompt,
        aspect_ratios: ratios,
        reference_file_id: referenceId,
        ocr_enabled: isAdmin && ocrEnabled && mode === 'shared',
        per_source_overrides: overrides,
        quality,
      }
      const preview = (await api.post('/generate/preview', payload)).data
      setAvailable(preview.available)
      if (preview.required_credits > preview.available) { message.error('可用积分不足，请充值后重试；未扣除积分'); return }
      const serialized = JSON.stringify(payload)
      if (submission.current?.payload !== serialized) submission.current = { payload: serialized, key: idempotencyKey() }
      const result = await generateMultiImage(payload, submission.current!.key)
      submission.current = null
      setTaskId(result.task_id)
      message.success('任务已提交，可继续提交其他任务；所有任务共享并发额度')
    } catch (reason) {
      message.error(promptError(reason))
    } finally {
      setSubmitting(false)
    }
  }

  const cancelCurrentTask = async () => {
    if (!taskId) return
    try {
      await cancelTask(taskId)
      message.success('已请求取消本次任务')
      refreshTask()
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '取消任务失败')
    }
  }

  return (
    <Layout className="app-shell">
      <AppHeader />
      <Layout.Content className="workspace-content">
        <Row gutter={[18, 18]}>
          <Col xs={24} lg={9}>
            <Card title="上传图片" className="panel-card" extra={<Tag>{files.length} / 50</Tag>}>
              <Space wrap className="option-row">
                {ocrEnabled && mode === 'shared' && (
                  <Button
                    size="small"
                    loading={analyzing}
                    disabled={!files.length || uploading}
                    onClick={() => void analyze(files)}
                  >
                    重新识别
                  </Button>
                )}
              </Space>
              <Upload.Dragger {...uploadProps}>
                <p className="ant-upload-drag-icon">
                  <InboxOutlined />
                </p>
                <p className="ant-upload-text">
                  {uploading
                    ? '正在上传…'
                    : analyzing
                      ? '正在 OCR 识别…'
                      : '拖入或选择图片，最多 50 张'}
                </p>
                <p className="ant-upload-hint">
                  PNG、JPG、WebP · 按文件名自然排序 · OCR 关闭时仅上传
                </p>
              </Upload.Dragger>
              <div className="uploaded-grid">
                  {files.map((file) => (
                    <div className={`uploaded-item-wrap ${file.file_id === currentFile?.file_id ? 'uploaded-item-active' : ''}`} key={file.file_id}>
                      <button type="button" className="uploaded-item" onClick={() => { setSelectedFile(file.file_id); setActiveBlockId(null) }}>
                        <img src={file.url} alt={file.filename} />
                        <span title={file.filename}>{file.filename}</span>
                      </button>
                      <Popconfirm title="移除这张图片？" description="只会从当前工作台移除，不删除服务器上的原文件。" okText="移除" cancelText="取消" onConfirm={() => removeFile(file.file_id)}>
                        <Button className="uploaded-item-remove" type="text" danger size="small" aria-label={`删除${file.filename}`} onClick={(event) => event.stopPropagation()}>×</Button>
                      </Popconfirm>
                    </div>
                  ))}
              </div>
              {currentFile &&
                (ocrEnabled && mode === 'shared' && currentAnalysis ? (
                  <AnnotatedImage
                    analysis={currentAnalysis}
                    activeBlockId={activeBlockId}
                    onSelect={(block) => setActiveBlockId(block.id)}
                  />
                ) : (
                  <Image src={currentFile.url} alt={currentFile.filename} />
                ))}
              {currentAnalysis?.error && ocrEnabled && (
                <Alert type="error" message={currentAnalysis.error} />
              )}
            </Card>
          </Col>
          <Col xs={24} lg={15}>
            <Card title="批量生成模式" className="panel-card">
              <Tabs
                activeKey={mode}
                items={[
                  { key: 'shared', label: '多图', disabled: uploading || analyzing },
                  { key: 'reference', label: '参考图组合', disabled: uploading || analyzing },
                ]}
                onChange={(value) => {
                  setMode(value as 'shared' | 'reference')
                  if (value === 'reference') setOcrEnabled(false)
                }}
              />
              {mode === 'shared' ? (
                <div className="option-card">
                  <Typography.Title level={5}>通用提示词</Typography.Title>
                  <PromptTemplatePicker value={prompt} onChange={setPrompt} />
                  <Input.TextArea
                    value={prompt}
                    onChange={(event) => setPrompt(event.target.value)}
                    placeholder="所有图片独立执行此规则，例如：将背景改为干净的白色摄影棚，保持产品和文字不变。"
                    autoSize={{ minRows: 4, maxRows: 10 }}
                  />
                </div>
              ) : (
                <Space direction="vertical" className="page-stack option-card">
                  <Select
                    style={{ width: '100%' }}
                    value={referenceId}
                    onChange={(value) => {
                      setReferenceId(value)
                      setTargets((previous) => previous.filter((id) => id !== value))
                    }}
                    placeholder="选择参考图片，例如图一"
                    options={fileOptions}
                  />
                  <Typography.Text>
                    每张待处理图片都会分别结合参考图执行编辑要求。
                  </Typography.Text>
                  <Checkbox disabled={!referenceId || !fileOptions.some(option => option.value !== referenceId)} checked={!!referenceId && targets.length === fileOptions.filter(option => option.value !== referenceId).length && targets.length > 0} indeterminate={targets.length > 0 && targets.length < fileOptions.filter(option => option.value !== referenceId).length} onChange={event => setTargets(event.target.checked ? fileOptions.filter(option => option.value !== referenceId).map(option => option.value) : [])}>全选待处理图片（不含参考图）</Checkbox>
                  <Select
                    mode="multiple"
                    style={{ width: '100%' }}
                    value={targets}
                    onChange={setTargets}
                    placeholder="选择待处理图片，例如图二、图三、图四"
                    options={fileOptions.filter((option) => option.value !== referenceId)}
                  />
                  <Typography.Title level={5} id="reference-prompt-label">编辑要求</Typography.Title>
                  <Typography.Text type="secondary" id="reference-prompt-help">
                    可以描述替换内容、参考方式、保留内容及其他限制。未提及的部分默认尽量保留。
                  </Typography.Text>
                  <PromptTemplatePicker value={referencePrompt} onChange={setReferencePrompt} />
                  <Input.TextArea
                    aria-labelledby="reference-prompt-label"
                    aria-describedby="reference-prompt-help"
                    autoSize={{ minRows: 4, maxRows: 10 }}
                    value={referencePrompt}
                    onChange={(event) => setReferencePrompt(event.target.value)}
                    maxLength={32000}
                    showCount
                    placeholder="将待处理图片的背景换成参考图中的场景，参考其色调和光照。保持原产品的外形、颜色、文字和位置不变，调整阴影使产品自然融入背景，不要增加其他物品。"
                  />

                </Space>
              )}
              <Space direction="vertical" size="middle" className="page-stack">
                <Typography.Text strong>输出比例（每种比例生成一张，独立处理）</Typography.Text>
                <Checkbox.Group
                  options={ratioOptions}
                  value={ratios}
                  onChange={(values) => setRatios(values.map(String))}
                />
                <Space>
                  <Typography.Text>质量</Typography.Text>
                  <Select
                    value={quality}
                    onChange={setQuality}
                    options={['low', 'medium', 'high', 'xhigh', 'max'].map((value) => ({
                      value,
                      label: value,
                    }))}
                  />
                </Space>
                <Alert
                  type="info"
                  message={isAdmin ? `预计生成 ${sourceIds.length * ratios.length} 张图片${ocrSteps ? `，另有 ${ocrSteps} 个文字编辑步骤` : ''}；成本请在经营总览按调用记录查看。` : `预计生成 ${sourceIds.length * ratios.length} 张，需要 ${sourceIds.length * ratios.length} 积分；可用 ${available ?? '加载中'}。成功扣费，最终失败或取消释放；文字识别免费。`}
                />
              </Space>
            </Card>
            {isAdmin && ocrEnabled && mode === 'shared' && (
              <Card title="OCR 文字块编辑（可选）" className="panel-card">
                {currentAnalysis ? (
                  <TextBlockTable
                    blocks={currentAnalysis.text_blocks}
                    replacements={replacements[currentAnalysis.file_id] ?? {}}
                    activeId={activeBlockId}
                    onHover={setActiveBlockId}
                    onChange={(id, value) =>
                      setReplacements((previous) => ({
                        ...previous,
                        [currentAnalysis.file_id]: {
                          ...previous[currentAnalysis.file_id],
                          [id]: value,
                        },
                      }))
                    }
                  />
                ) : (
                  <Typography.Text type="secondary">
                    启用 OCR 后识别文字块，可先编辑文字再执行通用提示词。
                  </Typography.Text>
                )}
              </Card>
            )}
            <Card className="panel-card">
              <Space wrap>
                <Checkbox
                  checked={rightsConfirmed}
                  onChange={(event) => setRightsConfirmed(event.target.checked)}
                >
                  我确认拥有素材使用权
                </Checkbox>
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  loading={submitting}
                  disabled={!files.length || uploading || analyzing || submitting || (!!task && !terminalStatuses.includes(task.status)) || (!isAdmin && (available === null || available < sourceIds.length * ratios.length))}
                  onClick={() => void generate()}
                >
                  提交批量任务
                </Button>
                <Link to="/tasks">查看所有并行任务</Link>
              </Space>
            </Card>
            {taskId && (
              <Card
                title="任务进度与生成结果"
                className="panel-card"
                extra={<Link to={`/tasks/${taskId}`}>任务详情</Link>}
              >
                <Typography.Text>
                  自动重试 {task?.auto_retry_count ?? 0} / {task?.auto_retry_limit ?? 3} 轮
                </Typography.Text>
                <Progress
                  percent={Math.round((task?.progress ?? 0) * 100)}
                  status={
                    task?.status === 'failed' || task?.status === 'partial_failed'
                      ? 'exception'
                      : task?.status === 'completed'
                        ? 'success'
                        : task && terminalStatuses.includes(task.status)
                          ? 'normal'
                          : 'active'
                  }
                />
                <Space wrap>
                  <Tag>{task?.status ?? 'queued'}</Tag>
                  <Typography.Text>
                    成功 {task?.completed_jobs ?? 0} / {task?.total_jobs ?? 0}
                  </Typography.Text>
                  <Typography.Text>
                    失败 {task?.failed_jobs ?? 0} · 取消 {task?.cancelled_jobs ?? 0}
                  </Typography.Text>
                  <Typography.Text>
                    执行中 {task?.jobs.filter((job) => job.status === 'processing').length ?? 0} ·
                    排队 {task?.jobs.filter((job) => job.status === 'pending').length ?? 0}
                  </Typography.Text>
                  <Typography.Text>全局并发上限 {task?.max_concurrency ?? '—'}</Typography.Text>
                  {isAdmin ? <Typography.Text>实际成本以核实账单为准</Typography.Text> : <Typography.Text>已扣 {task?.credit_summary?.settled ?? 0} · 冻结 {task?.credit_summary?.frozen ?? 0} · 释放 {task?.credit_summary?.released ?? 0} 积分</Typography.Text>}
                  <Popconfirm
                    title="确定取消本次任务吗？"
                    description="排队中的步骤会停止，正在执行的步骤可能在当前请求结束后停止。"
                    okText="取消任务"
                    cancelText="继续执行"
                    onConfirm={() => void cancelCurrentTask()}
                  >
                    <Button
                      danger
                      disabled={
                        !taskId ||
                        !task ||
                        terminalStatuses.includes(task.status) ||
                        task.status === 'cancelling'
                      }
                    >
                      {task?.status === 'cancelling' ? '正在取消…' : '取消本次任务'}
                    </Button>
                  </Popconfirm>
                </Space>
                {taskError && <Alert type="error" message={taskError} />}
                <div className="generated-results">
                  <Button
                    href={`/api/task/${taskId}/download`}
                    disabled={
                      !task?.jobs.some((job) => job.output_url && job.step.startsWith('custom_'))
                    }
                  >
                    {task && !terminalStatuses.includes(task.status)
                      ? '下载已生成图片 ZIP'
                      : '全部下载 ZIP'}
                  </Button>
                  <TaskResults jobs={task?.jobs ?? []} active={!task || !terminalStatuses.includes(task.status)} onSubmitted={refreshTask} />
                </div>
              </Card>
            )}
          </Col>
        </Row>
      </Layout.Content>
    </Layout>
  )
}
