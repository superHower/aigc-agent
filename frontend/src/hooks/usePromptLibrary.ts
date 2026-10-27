import { useCallback, useEffect, useRef, useState } from 'react'
import { listPromptCategories, listPromptTemplates, promptError, type PromptCategory, type PromptTemplate } from '../api/client'

export function usePromptLibrary() {
  const [categories, setCategories] = useState<PromptCategory[]>([])
  const [templates, setTemplates] = useState<PromptTemplate[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const request = useRef(0)
  const refresh = useCallback(async () => {
    const current = ++request.current
    setLoading(true)
    try {
      const [nextCategories, nextTemplates] = await Promise.all([listPromptCategories(), listPromptTemplates()])
      if (current !== request.current) return
      setCategories(nextCategories)
      setTemplates(nextTemplates)
      setError('')
    } catch (reason) { if (current === request.current) setError(promptError(reason)) }
    finally { if (current === request.current) setLoading(false) }
  }, [])
  useEffect(() => { void refresh(); return () => { request.current++ } }, [refresh])
  return { categories, templates, loading, error, refresh }
}

export function filterTemplates(templates: PromptTemplate[], category: string, query: string) {
  const keyword = query.trim().toLocaleLowerCase()
  return templates.filter((item) => (category === 'all' || (category === 'uncategorized' ? item.category_id === null : item.category_id === category)) && `${item.name}\n${item.content}`.toLocaleLowerCase().includes(keyword))
}

export function categoryOptions(categories: PromptCategory[]) {
  return [{ value: 'all', label: '全部分类' }, { value: 'uncategorized', label: '未分类' }, ...categories.map((item) => ({ value: item.id, label: item.name }))]
}
