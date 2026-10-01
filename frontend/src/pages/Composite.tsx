import { useState } from 'react'
import { Button, Card, ColorPicker, Empty, InputNumber, List, Space, Upload, message } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { compositeImages, uploadFiles, type UploadedFile } from '../api/client'
import { AppHeader } from '../components/AppHeader'

export function Composite() {
  const [files, setFiles] = useState<UploadedFile[]>([]); const [result, setResult] = useState<{ url: string; width: number; height: number } | null>(null)
  const [width, setWidth] = useState(750); const [gap, setGap] = useState(0); const [paddingTop, setPaddingTop] = useState(0); const [paddingBottom, setPaddingBottom] = useState(0); const [color, setColor] = useState('#FFFFFF'); const [loading, setLoading] = useState(false)
  const props = { multiple: true, accept: 'image/png,image/jpeg,image/webp', showUploadList: false, beforeUpload: async (_: unknown, list: unknown[]) => { if (_ !== list[list.length - 1]) return false; try { const uploaded = await uploadFiles((list as File[]).slice(0, 50)); setFiles((previous) => [...previous, ...uploaded.files]); setResult(null) } catch (reason) { message.error(reason instanceof Error ? reason.message : '上传失败') } return false } }
  const move = (index: number, direction: number) => { const next = [...files]; const target = index + direction; if (target < 0 || target >= next.length) return; [next[index], next[target]] = [next[target], next[index]]; setFiles(next) }
  const compose = async () => { if (!files.length) return message.warning('请先上传图片'); setLoading(true); try { setResult(await compositeImages({ image_ids: files.map((file) => file.file_id), width, gap, background_color: color, padding_top: paddingTop, padding_bottom: paddingBottom })) } catch (reason) { message.error(reason instanceof Error ? reason.message : '拼接失败') } finally { setLoading(false) } }
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Card title="长图拼接" extra={<Link to="/"><Button>返回工作台</Button></Link>}><Space direction="vertical" size="large" className="page-stack">
    <Upload {...props}><Button icon={<UploadOutlined />}>上传成品图</Button></Upload>
    {files.length ? <List bordered dataSource={files} renderItem={(file, index) => <List.Item actions={[<Button key="up" size="small" onClick={() => move(index, -1)}>上移</Button>, <Button key="down" size="small" onClick={() => move(index, 1)}>下移</Button>]}><List.Item.Meta avatar={<img className="thumb" src={file.url} />} title={`${index + 1}. ${file.filename}`} description={`${file.width} × ${file.height}`} /></List.Item>} /> : <Empty description="请上传 1–5 张成品图" />}
    <Space wrap><label>宽度 <InputNumber min={1} value={width} onChange={(value) => setWidth(value ?? 750)} /></label><label>间距 <InputNumber min={0} value={gap} onChange={(value) => setGap(value ?? 0)} /></label><label>顶部留白 <InputNumber min={0} value={paddingTop} onChange={(value) => setPaddingTop(value ?? 0)} /></label><label>底部留白 <InputNumber min={0} value={paddingBottom} onChange={(value) => setPaddingBottom(value ?? 0)} /></label><label>背景色 <ColorPicker value={color} onChange={(_, hex) => setColor(hex)} /></label><Button type="primary" loading={loading} onClick={() => void compose()}>生成长图</Button></Space>
    {result && <Card title={`生成结果 · ${result.width} × ${result.height}`}><img className="composite-preview" src={result.url} /><br /><a href={result.url} download>下载长图</a></Card>}
  </Space></Card></main></div>
}
