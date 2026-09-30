import { useMemo, useState } from 'react'
import { Alert, Button, Card, Checkbox, Col, Collapse, Input, Layout, Progress, Row, Select, Space, Tag, Typography, Upload, message } from 'antd'
import { InboxOutlined, PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import { analyzeFiles, generateBatch, previewPrompt, uploadFiles, type AnalysisFile, type TextBlock } from '../api/client'
import { AnnotatedImage } from '../components/AnnotatedImage'
import { TextBlockTable } from '../components/TextBlockTable'
import { useTaskProgress } from '../hooks/useTaskProgress'

const { Dragger } = Upload

export function Workspace() {
  const [analysis, setAnalysis] = useState<AnalysisFile[]>([])
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [activeBlockId, setActiveBlockId] = useState<string | null>(null)
  const [replacements, setReplacements] = useState<Record<string, { replace: string; enabled: boolean }>>({})
  const [brand, setBrand] = useState('')
  const [strategy, setStrategy] = useState<'serial'>('serial')
  const [quality, setQuality] = useState('high')
  const [promptPreview, setPromptPreview] = useState('')
  const [taskId, setTaskId] = useState<string | null>(null)
  const [rightsConfirmed, setRightsConfirmed] = useState(false)
  const [uploading, setUploading] = useState(false)
  const { task, error: taskError } = useTaskProgress(taskId)
  const current = analysis.find((item) => item.file_id === selectedFile) ?? analysis[0]

  const uploadProps: UploadProps = {
    multiple: true,
    maxCount: 5,
    accept: 'image/png,image/jpeg,image/webp',
    showUploadList: false,
    disabled: uploading,
    beforeUpload: async (file, fileList) => {
      if (file !== fileList[fileList.length - 1]) return false
      setUploading(true)
      try {
        const files = fileList.slice(0, 5) as unknown as File[]
        const uploaded = await uploadFiles(files)
        const analyzed = await analyzeFiles(uploaded.files.map((file) => file.file_id))
        setAnalysis(analyzed.files)
        setSelectedFile(analyzed.files[0]?.file_id ?? null)
        message.success(`已分析 ${analyzed.files.length} 张图片`)
      } catch (reason) {
        message.error(reason instanceof Error ? reason.message : '上传或分析失败')
      } finally {
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
    const block = allBlocks.find((item) => item.id === activeBlockId) ?? allBlocks[0]
    const replacement = block ? replacements[block.id]?.replace : ''
    if (!block || !replacement) {
      message.warning('请先选择文字块并填写替换文案')
      return
    }
    const result = await previewPrompt({ prompt_type: 'text', original: block.original, replace: replacement, position: block.position })
    setPromptPreview(result.prompt)
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
      const result = await generateBatch({ source_ids: analysis.map((item) => item.file_id), edit_rule: { strategy, quality }, per_source_overrides: overrides })
      setTaskId(result.task_id)
      message.success('批量任务已提交')
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '任务提交失败')
    }
  }

  return (
    <Layout className="app-shell">
      <Layout.Header className="app-header"><div className="brand-mark">ECOM IMAGE STUDIO</div><Tag color="green">WORKSPACE</Tag></Layout.Header>
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
              <Collapse className="prompt-collapse" items={[{ key: 'prompt', label: 'Prompt 预览', children: <Typography.Text copyable={{ text: promptPreview }}>{promptPreview || '点击下方按钮生成预览'}</Typography.Text> }]} />
              <Space wrap><Button icon={<ReloadOutlined />} onClick={() => void handlePreview()}>预览文字 Prompt</Button><Checkbox checked={rightsConfirmed} onChange={(event) => setRightsConfirmed(event.target.checked)}>我确认拥有该素材使用权</Checkbox><Button type="primary" icon={<PlayCircleOutlined />} disabled={!analysis.length} onClick={() => void handleGenerate()}>开始批量生成</Button></Space>
            </Card>
            {taskId && <Card title="4. 任务进度" className="panel-card"><Progress percent={Math.round((task?.progress ?? 0) * 100)} status={task?.status === 'failed' ? 'exception' : task?.status === 'completed' ? 'success' : 'active'} /><Space><Tag color="blue">{task?.status ?? 'queued'}</Tag><Typography.Text>{task?.completed_jobs ?? 0} / {task?.total_jobs ?? 0} 已完成</Typography.Text></Space>{taskError && <Alert type="error" message={taskError} />}</Card>}
          </Col>
        </Row>
      </Layout.Content>
    </Layout>
  )
}
