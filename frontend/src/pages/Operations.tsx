import { useEffect, useState } from 'react'
import { Alert, Button, Card, DatePicker, Input, Modal, Segmented, Space, Statistic, Table, Typography, message } from 'antd'
import dayjs from 'dayjs'
import { api, cleanupStorage, previewStorageCleanup, promptError } from '../api/client'
import { AppHeader } from '../components/AppHeader'
import { Chart } from '../components/Chart'

type Metrics = { summary: Record<string, number>; trend: { label: string; verified_cents: number; consumed: number; granted: number }[]; sales: { package_id: string; name: string; orders: number; verified_cents: number }[]; tasks: { summary: { tasks: number; failed: number; retried_tasks: number }; trend: { label: string; tasks: number }[] } }
export function Operations() {
  const [data, setData] = useState<Metrics>()
  const [period, setPeriod] = useState('week')
  const [selected, setSelected] = useState(dayjs())
  const [readiness, setReadiness] = useState<Record<string, string | number | boolean>>()
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [cleanupDate, setCleanupDate] = useState(dayjs().subtract(30, 'day'))
  const [cleanupBusy, setCleanupBusy] = useState(false)
  const [cleanupInfo, setCleanupInfo] = useState<{ count: number; bytes: number; protected: number; sample: string[] }>()
  const formatBytes = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(2)} MB`
  const previewCleanup = async () => {
    try { setCleanupInfo(await previewStorageCleanup(cleanupDate.format('YYYY-MM-DD'))) } catch (e) { message.error(promptError(e)) }
  }
  const executeCleanup = async () => {
    if (!cleanupInfo?.count) return message.info('没有符合条件的图片')
    Modal.confirm({ title: '确认清理服务器图片？', content: `将删除 ${cleanupInfo.count} 个文件，共 ${formatBytes(cleanupInfo.bytes)}。任务记录会保留，但删除后图片无法下载。`, okText: '确认删除', okType: 'danger', cancelText: '取消', onOk: async () => { setCleanupBusy(true); try { const result = await cleanupStorage(cleanupDate.format('YYYY-MM-DD')); message.success(`已删除 ${result.deleted} 个文件`); setCleanupInfo(undefined) } catch (e) { message.error(promptError(e)) } finally { setCleanupBusy(false) } } })
  }
  useEffect(() => {
    Promise.all([api.get('/admin/dashboard', { params: { period, selected_date: selected.format('YYYY-MM-DD'), timezone_offset: selected.toDate().getTimezoneOffset() } }), api.get('/admin/readiness')]).then(([d, r]) => { setData(d.data); setReadiness(r.data); setError('') }).catch(e => setError(promptError(e)))
  }, [period, selected, revision])
  const s = data?.summary
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Space direction="vertical" className="page-stack" size="large">
    {error && <Alert type="error" message={error} />}
    <Card title="经营总览"><Space wrap><Segmented value={period} options={[{ label: '日', value: 'day' }, { label: '周', value: 'week' }, { label: '月', value: 'month' }]} onChange={setPeriod} /><DatePicker value={selected} allowClear={false} onChange={d => d && setSelected(d)} /><Button onClick={() => setRevision(v => v + 1)}>刷新</Button></Space><Typography.Paragraph type="secondary">充值按核实入账时间，积分按流水发生时间；任务趋势按创建时间。余额与待审核为当前快照。日期按浏览器时区偏移计算。</Typography.Paragraph>
      <Space wrap size="large">{[['已核实充值（元）', (s?.verified_cents ?? 0) / 100], ['已入账订单', s?.credited_orders], ['待审核（当前）', s?.pending_reviews], ['发放积分', s?.granted], ['付费发放', s?.paid_granted], ['体验发放', s?.trial_granted], ['补偿发放', s?.adjustment_granted], ['消耗积分', s?.consumed], ['冻结积分（当前）', s?.current_frozen], ['可用积分（当前）', s?.current_available], ['本期释放', s?.released], ['本期过期', s?.expired], ['负调整', s?.adjusted], ['创建任务', data?.tasks.summary.tasks], ['最终失败图片', data?.tasks.summary.failed], ['自动重试任务', data?.tasks.summary.retried_tasks]].map(([title, value]) => <Statistic key={String(title)} title={title} value={value ?? 0} />)}</Space>
    </Card>
    <Card title="充值趋势（核实入账时间）"><Chart label="统计趋势" option={{ tooltip: { trigger: 'axis' }, xAxis: { type: 'category', data: data?.trend.map(t => t.label) }, yAxis: { type: 'value', name: '元' }, series: [{ name: '已核实充值', type: 'bar', data: data?.trend.map(t => t.verified_cents / 100) }] }} /></Card>
    <Card title="积分趋势（流水发生时间）"><Chart label="统计趋势" option={{ tooltip: { trigger: 'axis' }, legend: {}, xAxis: { type: 'category', data: data?.trend.map(t => t.label) }, yAxis: { type: 'value', minInterval: 1 }, series: [{ name: '发放', type: 'line', data: data?.trend.map(t => t.granted) }, { name: '消耗', type: 'line', data: data?.trend.map(t => t.consumed) }] }} /></Card>
    <Card title="任务趋势（创建时间）"><Chart label="统计趋势" option={{ tooltip: { trigger: 'axis' }, xAxis: { type: 'category', data: data?.tasks.trend.map(t => t.label) }, yAxis: { type: 'value', minInterval: 1 }, series: [{ name: '创建任务', type: 'bar', data: data?.tasks.trend.map(t => t.tasks) }] }} /></Card>
    <Card title="套餐销量（已核实）"><Table rowKey={r => r.package_id + r.name} dataSource={data?.sales} pagination={false} columns={[{ title: '订单套餐名称快照', dataIndex: 'name' }, { title: '订单数', dataIndex: 'orders' }, { title: '核实金额（元）', dataIndex: 'verified_cents', render: (v: number) => (v / 100).toFixed(2) }]} /></Card>
    <Card title="调用与成本"><Space wrap size="large">{[['执行记录', s?.attempts], ['已调用 SDK', s?.dispatched], ['发出状态未知', s?.dispatch_unknown], ['失败记录', s?.failed_attempts], ['重试调用', s?.retry_attempts], ['实际成本未知', s?.unknown_cost_attempts], ['缺少估算单价', s?.unpriced_attempts], ['配置单价估算（元）', (s?.estimated_cost_cents ?? 0) / 100]].map(([title, value]) => <Statistic key={String(title)} title={title} value={value ?? 0} />)}</Space><Alert type="info" message="估算只汇总有单价且调用 SDK 的记录，包含重试。没有可信上游账单来源时，实际成本为未知；调用 SDK 也不代表上游已接收。历史记录的发出状态可能未知。" /></Card>
    <Card title="发布配置状态"><Typography.Paragraph>数据库：{readiness?.database}；验证码：{readiness?.verification_mode}；Secure Cookie：{readiness?.secure_cookie ? '开启' : '关闭'}；上架套餐：{readiness?.active_packages}；有效收款码：{readiness?.payment_code_active ? '已启用' : '未配置'}；执行器：单进程。</Typography.Paragraph><Alert type="warning" message={String(readiness?.external_acceptance ?? '加载中')} /></Card>
    <Card title="存储图片清理"><Typography.Paragraph type="secondary">按文件最后修改时间清理指定日期以前的上传图、生成图、遮罩和快照。正在执行的任务文件会自动保护；数据库任务记录不会删除。</Typography.Paragraph><Space wrap><DatePicker value={cleanupDate} onChange={d => d && setCleanupDate(d)} /><Button onClick={() => void previewCleanup()}>预览清理范围</Button><Button danger disabled={!cleanupInfo?.count} loading={cleanupBusy} onClick={() => void executeCleanup()}>确认删除</Button></Space>{cleanupInfo && <Alert style={{ marginTop: 16 }} type={cleanupInfo.count ? 'warning' : 'info'} message={`符合条件 ${cleanupInfo.count} 个文件，共 ${formatBytes(cleanupInfo.bytes)}；保护中 ${cleanupInfo.protected} 个文件`} description={cleanupInfo.sample.length ? `示例：${cleanupInfo.sample.join('、')}` : '没有符合条件的图片。'} />}</Card>
  </Space></main></div>
}

type RecordRow = Record<string, string | number | null>
export function OperationRecords({ attempts = false }: { attempts?: boolean }) {
  const [items, setItems] = useState<RecordRow[]>([])
  const [target, setTarget] = useState('')
  const [filter, setFilter] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState('')
  useEffect(() => { api.get(attempts ? '/admin/attempts' : '/admin/audit', { params: { limit: 30, offset: (page - 1) * 30, target_id: filter || undefined } }).then(r => { setItems(r.data.items); setTotal(r.data.total) }).catch(e => setError(promptError(e))) }, [attempts, page, filter])
  const fields = attempts ? [['job_id', '逻辑图片 job'], ['id', '请求记录'], ['channel_name', '渠道快照'], ['model', '模型快照'], ['retry_round', '重试轮次'], ['started_at', '开始'], ['ended_at', '结束'], ['status', '结果'], ['dispatched', '调用 SDK（1/0/未知）'], ['response_after_cancel', '取消后响应'], ['cost_source', '实际成本来源'], ['estimated_cost_cents', '估算分'], ['error_code', '错误类别']] : [['created_at', '时间'], ['actor_id', '操作者'], ['action', '操作'], ['target_id', '对象'], ['reason', '原因'], ['details', '变更摘要']]
  return <div className="app-shell"><AppHeader /><main className="workspace-content"><Card title={attempts ? '调用明细' : '操作审计'}>{error && <Alert type="error" message={error} />}<Input.Search placeholder={attempts ? '按 job ID 筛选' : '按对象 ID 筛选'} value={target} onChange={e => setTarget(e.target.value)} onSearch={() => { setFilter(target); setPage(1) }} style={{ maxWidth: 420, marginBottom: 16 }} /><Table rowKey="id" dataSource={items} scroll={{ x: attempts ? 2400 : 1600 }} pagination={{ current: page, pageSize: 30, total, onChange: setPage }} columns={fields.map(([key, title]) => ({ title, dataIndex: key, render: (v: unknown) => v === null ? '未知' : String(v) }))} /></Card></main></div>
}

