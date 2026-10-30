import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Workspace } from './pages/Workspace'
import { Tasks } from './pages/Tasks'
import { TaskDetail } from './pages/TaskDetail'
import { Composite } from './pages/Composite'
import { Prompts } from './pages/Prompts'
import { Channels } from './pages/Channels'
import { lazy, Suspense } from 'react'
import { Spin } from 'antd'

const Dashboard = lazy(() =>
  import('./pages/Dashboard').then((module) => ({ default: module.Dashboard })),
)

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/"
          element={
            <Suspense fallback={<Spin fullscreen />}>
              <Dashboard />
            </Suspense>
          }
        />
        <Route path="/workspace" element={<Workspace />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/tasks/:id" element={<TaskDetail />} />
        <Route path="/composite" element={<Composite />} />
        <Route path="/prompts" element={<Prompts />} />
        <Route path="/channels" element={<Channels />} />
        <Route path="*" element={<Workspace />} />
      </Routes>
    </BrowserRouter>
  )
}
