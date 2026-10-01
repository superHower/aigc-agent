import { useMemo, useRef, useState } from 'react'
import { Alert, Button, Card, Checkbox, Col, Collapse, Input, InputNumber, Layout, Progress, Row, Select, Space, Switch, Tag, Typography, Upload, message } from 'antd'
import { InboxOutlined, PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import type { UploadProps } from 'antd'
import { analyzeFiles, generateBatch, previewPrompt, uploadFiles, type AnalysisFile, type TextBlock } from '../api/client'
import { AnnotatedImage } from '../components/AnnotatedImage'
import { TextBlockTable } from '../components/TextBlockTable'
import { useTaskProgress } from '../hooks/useTaskProgress'
import { AppHeader } from '../components/AppHeader'

const { Dragger } = Upload

export function Workspace() {
  const [analysis, setAnalysis] = useState<AnalysisFile[]>([])
  const [uploadedFiles, setUploadedFiles] = useState<Awaited<ReturnType<typeof uploadFiles>>['files']>([])
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [activeBlockId, setActiveBlockId] = useState<string | null>(null)
  const [replacements, setReplacements] = useState<Record<string, { replace: string; enabled: boolean }>>({})
  const [brand, setBrand] = useState('')
  const [logoEnabled, setLogoEnabled] = useState(false)
  const [logoReferenceId, setLogoReferenceId] = useState('')
  const [logoBrand, setLogoBrand] = useState('')
  const [referenceIds, setReferenceIds] = useState<string[]>([])
  const [customPrompt, setCustomPrompt] = useState('')
  const [generationCount, setGenerationCount] = useState(1)
  const [strategy, setStrategy] = useState<'serial'>('serial')
  const [quality, setQuality] = useState('high')
  const [promptPreviews, setPromptPreviews] = useState<Record<string, string>>({})
  const [taskId, setTaskId] = useState<string | null>(null)
  const [rightsConfirmed, setRightsConfirmed] = useState(false)
  const [uploading, setUploading] = useState(false)
  const uploadInProgress = useRef(false)
  const { task, error: taskError } = useTaskProgress(taskId)
  const current = analysis.find((item) => item.file_id === selectedFile) ?? analysis[0]

  const uploadProps: UploadProps = {
    multiple: true,
    fileList: [],
    accept: 'image/png,image/jpeg,image/webp',
    showUploadList: false,
    disabled: uploading,
    beforeUpload: async (file, fileList) => {
      if (file !== fileList[fileList.length - 1]) return false
      if (uploadInProgress.current) return false
      const remaining = 5 - uploadedFiles.length
      if (remaining <= 0) {
        message.warning('最多上传 5 张图片，已有图片会保留')
        return false
      }
      if (fileList.length > remaining) {
        message.warning(`还可上传 ${remaining} 张图片，本次仅上传前 ${remaining} 张`)
      }
      uploadInProgress.current = true
      setUploading(true)
      try {
        const files = fileList.slice(0, remaining) as unknown as File[]
        const uploaded = await uploadFiles(files)
        setUploadedFiles((previous) => [...previous, ...uploaded.files])
        setSelectedFile((previous) => previous ?? uploaded.files[0]?.file_id ?? null)
        const analyzed = await analyzeFiles(uploaded.files.map((file) => file.file_id))
        setAnalysis((previous) => [...previous, ...analyzed.files])
        message.success(`已分析 ${analyzed.files.length} 张图片`)
      } catch (reason) {
        message.error(reason instanceof Error ? reason.message : '上传或分析失败')
      } finally {
        uploadInProgress.current = false
        setUploading(false)
      }
      return false
    },
  }

  const allBlocks = useMemo(() => analysis.flatMap((item) => item.text_blocks), [analysis])
  const updateReplacement = (id: string, value: { replace: string; enabled: boolean }) => {
    setReplacements((currentValue) => ({ ...currentValue, [id]: value }))
  }

  const handlePreview = async () => {
    const previewBlocks = allBlocks.filter((block) => replacements[block.id]?.replace?.trim())
    if (!previewBlocks.length) {
      message.warning('请至少填写一个文字块的替换文案')
      return
    }
    try {
      const results = await Promise.all(previewBlocks.map(async (block) => {
        const result = await previewPrompt({ prompt_type: 'text', original: block.original, replace: replacements[block.id].replace, position: block.position })
        return [block.id, result.prompt] as const
      }))
      setPromptPreviews(Object.fromEntries(results))
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '提示词预览失败')
    }
  }

  const handleGenerate = async () => {
    if (!rightsConfirmed) {
      message.warning('请确认拥有素材使用权')
      return
    }
    const overrides: Record<string, { text_blocks: { id: string; replace: string; enabled: boolean }[] }> = {}
    analysis.forEach((item) => {
      overrides[item.file_id] = { text_blocks: item.text_blocks.map((block) => ({ id: block.id, ...(replacements[block.id] ?? { replace: '', enabled: true }) })) }
    })
    try {
      const result = await generateBatch({
        source_ids: analysis.map((item) => item.file_id),
        edit_rule: {
          strategy, quality, logo_replace_enabled: logoEnabled, logo_reference_file_id: logoReferenceId,
          logo_brand: logoBrand, custom_prompt: customPrompt, reference_file_ids: referenceIds, generation_count: generationCount,
        },
        per_source_overrides: overrides,
      })
      setTaskId(result.task_id)
      message.success('批量任务已提交')
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '任务提交失败')
    }
  }

  return (
    <Layout className="app-shell">
      <AppHeader />
      <Layout.Content className="workspace-content">
        <Row gutter={[18, 18]}>
          <Col xs={24} lg={9}>
            <Card title="1. 上传参考图" className="panel-card">
              <Dragger {...uploadProps}>
                <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                <p className="ant-upload-text">{uploading ? '正在上传并分析…' : '拖入 1–5 张参考图'}</p>
                <p className="ant-upload-hint">支持 PNG、JPG、WebP；上传后自动 OCR</p>
              </Dragger>
              <Space wrap className="file-tabs">
                {analysis.map((item, index) => <Button key={item.file_id} type={item.file_id === selectedFile ? 'primary' : 'default'} onClick={() => setSelectedFile(item.file_id)}>图片 {index + 1}</Button>)}
              </Space>
              {uploadedFiles.length > 0 && <div className="uploaded-grid">{uploadedFiles.map((file, index) => <div className={`uploaded-item ${file.file_id === selectedFile ? 'uploaded-item-active' : ''}`} key={file.file_id} onClick={() => setSelectedFile(file.file_id)}><img src={file.url} alt={file.filename} /><span>图片 {index + 1}</span></div>)}</div>}
              {current && <AnnotatedImage analysis={current} activeBlockId={activeBlockId} onSelect={(block) => setActiveBlockId(block.id)} />}
            </Card>
          </Col>
          <Col xs={24} lg={15}>
            <Card title="2. 文字块编辑" className="panel-card" extra={current ? <Tag>{current.text_blocks.length} 个文字块</Tag> : null}>
              {current ? <TextBlockTable blocks={current.text_blocks} replacements={replacements} activeId={activeBlockId} onHover={setActiveBlockId} onChange={updateReplacement} /> : <Typography.Paragraph type="secondary">上传图片后，这里会显示 OCR 检测到的文字块。</Typography.Paragraph>}
            </Card>
            <Card title="3. 生成规则" className="panel-card">
              <Row gutter={12}>
                <Col span={12}><Typography.Text>品牌/Logo 文案</Typography.Text><Input value={brand} onChange={(event) => setBrand(event.target.value)} placeholder="例如 STRYVAN" /></Col>
                <Col span={6}><Typography.Text>策略</Typography.Text><Select value={strategy} options={[{ value: 'serial', label: '串行精修' }]} /></Col>
                <Col span={6}><Typography.Text>质量</Typography.Text><Select value={quality} onChange={setQuality} options={['low', 'medium', 'high', 'xhigh', 'max'].map((value) => ({ value, label: value }))} /></Col>
              </Row>
              <Card size="small" title="Logo 替换（可选）" className="option-card"><Space wrap><Switch checked={logoEnabled} onChange={setLogoEnabled} /><span>仅在 OCR 检测到 Logo 时替换</span><Input value={logoBrand} onChange={(event) => setLogoBrand(event.target.value)} placeholder="Logo 文案，例如 STRYVAN" disabled={!logoEnabled} style={{ width: 220 }} /><Select value={logoReferenceId || undefined} onChange={setLogoReferenceId} placeholder="选择 Logo 参考图" disabled={!logoEnabled} options={uploadedFiles.map((file) => ({ value: file.file_id, label: file.filename }))} style={{ width: 220 }} /></Space></Card>
              <Card size="small" title="参考图与自定义提示词" className="option-card"><Select mode="multiple" value={referenceIds} onChange={setReferenceIds} placeholder="选择要提供给模型的参考图（可多选）" options={uploadedFiles.map((file) => ({ value: file.file_id, label: file.filename }))} style={{ width: '100%' }} maxTagCount="responsive" /><Input.TextArea value={customPrompt} onChange={(event) => setCustomPrompt(event.target.value)} placeholder="可选，例如：结合图片一的背景、图片二的灯具样式生成新的电商图片。" autoSize={{ minRows: 3, maxRows: 7 }} /></Card>
              <Space className="option-row"><Typography.Text>生成张数</Typography.Text><InputNumber min={1} max={4} value={generationCount} onChange={(value) => setGenerationCount(value ?? 1)} /><Typography.Text type="secondary">自定义提示词会按此数量生成独立结果</Typography.Text></Space>
              <Collapse className="prompt-collapse" items={[{ key: 'prompt', label: '中文提示词预览', children: <Space direction="vertical" className="prompt-list">{allBlocks.filter((block) => replacements[block.id]?.replace?.trim()).map((block) => <Card size="small" key={block.id} title={`${block.id}：${block.original} → ${replacements[block.id].replace}`}><Typography.Text copyable={{ text: promptPreviews[block.id] }}>{promptPreviews[block.id] || '点击“预览全部提示词”生成'}</Typography.Text></Card>)}{customPrompt.trim() && <Card size="small" title="自定义提示词"><Typography.Text copyable={{ text: customPrompt }}>{customPrompt}</Typography.Text></Card>}{!allBlocks.some((block) => replacements[block.id]?.replace?.trim()) && !customPrompt.trim() && <Typography.Text type="secondary">填写文字替换或自定义提示词后，这里会显示对应内容。</Typography.Text>}</Space> }]} />
              <Space wrap><Button icon={<ReloadOutlined />} onClick={() => void handlePreview()}>预览全部提示词</Button><Checkbox checked={rightsConfirmed} onChange={(event) => setRightsConfirmed(event.target.checked)}>我确认拥有素材使用权</Checkbox><Button type="primary" icon={<PlayCircleOutlined />} disabled={!analysis.length} onClick={() => void handleGenerate()}>开始批量生成</Button></Space>
            </Card>
            {taskId && <Card title="4. 任务进度" className="panel-card"><Progress percent={Math.round((task?.progress ?? 0) * 100)} status={task?.status === 'failed' ? 'exception' : task?.status === 'completed' ? 'success' : 'active'} /><Space><Tag color="blue">{task?.status ?? 'queued'}</Tag><Typography.Text>{task?.completed_jobs ?? 0} / {task?.total_jobs ?? 0} 已完成</Typography.Text></Space>{taskError && <Alert type="error" message={taskError} />}{task?.jobs.some((job) => job.output_url) && <div className="generated-results"><Typography.Title level={5}>已生成图片</Typography.Title><div className="result-grid">{task.jobs.filter((job) => job.output_url).map((job) => <div className="result-card" key={job.id}><img src={job.output_url ?? ''} alt={job.step} /><Typography.Text ellipsis>{job.step}</Typography.Text><a href={job.output_url ?? ''} download>下载图片</a></div>)}</div><Link to={`/tasks/${task.id}`}><Button>查看任务详情</Button></Link></div>}</Card>}
          </Col>
        </Row>
      </Layout.Content>
    </Layout>
  )
}
