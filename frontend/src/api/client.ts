import axios from 'axios'

export const api = axios.create({ baseURL: '/api', timeout: 120_000 })
api.interceptors.request.use((config) => {
  if (!['get', 'head', 'options'].includes(config.method ?? 'get')) {
    const csrf = document.cookie.split('; ').find((item) => item.startsWith('csrf='))?.slice(5)
    if (csrf) config.headers.set('X-CSRF-Token', decodeURIComponent(csrf))
  }
  return config
})
api.interceptors.response.use((response) => response, (error) => {
  if (error.response?.status === 401 && !['/login', '/register', '/forgot-password'].includes(window.location.pathname)) window.location.assign('/login')
  return Promise.reject(error)
})

export type DashboardSummary = {
  tasks: number; images: number; done: number; failed: number; cancelled: number
  active: number; active_tasks: number; retried_tasks: number; steps: number
  success_rate: number | null; estimated_cost: number
}
export type DashboardData = {
  period: 'day' | 'week' | 'month'; start_date: string; end_date: string
  previous_start_date: string; previous_end_date: string; updated_at: string
  summary: DashboardSummary; previous: DashboardSummary
  trend: { label: string; tasks: number; done: number; failed: number; active: number }[]
  task_statuses: Record<string, number>
  channels: { name: string; total: number; done: number; failed: number }[]
  recent_tasks: { id: string; status: string; created_at: string; images: number; done: number; failed: number; auto_retry_count: number }[]
}
export async function getDashboard(period: DashboardData['period'], date: string, offset: number, signal?: AbortSignal) {
  return (await api.get<DashboardData>('/dashboard', { params: { period, selected_date: date, timezone_offset: offset }, signal })).data
}

export type Channel = { id: string; name: string; model: string; base_url: string; remark: string; concurrency: number; timeout: number; enabled: boolean; has_api_key: boolean; last_error: string | null }
export type ChannelInput = Omit<Channel, 'id' | 'has_api_key' | 'last_error'> & { api_key: string }
export async function listChannels() { return (await api.get<{ items: Channel[] }>('/channels')).data.items }
export async function saveChannel(payload: ChannelInput, id?: string) { return (await (id ? api.put(`/channels/${id}`, payload) : api.post('/channels', payload))).data }
export async function deleteChannel(id: string) { await api.delete(`/channels/${id}`) }
export async function resetChannel(id: string) { await api.post(`/channels/${id}/reset`) }

export type PromptCategory = { id: string; name: string; created_at: string }
export type PromptTemplate = { id: string; name: string; content: string; category_id: string | null; created_at: string; updated_at: string }
export type PromptTemplateInput = Pick<PromptTemplate, 'name' | 'content' | 'category_id'>
export async function listPromptCategories() { return (await api.get<{ items: PromptCategory[] }>('/prompt-categories')).data.items }
export async function savePromptCategory(name: string, id?: string) { return (await (id ? api.put<PromptCategory>(`/prompt-categories/${id}`, { name }) : api.post<PromptCategory>('/prompt-categories', { name }))).data }
export async function deletePromptCategory(id: string) { await api.delete(`/prompt-categories/${id}`) }
export async function listPromptTemplates() { return (await api.get<{ items: PromptTemplate[] }>('/prompt-templates')).data.items }
export async function savePromptTemplate(payload: PromptTemplateInput, id?: string) { return (await (id ? api.put<PromptTemplate>(`/prompt-templates/${id}`, payload) : api.post<PromptTemplate>('/prompt-templates', payload))).data }
export async function deletePromptTemplate(id: string) { await api.delete(`/prompt-templates/${id}`) }
export function promptError(reason: unknown) {
  if (axios.isAxiosError(reason) && typeof reason.response?.data?.detail === 'string') return reason.response.data.detail
  return '操作失败，请稍后重试'
}

export type UploadedFile = { file_id: string; filename: string; url: string; width: number; height: number; size: number; content_type: string }
export type TextBlock = { id: string; bbox: [number, number, number, number]; position: string; original: string; confidence: number | null; mask_url: string }
export type AnalysisFile = { file_id: string; width: number; height: number; thumbnail_url: string | null; text_blocks: TextBlock[]; logo_blocks: unknown[]; error: string | null }
export type TaskJob = { channel_name?: string | null; id: string; task_id: string; source_id: string; step: string; target_id: string | null; status: string; retry_count: number; cancel_requested: boolean; output_url: string | null; output_filename?: string | null; error: string | null; created_at?: string; updated_at?: string }
export type Task = { auto_retry_count?: number; auto_retry_limit?: number; id: string; status: string; created_at?: string; updated_at?: string; total_jobs: number; completed_jobs: number; failed_jobs: number; cancelled_jobs: number; progress: number; estimated_cost?: number; max_concurrency?: number; sources?: { source_id: string; status: string; total_jobs: number; completed_jobs: number }[]; jobs: TaskJob[]; error?: string | null }

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
