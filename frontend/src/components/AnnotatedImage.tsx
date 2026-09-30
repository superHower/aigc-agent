import { Image } from 'antd'
import type { AnalysisFile, TextBlock } from '../api/client'

type Props = {
  analysis: AnalysisFile
  activeBlockId: string | null
  onSelect: (block: TextBlock) => void
}

export function AnnotatedImage({ analysis, activeBlockId, onSelect }: Props) {
  const imageUrl = analysis.thumbnail_url ?? `/api/files/${analysis.file_id}`
  return (
    <div className="annotated-image">
      <Image src={imageUrl} preview={{ src: `/api/files/${analysis.file_id}` }} />
      {analysis.text_blocks.map((block) => {
        const [x1, y1, x2, y2] = block.bbox
        const left = (x1 / analysis.width) * 100
        const top = (y1 / analysis.height) * 100
        const width = ((x2 - x1) / analysis.width) * 100
        const height = ((y2 - y1) / analysis.height) * 100
        return (
          <button
            key={block.id}
            className={`marker ${activeBlockId === block.id ? 'marker-active' : ''}`}
            style={{ left: `${left}%`, top: `${top}%`, width: `${width}%`, height: `${height}%` }}
            onClick={() => onSelect(block)}
            title={`${block.id}: ${block.original}`}
          >
            <span>{block.id}</span>
          </button>
        )
      })}
    </div>
  )
}
