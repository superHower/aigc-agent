import { Button, Card, Image, Popconfirm, Upload } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import type { UploadedFile } from '../api/client'

export function WorkspaceUpload({ title, files, limit, uploadProps, onRemove, onSelect, selectedId }: {
  title: string; files: UploadedFile[]; limit: number; uploadProps: UploadProps;
  onRemove: (id: string) => void; onSelect?: (id: string) => void; selectedId?: string;
}) {
  return <Card title={title} className="panel-card workspace-upload" extra={`${files.length} / ${limit}`}>
    <Upload.Dragger {...uploadProps} aria-label={`${title}上传区`}>
      <p className="ant-upload-drag-icon"><InboxOutlined /></p>
      <p className="ant-upload-text">{limit === 1 && files.length ? '点击或拖入图片以替换' : `拖入或选择图片，最多 ${limit} 张`}</p>
      <p className="ant-upload-hint">PNG、JPG、WebP{limit > 1 ? ' · 按文件名自然排序' : ''}</p>
    </Upload.Dragger>
    <div className={limit === 1 ? 'workspace-single-image' : 'workspace-upload-grid'}>
      {files.map(file => <div className={`uploaded-item-wrap${selectedId === file.file_id ? ' uploaded-item-active' : ''}`} key={file.file_id}>
        <Image src={file.url} alt={file.filename} />
        <button type="button" className="workspace-upload-filename" onClick={() => onSelect?.(file.file_id)} title={file.filename}>{file.filename}</button>
        <Popconfirm title="移除这张图片？" description="只从当前模式移除，服务器原文件会保留。" onConfirm={() => onRemove(file.file_id)} okText="移除" cancelText="取消" disabled={uploadProps.disabled}>
          <Button className="uploaded-item-remove" type="text" danger disabled={uploadProps.disabled} aria-label={`移除${title}：${file.filename}`}>×</Button>
        </Popconfirm>
      </div>)}
    </div>
  </Card>
}
