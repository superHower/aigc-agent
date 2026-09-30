import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  timeout: 120_000,
})

export type UploadedFile = {
  file_id: string
  filename: string
  url: string
  width: number
  height: number
  size: number
  content_type: string
}

export type TextBlock = {
  id: string
  bbox: [number, number, number, number]
  position: string
  original: string
  confidence: number | null
  mask_url: string
}

export type AnalysisFile = {
  file_id: string
  width: number
  height: number
  thumbnail_url: string | null
  text_blocks: TextBlock[]
  logo_blocks: unknown[]
  error: string | null
}

export type TaskJob = {
  id: string
  source_id: string
  step: string
  target_id: string | null
  status: string
  retry_count: number
  output_url: string | null
  error: string | null
}

export type Task = {
  id: string
  status: string
  total_jobs: number
  completed_jobs: number
  failed_jobs: number
  cancelled_jobs: number
  progress: number
  jobs: TaskJob[]
}

export async function uploadFiles(files: File[]) {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  return (await api.post<{ files: UploadedFile[] }>('/upload', form)).data
}

export async function analyzeFiles(fileIds: string[]) {
  return (await api.post<{ files: AnalysisFile[] }>('/analyze', { file_ids: fileIds })).data
}

export async function previewPrompt(payload: Record<string, string>) {
  return (await api.post<{ prompt: string }>('/prompt/preview', payload)).data
}

export async function generateBatch(payload: unknown) {
  return (await api.post<{ task_id: string }>('/generate/batch', payload)).data
}

export async function getTask(taskId: string) {
  return (await api.get<Task>(`/task/${taskId}`)).data
}
