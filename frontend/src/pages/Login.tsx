import { useState } from 'react'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { api, promptError } from '../api/client'
import { Link, useLocation } from 'react-router-dom'

export function Login() {
  const location = useLocation()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  return <main className="auth-page">
    <Card>
      <Typography.Title level={2}>AI 生图</Typography.Title>
      <Typography.Paragraph type="secondary">登录后管理自己的图片、任务和模板。</Typography.Paragraph>
      {location.state?.notice && <Alert type="success" message={location.state.notice} />}
      {error && <Alert type="error" message={error} style={{ marginBottom: 16 }} />}
      <Form layout="vertical" onFinish={async (values) => {
        setBusy(true); setError('')
        try { await api.post('/auth/login', values); window.location.assign('/') }
        catch (reason) { setError(promptError(reason)) }
        finally { setBusy(false) }
      }}>
        <Form.Item name="account" label="邮箱" rules={[{ required: true, whitespace: true }, { validator: async (_, value: string) => { if (!value || value.trim().toLowerCase() === 'admin') return; if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())) throw new Error('请输入有效的邮箱地址') } }]}><Input autoComplete="username" placeholder="请输入邮箱" maxLength={254} /></Form.Item>
        <Form.Item name="password" label="密码" rules={[{ required: true }]}><Input.Password autoComplete="current-password" /></Form.Item>
        <Button block type="primary" htmlType="submit" loading={busy}>登录</Button>
      </Form>
      <Typography.Paragraph style={{ marginTop: 16 }}><Link to="/register">注册账号</Link> · <Link to="/forgot-password">忘记密码</Link></Typography.Paragraph>
    </Card>
  </main>
}
