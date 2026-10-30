import { useEffect, useState } from 'react'
import { Alert, Button, Card, Space, Statistic, Table, Typography } from 'antd'
import { api, promptError } from '../api/client'
import { AppHeader } from '../components/AppHeader'

type Entry = { id: string; event: string; available_delta: number; frozen_delta: number; created_at: string }
type Lot = { id: string; source: string; available: number; frozen: number; expires_at: string | null }
const labels: Record<string, string> = { grant: '发放', freeze: '冻结', settle: '成功扣费', release: '释放', expire: '到期', adjust: '管理员调整' }
export function Credits() {
  const [balance, setBalance] = useState<{ available: number; frozen: number; lots: Lot[] } | null>(null)
  const [entries, setEntries] = useState<Entry[]>([])
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState('')
  useEffect(() => {
    Promise.all([api.get('/account/credits'), api.get('/account/credit-entries', { params: { offset, limit: 50 } })]).then(([account, ledger]) => {
      setBalance(account.data); setEntries(ledger.data.items); setError('')
    }).catch(reason => setError(promptError(reason)))
  }, [offset])
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Space direction="vertical" className="page-stack" size="large">
    {error && <Alert type="error" message={error} />}
    <Card title="我的积分" loading={!balance}><Space size="large"><Statistic title="可用积分" value={balance?.available ?? 0} /><Statistic title="任务冻结" value={balance?.frozen ?? 0} /></Space><Typography.Paragraph type="secondary">1 积分生成 1 张最终图片。注册体验积分 7 天有效，付费积分不过期。自动重试不额外扣费；手动重试重新冻结。充值请前往会员套餐，人工核实收款后到账。</Typography.Paragraph></Card>
    <Card title="积分来源"><Table rowKey="id" dataSource={balance?.lots} pagination={false} columns={[{ title: '来源', dataIndex: 'source', render: (v: string) => v === 'trial' ? '注册体验' : v }, { title: '可用', dataIndex: 'available' }, { title: '冻结', dataIndex: 'frozen' }, { title: '到期时间', dataIndex: 'expires_at', render: (v: string | null) => v ? new Date(v).toLocaleString() : '永久有效' }]} /></Card>
    <Card title="积分明细"><Table rowKey="id" dataSource={entries} pagination={false} columns={[{ title: '事件', dataIndex: 'event', render: (v: string) => labels[v] ?? v }, { title: '可用变动', dataIndex: 'available_delta' }, { title: '冻结变动', dataIndex: 'frozen_delta' }, { title: '时间', dataIndex: 'created_at', render: (v: string) => new Date(v).toLocaleString() }]} /><Space><Button disabled={!offset} onClick={() => setOffset(offset - 50)}>上一页</Button><Button disabled={entries.length < 50} onClick={() => setOffset(offset + 50)}>下一页</Button></Space></Card>
  </Space></main></div>
}
