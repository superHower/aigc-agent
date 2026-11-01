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
        <Form.Item name="account" label="用户名 / 手机号" rules={[{ required: true }]}><Input autoComplete="username" /></Form.Item>
        <Form.Item name="password" label="密码" rules={[{ required: true }]}><Input.Password autoComplete="current-password" /></Form.Item>
        <Button block type="primary" htmlType="submit" loading={busy}>登录</Button>
      </Form>
      <Typography.Paragraph style={{ marginTop: 16 }}><Link to="/register">注册账号</Link> · <Link to="/forgot-password">忘记密码</Link></Typography.Paragraph>
    </Card>
  </main>
}
