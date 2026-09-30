import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Workspace } from './pages/Workspace'

export function App() {
  return <BrowserRouter><Routes><Route path="*" element={<Workspace />} /></Routes></BrowserRouter>
}
