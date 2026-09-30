import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Workspace } from './pages/Workspace'
import { Tasks } from './pages/Tasks'
import { TaskDetail } from './pages/TaskDetail'
import { Composite } from './pages/Composite'

export function App() {
  return <BrowserRouter><Routes>
    <Route path="/" element={<Workspace />} />
    <Route path="/tasks" element={<Tasks />} />
    <Route path="/tasks/:id" element={<TaskDetail />} />
    <Route path="/composite" element={<Composite />} />
    <Route path="*" element={<Workspace />} />
  </Routes></BrowserRouter>
}
