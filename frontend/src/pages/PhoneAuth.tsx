import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Form, Input, Space, Typography } from 'antd'
import { api, promptError } from '../api/client'

export function PhoneAuth({ reset = false }: { reset?: boolean }) {
  const [form] = Form.useForm()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [sending, setSending] = useState(false)
  const [remaining, setRemaining] = useState(0)
  const navigate = useNavigate()
  useEffect(() => {
    if (!remaining) return
    const timer = window.setTimeout(() => setRemaining(remaining - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [remaining])
  return <main style={{ maxWidth: 440, margin: '8vh auto', padding: 24 }}><Card>
    <Typography.Title level={2}>{reset ? '找回密码' : '注册账号'}</Typography.Title>
    {error && <Alert type="error" message={error} style={{ marginBottom: 16 }} />}
    <Form form={form} layout="vertical" onFinish={async (values) => {
      setBusy(true); setError('')
      try {
        await api.post(reset ? '/auth/reset-password' : '/auth/register', values)
        navigate('/login', { state: { notice: reset ? '密码已重置，请重新登录' : '注册成功，请登录' } })
      } catch (reason) { setError(promptError(reason)) }
      finally { setBusy(false) }
    }}>
      {!reset && <Form.Item name="username" label="用户名" rules={[{ required: true }, { pattern: /^(?![0-9]+$)[\u4e00-\u9fffA-Za-z0-9_]{3,24}$/, message: '3–24 位中文、字母、数字或下划线，不能为纯数字' }]}><Input autoComplete="username" maxLength={24} /></Form.Item>}
      <Form.Item name="phone" label="手机号" rules={[{ required: true }, { pattern: /^1[3-9][0-9]{9}$/, message: '请输入有效的中国大陆手机号' }]}><Input autoComplete="tel" maxLength={11} /></Form.Item>
      <Form.Item label="短信验证码" required><Space.Compact style={{ width: '100%' }}>
        <Form.Item name="code" noStyle rules={[{ required: true }, { pattern: /^[0-9]{6}$/, message: '请输入 6 位验证码' }]}><Input autoComplete="one-time-code" maxLength={6} /></Form.Item>
        <Button loading={sending} disabled={remaining > 0} onClick={async () => {
          try {
            await form.validateFields(['phone']); setSending(true); setError('')
            await api.post('/auth/sms', { phone: form.getFieldValue('phone'), purpose: reset ? 'reset' : 'register' })
            setRemaining(60)
          } catch (reason) { if (reason && typeof reason === 'object' && !('errorFields' in reason)) setError(promptError(reason)) }
          finally { setSending(false) }
        }}>{remaining ? `${remaining} 秒后重发` : '获取验证码'}</Button>
      </Space.Compact></Form.Item>
      <Form.Item name="password" label="密码" rules={[{ required: true }, { min: 8, max: 64, message: '密码长度为 8–64 位' }]}><Input.Password autoComplete="new-password" maxLength={64} /></Form.Item>
      <Form.Item name="confirm" label="确认密码" dependencies={['password']} rules={[{ required: true }, ({ getFieldValue }) => ({ validator(_, value) { return value === getFieldValue('password') ? Promise.resolve() : Promise.reject(new Error('两次密码不一致')) } })]}><Input.Password autoComplete="new-password" maxLength={64} /></Form.Item>
      <Button block type="primary" htmlType="submit" loading={busy}>{reset ? '重置密码' : '注册'}</Button>
    </Form>
    <Typography.Paragraph style={{ marginTop: 16 }}><Link to="/login">返回登录</Link></Typography.Paragraph>
  </Card></main>
}
