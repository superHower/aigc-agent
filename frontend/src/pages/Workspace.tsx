import { useRef, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Image,
  Input,
  Layout,
  Popconfirm,
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
  type AnalysisFile,
  type UploadedFile,
} from '../api/client'
import { AnnotatedImage } from '../components/AnnotatedImage'
import { TextBlockTable } from '../components/TextBlockTable'
import { useTaskProgress } from '../hooks/useTaskProgress'
import { AppHeader } from '../components/AppHeader'
import { TaskResults } from '../components/TaskResults'
import { PromptTemplatePicker } from '../components/PromptTemplatePicker'

const ratioOptions = [
  { label: '原比例', value: 'original' },
  { label: '1:1', value: '1:1' },
  { label: '3:4', value: '3:4' },
  { label: '16:9', value: '16:9' },
]
const terminalStatuses = ['completed', 'partial_failed', 'failed', 'cancelled']

export function Workspace() {
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
  const [component, setComponent] = useState('背景')
  const [quality, setQuality] = useState('high')
  const [rightsConfirmed, setRightsConfirmed] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const uploadInProgress = useRef(false)
  const [taskId, setTaskId] = useState<string | null>(() =>
    sessionStorage.getItem('workspace-task-id'),
  )
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
  const expectedCount = sourceIds.length * ratios.length + ocrSteps
  const fileOptions = files.map((file) => ({ value: file.file_id, label: file.filename }))

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
    if (mode === 'reference' && (!referenceId || !component.trim())) {
      message.warning('请选择参考图并填写替换内容')
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
      const result = await generateMultiImage({
        source_ids: sourceIds,
        mode,
        prompt,
        aspect_ratios: ratios,
        reference_file_id: referenceId,
        reference_component: component,
        ocr_enabled: ocrEnabled && mode === 'shared',
        per_source_overrides: overrides,
        quality,
      })
      setTaskId(result.task_id)
      sessionStorage.setItem('workspace-task-id', result.task_id)
      message.success('任务已提交，可继续提交其他任务；所有任务共享并发额度')
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '任务提交失败')
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
                <Switch
                  checked={ocrEnabled && mode === 'shared'}
                  disabled={mode === 'reference' || uploading || analyzing}
                  onChange={(enabled) => {
                    setOcrEnabled(enabled)
                    if (enabled) void analyze(files)
                  }}
                />
                <Typography.Text>启用 OCR 文字识别（默认关闭）</Typography.Text>
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
                  <button
                    type="button"
                    className={`uploaded-item ${file.file_id === currentFile?.file_id ? 'uploaded-item-active' : ''}`}
                    key={file.file_id}
                    onClick={() => {
                      setSelectedFile(file.file_id)
                      setActiveBlockId(null)
                    }}
                  >
                    <img src={file.url} alt={file.filename} />
                    <span title={file.filename}>{file.filename}</span>
                  </button>
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
                    请把以下待处理图片的指定内容换成参考图的，其他内容不变。
                  </Typography.Text>
                  <Select
                    mode="multiple"
                    style={{ width: '100%' }}
                    value={targets}
                    onChange={setTargets}
                    placeholder="选择待处理图片，例如图二、图三、图四"
                    options={fileOptions.filter((option) => option.value !== referenceId)}
                  />
                  <PromptTemplatePicker value={component} onChange={setComponent} />
                  <Input.TextArea
                    autoSize={{ minRows: 4, maxRows: 10 }}
                    value={component}
                    onChange={(event) => setComponent(event.target.value)}
                    placeholder="要替换的内容，例如背景"
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
                  message={`预计生成 ${sourceIds.length * ratios.length} 张图片${ocrSteps ? `，另有 ${ocrSteps} 个文字编辑步骤` : ''}，预计费用 ¥${(expectedCount * 0.05).toFixed(2)}`}
                />
              </Space>
            </Card>
            {ocrEnabled && mode === 'shared' && (
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
                  disabled={!files.length || uploading || analyzing}
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
                  <Typography.Text>预计 ¥{(task?.estimated_cost ?? 0).toFixed(2)}</Typography.Text>
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
                  <TaskResults jobs={task?.jobs ?? []} />
                </div>
              </Card>
            )}
          </Col>
        </Row>
      </Layout.Content>
    </Layout>
  )
}
