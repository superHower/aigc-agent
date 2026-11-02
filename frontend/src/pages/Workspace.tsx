import { useEffect, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Popconfirm,
  Input,
  InputNumber,
  Layout,
  Progress,
  Select,
  Space,
  Switch,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'
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
  listPromptGroups,
  type PromptGroup,
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
import { usePromptLibrary } from '../hooks/usePromptLibrary'
import { WorkspaceUpload } from '../components/WorkspaceUpload'

const ratioOptions = [
  { label: '原比例', value: 'original' },
  { label: '1:1', value: '1:1' },
  { label: '3:4', value: '3:4' },
  { label: '16:9', value: '16:9' },
]
const terminalStatuses = ['completed', 'partial_failed', 'failed', 'cancelled']
const naturalProportionsInstruction = '必须保持主体、文字和其他内容的自然比例，禁止拉伸、挤压或变形。'
const canvasAdaptationInstruction = '可调整布局、间距或扩展背景来适配画布，保留完整主体。'

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
  const [sharedFiles, setSharedFiles] = useState<UploadedFile[]>([])
  const [referenceFiles, setReferenceFiles] = useState<UploadedFile[]>([])
  const [targetFiles, setTargetFiles] = useState<UploadedFile[]>([])
  const [groupFiles, setGroupFiles] = useState<UploadedFile[]>([])
  const [analysis, setAnalysis] = useState<AnalysisFile[]>([])
  const [ocrEnabled, setOcrEnabled] = useState(false)
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [activeBlockId, setActiveBlockId] = useState<string | null>(null)
  const [replacements, setReplacements] = useState<
    Record<string, Record<string, { replace: string; enabled: boolean }>>
  >({})
  const [mode, setMode] = useState<'shared' | 'reference' | 'prompt_group'>('shared')
  const library = usePromptLibrary()
  const [promptGroups, setPromptGroups] = useState<PromptGroup[]>([])
  const [promptGroupId, setPromptGroupId] = useState<string>()
  const [groupError, setGroupError] = useState('')
  const [groupsLoading, setGroupsLoading] = useState(false)
  const refreshGroups = async () => {
    setGroupsLoading(true)
    try { setPromptGroups(await listPromptGroups()); setGroupError('') }
    catch (reason) { setGroupError(promptError(reason)) }
    finally { setGroupsLoading(false) }
  }
  useEffect(() => { if (mode === 'prompt_group') { void refreshGroups(); void library.refresh() } }, [mode])
  const [prompt, setPrompt] = useState('')
  const [ratios, setRatios] = useState<string[]>(['original'])
  const files = mode === 'shared' ? sharedFiles : mode === 'reference' ? targetFiles : groupFiles
  const setFiles = mode === 'shared' ? setSharedFiles : mode === 'reference' ? setTargetFiles : setGroupFiles
  const referenceId = referenceFiles[0]?.file_id
  const [referencePrompt, setReferencePrompt] = useState('')
  const activePrompt = mode === 'reference' ? referencePrompt : prompt
  const togglePromptInstruction = (instruction: string, enabled: boolean) => {
    const update = (value: string) => {
      if (enabled) return value.includes(instruction)
        ? value : `${value}${value && !value.endsWith('\n') ? '\n' : ''}${instruction}`
      return value.replace(`\n${instruction}`, '').replace(instruction, '')
    }
    if (mode === 'reference') setReferencePrompt(update)
    else setPrompt(update)
  }
  const [quality, setQuality] = useState('high')
  const [videoResolution, setVideoResolution] = useState<string>()
  const [videoRatio, setVideoRatio] = useState<string>()
  const [videoMode, setVideoMode] = useState<string>()
  const [videoDuration, setVideoDuration] = useState(5)
  const [rightsConfirmed, setRightsConfirmed] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const uploadInProgress = useRef(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const { task, error: taskError, refresh: refreshTask } = useTaskProgress(taskId)
  const currentFile = files.find((file) => file.file_id === selectedFile) ?? files[0]
  const currentAnalysis = analysis.find((item) => item.file_id === currentFile?.file_id)
  const sourceIds = files.map(file => file.file_id)
  const selectedGroup = promptGroups.find(group => group.id === promptGroupId)
  const groupTemplates = selectedGroup?.template_ids.map(id => library.templates.find(template => template.id === id)) ?? []
  const imageCount = mode === 'prompt_group' ? (sourceIds.length ? groupTemplates.length : 0) : sourceIds.length * ratios.length
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

  const makeUploadProps = (role: 'source' | 'reference'): UploadProps => {
    const existing = role === 'reference' ? referenceFiles : files
    const limit = role !== 'source' || mode === 'prompt_group' ? 1 : 50
    const save = role === 'reference' ? setReferenceFiles : setFiles
    return {
      multiple: limit > 1,
      fileList: [],
      accept: 'image/png,image/jpeg,image/webp',
      showUploadList: false,
      disabled: uploading || analyzing || submitting,
      beforeUpload: async (file, batch) => {
        if (file !== batch[batch.length - 1] || uploadInProgress.current) return false
        if (batch.length > limit || (limit > 1 && existing.length + batch.length > limit)) {
          message.warning(`最多上传 ${limit} 张图片`)
          return false
        }
        uploadInProgress.current = true
        setUploading(true)
        try {
          const result = await uploadFiles([...batch].sort((a, b) => a.name.localeCompare(b.name, 'zh-CN', { numeric: true })))
          const next = (limit === 1 ? result.files : [...existing, ...result.files]).sort((a, b) => a.filename.localeCompare(b.filename, 'zh-CN', { numeric: true }))
          save(next)
          if (role === 'source') {
            setSelectedFile(next[0]?.file_id ?? null)
            setActiveBlockId(null)
            if (ocrEnabled && mode === 'shared') await analyze(result.files)
          }
        } catch (reason) { message.error(promptError(reason)) }
        finally { uploadInProgress.current = false; setUploading(false) }
        return false
      },
    }
  }

  const generate = async (kind: 'image' | 'video' = 'image') => {
    if (kind === 'video' && (!videoResolution || !videoRatio || !videoMode)) {
      message.warning('请先选择视频清晰度、比例和生成模式')
      return
    }
    if (!rightsConfirmed) {
      message.warning('请确认拥有素材使用权')
      return
    }
    if (!sourceIds.length || (mode !== 'prompt_group' && !ratios.length)) {
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
    if (mode === 'prompt_group' && (!selectedGroup || !groupTemplates.length || groupTemplates.some(template => !template) || groupError || library.error)) {
      message.warning('请选择非空且有效的提示词组，可刷新或前往提示词管理编辑')
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
        generation_kind: kind,
        ...(kind === 'video' ? { video_resolution: videoResolution, video_aspect_ratio: videoRatio, video_mode: videoMode, video_duration: videoDuration } : {}),
        source_ids: sourceIds,
        mode,
        prompt: mode === 'prompt_group' ? '' : mode === 'reference' ? referencePrompt : prompt,
        aspect_ratios: mode === 'prompt_group' ? ['original'] : ratios,
        prompt_group_id: mode === 'prompt_group' ? promptGroupId : undefined,
        reference_file_id: mode === 'reference' ? referenceId : undefined,
        ocr_enabled: isAdmin && ocrEnabled && mode === 'shared',
        per_source_overrides: mode === 'prompt_group' ? {} : overrides,
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
              <Tabs
                activeKey={mode}
                items={[
                  { key: 'shared', label: '多图共用提示词', disabled: uploading || analyzing || submitting },
                  { key: 'reference', label: '参考图组合', disabled: uploading || analyzing || submitting },
                  { key: 'prompt_group', label: '一图多提示词', disabled: uploading || analyzing || submitting },
                ]}
                onChange={(value) => {
                  setMode(value as 'shared' | 'reference' | 'prompt_group')
                  if (value !== 'shared') setOcrEnabled(false)
                  setSelectedFile(null)
                  setActiveBlockId(null)
                }}
              />
              <div className={mode === 'reference' ? 'workspace-reference-uploads' : undefined}>
                {mode === 'reference' && <WorkspaceUpload title="参考图" files={referenceFiles} limit={1} uploadProps={makeUploadProps('reference')} onRemove={() => setReferenceFiles([])} />}
                <WorkspaceUpload title={mode === 'shared' ? '上传图片' : '待处理图'} files={files} limit={mode === 'prompt_group' ? 1 : 50} uploadProps={makeUploadProps('source')} onRemove={removeFile} selectedId={currentFile?.file_id} onSelect={setSelectedFile} />
              </div>
              {ocrEnabled && mode === 'shared' && currentAnalysis && <Card className="panel-card" title="文字识别预览"><AnnotatedImage analysis={currentAnalysis} activeBlockId={activeBlockId} onSelect={block => setActiveBlockId(block.id)} /></Card>}
              <Card title={mode === 'prompt_group' ? '提示词组与生成设置' : '提示词与生成设置'} className="panel-card">
              {mode === 'prompt_group' ? (
                <Space direction="vertical" className="page-stack option-card">
                  <Typography.Text strong>提示词组</Typography.Text>
                  <Select aria-label="提示词组" value={promptGroupId} onChange={setPromptGroupId} loading={groupsLoading} placeholder="选择提示词组" options={promptGroups.map(group => ({ value: group.id, label: `${group.name}（${group.template_ids.length} 条）` }))} />
                  <Space wrap><Button loading={groupsLoading || library.loading} onClick={() => { void refreshGroups(); void library.refresh() }}>刷新提示词组</Button><Link to="/prompts">管理提示词组</Link></Space>
                  {(groupError || library.error) && <Alert type="error" message={groupError || library.error} />}
                  {selectedGroup && !groupTemplates.length && <Alert type="warning" message="该组为空，请先添加提示词模板" />}
                  {groupTemplates.map((template, index) => <Card size="small" key={selectedGroup!.template_ids[index]} title={`${index + 1}. ${template?.name ?? '模板已不可访问，请重新编辑组'}`}><Typography.Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }} ellipsis={{ rows: 3, expandable: true }}>{template?.content}</Typography.Paragraph></Card>)}
                  <Typography.Text type="secondary">每条提示词独立处理同一张原图，按组内顺序各生成一张原比例图片。</Typography.Text>
                </Space>
              ) : mode === 'shared' ? (
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
                {mode !== 'prompt_group' && <>
                <Typography.Text strong>输出比例（每种比例生成一张，独立处理）</Typography.Text>
                <Checkbox.Group
                  options={ratioOptions}
                  value={ratios}
                  onChange={(values) => setRatios(values.map(String))}
                />
                <Space>
                  <Switch
                    aria-label="保持自然比例"
                    checked={activePrompt.includes(naturalProportionsInstruction)}
                    onChange={(enabled) => togglePromptInstruction(naturalProportionsInstruction, enabled)}
                  />
                  <Typography.Text>保持自然比例</Typography.Text>
                </Space>
                <Space>
                  <Switch
                    aria-label="适配画布并保留完整主体"
                    checked={activePrompt.includes(canvasAdaptationInstruction)}
                    onChange={(enabled) => togglePromptInstruction(canvasAdaptationInstruction, enabled)}
                  />
                  <Typography.Text>适配画布并保留完整主体</Typography.Text>
                </Space>
                </>}
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
                  message={isAdmin ? `预计生成 ${imageCount} 张图片${ocrSteps ? `，另有 ${ocrSteps} 个文字编辑步骤` : ''}；成本请在经营总览按调用记录查看。` : `预计生成 ${imageCount} 张，需要 ${imageCount} 积分；可用 ${available ?? '加载中'}。成功扣费，最终失败或取消释放；文字识别免费。`}
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
              {mode === 'prompt_group' && <Space direction="vertical" className="page-stack" style={{ marginBottom: 20 }}>
                <Typography.Title level={5}>批量生视频设置</Typography.Title>
                <Alert type="info" message="使用上方上传的一张图片及所选提示词组，每条提示词生成一个视频。首尾帧模式将该图片作为首帧，仅支持 768P；1080P、2K 仅支持 16:9、9:16。取消只停止本地等待，上游可能继续生成并收费。" />
                <Space wrap>
                  <Select aria-label="视频清晰度" placeholder="选择清晰度" value={videoResolution} onChange={value => { setVideoResolution(value); if (value !== '768p' && videoRatio && !['16:9', '9:16'].includes(videoRatio)) setVideoRatio(undefined) }} style={{ width: 160 }} options={['768p', '1080p', '2k'].map(value => ({ value, label: value.toUpperCase(), disabled: videoMode === 'first_last_frame' && value !== '768p' }))} />
                  <Select aria-label="视频比例" placeholder="选择比例" value={videoRatio} onChange={setVideoRatio} style={{ width: 160 }} options={(videoResolution && videoResolution !== '768p' ? ['16:9', '9:16'] : ['16:9', '9:16', '1:1', '4:3', '3:4', '21:9']).map(value => ({ value, label: value }))} />
                  <Select aria-label="视频生成模式" placeholder="选择视频模式" value={videoMode} onChange={value => { setVideoMode(value); if (value === 'first_last_frame') setVideoResolution('768p') }} style={{ width: 190 }} options={[{ value: 'first_last_frame', label: '首尾帧模式' }, { value: 'omni_reference', label: '全能参考模式' }]} />
                  <Space>时长（秒）<InputNumber aria-label="视频时长" min={4} max={15} precision={0} value={videoDuration} onChange={value => setVideoDuration(value ?? 5)} /></Space>
                </Space>
              </Space>}
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
                  disabled={!files.length || (mode === 'prompt_group' && (!imageCount || groupsLoading || library.loading || !!groupError || !!library.error || groupTemplates.some(template => !template))) || uploading || analyzing || submitting || (!!task && !terminalStatuses.includes(task.status)) || (!isAdmin && (available === null || available < imageCount))}
                  onClick={() => void generate()}
                >
                  {mode === 'prompt_group' ? '提交批量生图任务' : '提交批量任务'}
                </Button>
                {mode === 'prompt_group' && <Button loading={submitting} disabled={!files.length || !imageCount || uploading || analyzing || submitting || groupsLoading || library.loading || !!groupError || !!library.error || groupTemplates.some(template => !template) || !videoResolution || !videoRatio || !videoMode} onClick={() => void generate('video')}>提交批量生视频</Button>}
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
                      !task?.jobs.some((job) => job.output_url && (job.step.startsWith('custom_') || job.step.startsWith('prompt_')))
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
      </Layout.Content>
    </Layout>
  )
}
