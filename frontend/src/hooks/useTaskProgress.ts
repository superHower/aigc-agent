import { useEffect, useState } from 'react'
import { getTask, type Task } from '../api/client'

export function useTaskProgress(taskId: string | null) {
  const [task, setTask] = useState<Task | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshVersion, setRefreshVersion] = useState(0)

  useEffect(() => {
    setTask(null)
    setError(null)
    if (!taskId) {
      return
    }
    let active = true
    let timer: number | undefined
    const poll = async () => {
      try {
        const next = await getTask(taskId)
        if (!active) return
        setTask(next)
        setError(null)
        if (!['completed', 'partial_failed', 'failed', 'cancelled'].includes(next.status)) {
          timer = window.setTimeout(poll, 2500)
        }
      } catch (reason) {
        if (active) {
          const status = getStatus(reason)
          if (status === 404) {
            sessionStorage.removeItem('workspace-task-id')
            setTask(null)
            setError('任务不存在，可能是任务数据库已清空。请重新提交任务。')
            return
          }
          if (status === 503) {
            setError('任务数据库尚未初始化，请重启后端服务。')
            return
          }
          setError(reason instanceof Error ? reason.message : '任务查询失败')
          timer = window.setTimeout(poll, 2500)
        }
      }
    }
    void poll()
    return () => {
      active = false
      if (timer) window.clearTimeout(timer)
    }
  }, [taskId, refreshVersion])

  return { task, error, refresh: () => setRefreshVersion((version) => version + 1) }
}

function getStatus(reason: unknown): number | undefined {
  if (typeof reason === 'object' && reason !== null && 'response' in reason) {
    return (reason as { response?: { status?: number } }).response?.status
  }
  return undefined
}
