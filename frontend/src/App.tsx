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
import { Membership } from './pages/Membership'
import { Packages } from './pages/Packages'
import { Orders, OrderDetail } from './pages/Orders'
import { PaymentSettings } from './pages/PaymentSettings'
import { Users } from './pages/Users'
import { AuthProvider, RequireAuth } from './components/AuthProvider'

const Dashboard = lazy(() =>
  import('./pages/Dashboard').then((module) => ({ default: module.Dashboard })),
)
const Operations = lazy(() => import('./pages/Operations').then(m => ({ default: m.Operations })))
const OperationRecords = lazy(() => import('./pages/Operations').then(m => ({ default: m.OperationRecords })))

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
        <Route path="/account/membership" element={<Membership />} />
        <Route path="/orders" element={<Orders />} />
        <Route path="/orders/:id" element={<OrderDetail />} />
        <Route element={<RequireAuth admin />}>
          <Route path="/admin" element={<Suspense fallback={<Spin fullscreen />}><Operations /></Suspense>} />
          <Route path="/admin/users" element={<Users />} />
          <Route path="/admin/audit" element={<Suspense fallback={<Spin fullscreen />}><OperationRecords /></Suspense>} />
          <Route path="/admin/attempts" element={<Suspense fallback={<Spin fullscreen />}><OperationRecords attempts /></Suspense>} />
          <Route path="/admin/orders" element={<Orders admin />} />
          <Route path="/admin/payment-settings" element={<PaymentSettings />} />
        </Route>
        <Route element={<RequireAuth admin />}><Route path="/admin/packages" element={<Packages />} /></Route>
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
