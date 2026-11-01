import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Form, Input, Space, Typography } from 'antd'
import { api, promptError } from '../api/client'

export function PhoneAuth({ reset = false }: { reset?: boolean }) {
  const [form] = Form.useForm()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [challenge, setChallenge] = useState<{ captcha_id: string; image: string }>()
  const navigate = useNavigate()
  async function refreshCaptcha() {
    setRefreshing(true); setChallenge(undefined); form.setFieldValue('code', '')
    try { const { data } = await api.get('/auth/captcha'); setChallenge(data) }
    catch (reason) { setError(promptError(reason)) }
    finally { setRefreshing(false) }
  }
  useEffect(() => { if (!reset) void refreshCaptcha() }, [reset])
  if (reset) return <main className="auth-page"><Card title="找回密码"><Typography.Paragraph>请联系管理员核实身份后重置密码。重置后原登录会话将失效。</Typography.Paragraph><Link to="/login">返回登录</Link></Card></main>
  return <main className="auth-page"><Card>
    <Typography.Title level={2}>{reset ? '找回密码' : '注册账号'}</Typography.Title>
    {error && <Alert type="error" message={error} style={{ marginBottom: 16 }} />}
    <Form form={form} layout="vertical" onFinish={async (values) => {
      setBusy(true); setError('')
      try {
        await api.post('/auth/register', { ...values, captcha_id: challenge?.captcha_id })
        navigate('/login', { state: { notice: reset ? '密码已重置，请重新登录' : '注册成功，请登录' } })
      } catch (reason) { setError(promptError(reason)); void refreshCaptcha() }
      finally { setBusy(false) }
    }}>
      {!reset && <Form.Item name="username" label="用户名" rules={[{ required: true }, { pattern: /^(?![0-9]+$)[\u4e00-\u9fffA-Za-z0-9_]{3,24}$/, message: '3–24 位中文、字母、数字或下划线，不能为纯数字' }]}><Input autoComplete="username" maxLength={24} /></Form.Item>}
      <Form.Item name="phone" label="手机号" rules={[{ required: true }, { pattern: /^1[3-9][0-9]{9}$/, message: '请输入有效的中国大陆手机号' }]}><Input autoComplete="tel" maxLength={11} /></Form.Item>
      <Form.Item label="图形验证码" required><Space wrap>
        <Form.Item name="code" noStyle rules={[{ required: true }, { pattern: /^[A-Za-z0-9]{5}$/, message: '请输入图片中的 5 位字符' }]}><Input aria-label="图形验证码" autoComplete="off" maxLength={5} style={{ width: 140 }} /></Form.Item>
        <Button type="text" aria-label="刷新图形验证码" title="看不清？点击换一张" disabled={refreshing} loading={refreshing} onClick={() => void refreshCaptcha()} style={{ height: 64, padding: 0 }}>{challenge ? <img src={challenge.image} alt="图形验证码，点击换一张" width={180} height={64} /> : '获取验证码'}</Button>
      </Space><Typography.Text type="secondary">不区分大小写，5 分钟内有效，点击图片换一张。</Typography.Text></Form.Item>
      <Form.Item name="password" label="密码" rules={[{ required: true }, { min: 8, max: 64, message: '密码长度为 8–64 位' }]}><Input.Password autoComplete="new-password" maxLength={64} /></Form.Item>
      <Form.Item name="confirm" label="确认密码" dependencies={['password']} rules={[{ required: true }, ({ getFieldValue }) => ({ validator(_, value) { return value === getFieldValue('password') ? Promise.resolve() : Promise.reject(new Error('两次密码不一致')) } })]}><Input.Password autoComplete="new-password" maxLength={64} /></Form.Item>
      <Button block type="primary" htmlType="submit" loading={busy} disabled={!challenge || refreshing}>注册</Button>
    </Form>
    <Typography.Paragraph style={{ marginTop: 16 }}><Link to="/login">返回登录</Link></Typography.Paragraph>
  </Card></main>
}
