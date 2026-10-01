import axios from 'axios'

export const api = axios.create({ baseURL: '/api', timeout: 120_000 })

export type UploadedFile = { file_id: string; filename: string; url: string; width: number; height: number; size: number; content_type: string }
export type TextBlock = { id: string; bbox: [number, number, number, number]; position: string; original: string; confidence: number | null; mask_url: string }
export type AnalysisFile = { file_id: string; width: number; height: number; thumbnail_url: string | null; text_blocks: TextBlock[]; logo_blocks: unknown[]; error: string | null }
export type TaskJob = { id: string; task_id: string; source_id: string; step: string; target_id: string | null; status: string; retry_count: number; cancel_requested: boolean; output_url: string | null; output_filename?: string | null; error: string | null; created_at?: string; updated_at?: string }
export type Task = { id: string; status: string; created_at?: string; updated_at?: string; total_jobs: number; completed_jobs: number; failed_jobs: number; cancelled_jobs: number; progress: number; estimated_cost?: number; max_concurrency?: number; sources?: { source_id: string; status: string; total_jobs: number; completed_jobs: number }[]; jobs: TaskJob[]; error?: string | null }

export async function uploadFiles(files: File[]) { const form = new FormData(); files.forEach((file) => form.append('files', file)); return (await api.post<{ files: UploadedFile[] }>('/upload', form)).data }
export async function analyzeFiles(fileIds: string[]) { return (await api.post<{ files: AnalysisFile[] }>('/analyze', { file_ids: fileIds })).data }
export async function previewPrompt(payload: Record<string, string>) { return (await api.post<{ prompt: string }>('/prompt/preview', payload)).data }
export async function generateBatch(payload: { source_ids: string[]; edit_rule: Record<string, unknown>; per_source_overrides: Record<string, unknown> }) { return (await api.post<{ task_id: string }>('/generate/batch', payload)).data }
export async function getTask(taskId: string) { return (await api.get<Task>(`/task/${taskId}`)).data }
export async function generateMultiImage(payload: Record<string, unknown>) { return (await api.post<{ task_id: string; total_jobs: number; estimated_cost: number }>('/generate/multi-image', payload)).data }
export async function listTasks() { return (await api.get<{ items: Task[] }>('/tasks')).data }
export async function cancelTask(taskId: string) { return (await api.post(`/task/${taskId}/cancel`)).data }
export async function retryTask(taskId: string, jobId?: string) { return (await api.post(`/task/${taskId}/retry`, jobId ? { job_id: jobId } : {})).data }
export async function compositeImages(payload: { image_ids: string[]; width: number; gap: number; background_color: string; padding_top: number; padding_bottom: number }) { return (await api.post<{ file_id: string; url: string; width: number; height: number; image_count: number }>('/composite', payload)).data }
