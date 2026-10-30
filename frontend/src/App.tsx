import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Workspace } from './pages/Workspace'
import { Tasks } from './pages/Tasks'
import { TaskDetail } from './pages/TaskDetail'
import { Composite } from './pages/Composite'
import { Prompts } from './pages/Prompts'
import { Channels } from './pages/Channels'
import { lazy, Suspense } from 'react'
import { Spin } from 'antd'
import { Login } from './pages/Login'
import { PhoneAuth } from './pages/PhoneAuth'
import { Credits } from './pages/Credits'
import { AuthProvider, RequireAuth } from './components/AuthProvider'

const Dashboard = lazy(() =>
  import('./pages/Dashboard').then((module) => ({ default: module.Dashboard })),
)

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<PhoneAuth />} />
        <Route path="/forgot-password" element={<PhoneAuth reset />} />
        <Route element={<RequireAuth />}>
        <Route
          path="/"
          element={
            <Suspense fallback={<Spin fullscreen />}>
              <Dashboard />
            </Suspense>
          }
        />
        <Route path="/workspace" element={<Workspace />} />
        <Route path="/account/credits" element={<Credits />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/tasks/:id" element={<TaskDetail />} />
        <Route path="/composite" element={<Composite />} />
        <Route path="/prompts" element={<Prompts />} />
        <Route element={<RequireAuth admin />}><Route path="/channels" element={<Channels />} /></Route>
        <Route path="*" element={<Workspace />} />
        </Route>
      </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
