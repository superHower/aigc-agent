import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { Alert, Spin } from 'antd'
import { api } from '../api/client'

type User = { id: string; username: string; role: 'admin' | 'user' }
const AuthContext = createContext<{ user: User | null; loading: boolean; error: boolean }>({ user: null, loading: true, error: false })
export const useAuth = () => useContext(AuthContext)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  useEffect(() => {
    api.get<User>('/auth/me').then((response) => setUser(response.data)).catch((reason) => {
      if (reason.response?.status !== 401) setError(true)
    }).finally(() => setLoading(false))
  }, [])
  return <AuthContext.Provider value={{ user, loading, error }}>{children}</AuthContext.Provider>
}

export function RequireAuth({ admin = false }: { admin?: boolean }) {
  const { user, loading, error } = useAuth()
  if (loading) return <Spin fullscreen />
  if (error) return <Alert type="error" message="服务暂不可用，请刷新后重试" />
  if (!user) return <Navigate to="/login" replace />
  if (admin && user.role !== 'admin') return <Navigate to="/" replace />
  return <Outlet />
}
