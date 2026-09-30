import { useEffect, useState } from 'react'
import { getTask, type Task } from '../api/client'

export function useTaskProgress(taskId: string | null) {
  const [task, setTask] = useState<Task | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!taskId) {
      setTask(null)
      return
    }
    let active = true
    let timer: number | undefined
    const poll = async () => {
      try {
        const next = await getTask(taskId)
        if (!active) return
        setTask(next)
        if (!['completed', 'partial_failed', 'failed', 'cancelled'].includes(next.status)) {
          timer = window.setTimeout(poll, 2500)
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : '任务查询失败')
      }
    }
    void poll()
    return () => {
      active = false
      if (timer) window.clearTimeout(timer)
    }
  }, [taskId])

  return { task, error }
}
