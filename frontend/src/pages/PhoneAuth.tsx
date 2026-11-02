import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { api, promptError } from '../api/client'

export function PhoneAuth({ reset = false }: { reset?: boolean }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  return <main className="auth-page"><Card>
    <Typography.Title level={2}>{reset ? '修改密码' : '注册账号'}</Typography.Title>
    {!reset && <Typography.Paragraph>注册即赠 500 积分，登录后立即可用。注册 24 小时内可在充值中心领取新人体验卡优惠。</Typography.Paragraph>}
    {reset && <Typography.Paragraph type="secondary">输入邮箱和原密码以修改密码。忘记原密码请联系管理员。</Typography.Paragraph>}
    {error && <Alert type="error" message={error} />}
    <Form layout="vertical" onFinish={async values => {
      setBusy(true); setError('')
      try {
        await api.post(reset ? '/auth/reset-password' : '/auth/register', values)
        navigate('/login', { state: { notice: reset ? '密码已修改，请重新登录' : '注册成功，请登录' } })
      } catch (reason) { setError(promptError(reason)) } finally { setBusy(false) }
    }}>
      {!reset && <Form.Item name="username" label="用户名" rules={[{ required: true }, { pattern: /^(?![0-9]+$)[\u4e00-\u9fffA-Za-z0-9_]{3,24}$/, message: '3–24 位中文、字母、数字或下划线，不能为纯数字' }]}><Input autoComplete="username" maxLength={24} /></Form.Item>}
      <Form.Item name="email" label="邮箱" rules={[{ required: true }, { type: 'email' }]}><Input autoComplete="email" maxLength={254} /></Form.Item>
      {reset && <Form.Item name="old_password" label="原密码" rules={[{ required: true }]}><Input.Password autoComplete="current-password" maxLength={64} /></Form.Item>}
      <Form.Item name="password" label={reset ? '新密码' : '密码'} rules={[{ required: true, min: 8, max: 64 }]}><Input.Password autoComplete="new-password" maxLength={64} /></Form.Item>
      <Form.Item name="confirm" label={reset ? '确认新密码' : '确认密码'} dependencies={['password']} rules={[{ required: true }, ({ getFieldValue }) => ({ validator(_, value) { return value === getFieldValue('password') ? Promise.resolve() : Promise.reject(new Error('两次密码不一致')) } })]}><Input.Password autoComplete="new-password" maxLength={64} /></Form.Item>
      <Button block type="primary" htmlType="submit" loading={busy}>{reset ? '修改密码' : '注册'}</Button>
    </Form><Typography.Paragraph style={{ marginTop: 16 }}><Link to="/login">返回登录</Link></Typography.Paragraph>
  </Card></main>
}
