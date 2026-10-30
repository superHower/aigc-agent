import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Empty,
  Layout,
  Row,
  Segmented,
  Skeleton,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  FileImageOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import zhCN from 'antd/es/date-picker/locale/zh_CN'
import { Link } from 'react-router-dom'
import { AppHeader } from '../components/AppHeader'
import { useAuth } from '../components/AuthProvider'
import { Chart } from '../components/Chart'
import { api, getDashboard, promptError, type DashboardData } from '../api/client'

const statusLabels: Record<string, string> = {
  queued: '排队中',
  running: '生成中',
  cancelling: '取消中',
  completed: '已完成',
  partial_failed: '部分失败',
  failed: '失败',
  cancelled: '已取消',
}
const statusColors: Record<string, string> = {
  completed: 'success',
  partial_failed: 'warning',
  failed: 'error',
  running: 'processing',
  queued: 'blue',
  cancelling: 'warning',
  cancelled: 'default',
}
const palette = { done: '#20b68b', failed: '#f07878', active: '#6799f5', purple: '#8b7cf8' }

function Comparison({
  value,
  previous,
  unit = '',
}: {
  value: number
  previous: number
  unit?: string
}) {
  const difference = Math.round((value - previous) * 10) / 10
  return (
    <span className="metric-comparison">
      较上一周期{' '}
      <strong>
        {difference > 0 ? '+' : ''}
        {difference}
        {unit}
      </strong>
    </span>
  )
}

export function Dashboard() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [period, setPeriod] = useState<DashboardData['period']>('week')
  const [selectedDate, setSelectedDate] = useState(() => dayjs())
  const [data, setData] = useState<DashboardData>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const [usage, setUsage] = useState<{ summary: { current_available: number; current_frozen: number; consumed: number }; membership: { active: boolean; expires_at: string | null; concurrency: number } }>()
  const date = selectedDate.format('YYYY-MM-DD')
  useEffect(() => {
    api.get('/account/usage', { params: { period, selected_date: date, timezone_offset: selectedDate.toDate().getTimezoneOffset() } }).then(r => setUsage(r.data)).catch(() => {})
  }, [period, date, revision])

  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined
    setData(undefined)
    setLoading(true)
    setError('')
    const poll = async () => {
      try {
        const next = await getDashboard(
          period,
          date,
          selectedDate.toDate().getTimezoneOffset(),
          controller.signal,
        )
        if (!controller.signal.aborted) {
          setData(next)
          setError('')
        }
      } catch (reason) {
        if (!controller.signal.aborted) setError(promptError(reason))
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
          timer = window.setTimeout(poll, 15000)
        }
      }
    }
    void poll()
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [period, date, revision])

  const trendOption = useMemo(
    () => ({
      color: [palette.done, palette.failed, palette.active, palette.purple],
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0, itemWidth: 12, itemHeight: 8 },
      grid: { left: 45, right: 42, top: 36, bottom: 65 },
      xAxis: {
        type: 'category',
        data: data?.trend.map((item) => item.label),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: '#e6eaf1' } },
        axisLabel: { color: '#7b8599' },
      },
      yAxis: [
        {
          type: 'value',
          name: '图片 / 张',
          minInterval: 1,
          splitLine: { lineStyle: { color: '#f0f2f6', type: 'dashed' } },
        },
        { type: 'value', name: '任务 / 个', minInterval: 1, splitLine: { show: false } },
      ],
      series: [
        ...(['done', 'failed', 'active'] as const).map((key) => ({
          name: { done: '成功出图', failed: '失败', active: '待生成' }[key],
          type: 'bar',
          stack: 'images',
          barMaxWidth: 28,
          data: data?.trend.map((item) => item[key]),
          itemStyle: { borderRadius: [3, 3, 0, 0] },
        })),
        {
          name: '任务数',
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          symbolSize: 6,
          data: data?.trend.map((item) => item.tasks),
        },
      ],
    }),
    [data],
  )

  const distributionOption = useMemo(
    () => ({
      color: [palette.done, palette.failed, palette.active, '#d7deea'],
      tooltip: { trigger: 'item', formatter: '{b}：{c} 张（{d}%）' },
      legend: { bottom: 0, itemWidth: 10, itemHeight: 10 },
      series: [
        {
          type: 'pie',
          radius: ['53%', '74%'],
          center: ['50%', '44%'],
          label: { show: false },
          emphasis: {
            label: { show: true, formatter: '{b}\n{d}%', fontSize: 15, fontWeight: 'bold' },
          },
          itemStyle: { borderColor: '#fff', borderWidth: 4, borderRadius: 7 },
          data: [
            { name: '成功', value: data?.summary.done ?? 0 },
            { name: '失败', value: data?.summary.failed ?? 0 },
            { name: '待生成', value: data?.summary.active ?? 0 },
            { name: '已取消', value: data?.summary.cancelled ?? 0 },
          ],
        },
      ],
    }),
    [data],
  )

  const channelOption = useMemo(() => {
    const channels = [...(data?.channels ?? [])].slice(0, 8).reverse()
    return {
      color: [palette.done, palette.failed, '#d7deea'],
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { bottom: 0, itemWidth: 10, itemHeight: 8 },
      grid: { left: 110, right: 25, top: 10, bottom: 45 },
      xAxis: {
        type: 'value',
        minInterval: 1,
        splitLine: { lineStyle: { color: '#f0f2f6', type: 'dashed' } },
      },
      yAxis: {
        type: 'category',
        data: channels.map((item) => item.name),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { width: 94, overflow: 'truncate' },
      },
      series: [
        {
          name: '成功',
          type: 'bar',
          stack: 'total',
          barMaxWidth: 18,
          data: channels.map((item) => item.done),
        },
        { name: '失败', type: 'bar', stack: 'total', data: channels.map((item) => item.failed) },
        {
          name: '其他',
          type: 'bar',
          stack: 'total',
          data: channels.map((item) => item.total - item.done - item.failed),
          itemStyle: { borderRadius: [0, 4, 4, 0] },
        },
      ],
    }
  }, [data])

  const summary = data?.summary
  const previous = data?.previous
  return (
    <Layout className="app-shell">
      <AppHeader />
      <Layout.Content className="workspace-content dashboard-content">
        <div className="dashboard-heading">
          <div>
            <span className="dashboard-eyebrow">创作，一目了然。</span>
            <Typography.Title level={2}>数据概览</Typography.Title>
            <Typography.Text type="secondary">任务按创建时间统计；积分消耗按成功结算时间统计。</Typography.Text>
          </div>
          <Link to="/workspace">
            <Button type="primary" size="large" icon={<ThunderboltOutlined />}>
              开始生图 <ArrowRightOutlined />
            </Button>
          </Link>
        </div>

        <div className="dashboard-toolbar">
          <Space wrap size="middle">
            <Segmented
              value={period}
              options={[
                { label: '日', value: 'day' },
                { label: '周', value: 'week' },
                { label: '月', value: 'month' },
              ]}
              onChange={(value) => setPeriod(value as DashboardData['period'])}
            />
            <DatePicker
              allowClear={false}
              locale={zhCN}
              value={selectedDate}
              picker={period === 'day' ? 'date' : period}
              onChange={(value) => {
                if (value) setSelectedDate(value)
              }}
            />
            {data && (
              <Typography.Text type="secondary">
                {data.start_date} — {data.end_date}
              </Typography.Text>
            )}
          </Space>
          <Space>
            <Typography.Text type="secondary" className="dashboard-refresh-time">
              {data
                ? `${dayjs(data.updated_at).format('HH:mm:ss')} 更新 · 每 15 秒刷新`
                : '正在同步数据'}
            </Typography.Text>
            <Button
              aria-label="刷新统计"
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={() => setRevision((value) => value + 1)}
            />
          </Space>
        </div>
        {error && (
          <Alert
            type="error"
            showIcon
            message={error}
            action={<Button onClick={() => setRevision((value) => value + 1)}>重试</Button>}
            style={{ marginBottom: 18 }}
          />
        )}
        <Card style={{ marginBottom: 18 }}><Space size="large" wrap><Statistic title="可用积分" value={usage?.summary.current_available ?? 0} /><Statistic title="冻结积分" value={usage?.summary.current_frozen ?? 0} /><Statistic title="本期消耗积分" value={usage?.summary.consumed ?? 0} /><Typography.Text>{usage?.membership.active ? '会员' : '普通用户'} · 并发 {usage?.membership.concurrency ?? 1} · {usage?.membership.expires_at ? `到期 ${new Date(usage.membership.expires_at).toLocaleString()}` : '未开通会员'}</Typography.Text>{isAdmin && <Link to="/admin">经营总览与实际调用成本</Link>}</Space></Card>
        {loading && !data ? (
          <Card className="panel-card">
            <Skeleton active paragraph={{ rows: 8 }} />
          </Card>
        ) : (
          data &&
          summary &&
          previous && (
            <>
              <Row gutter={[18, 18]} className="dashboard-metrics">
                {[
                  {
                    title: '创建任务',
                    value: summary.tasks,
                    before: previous.tasks,
                    suffix: '个',
                    icon: <ThunderboltOutlined />,
                    tone: 'blue',
                    hint: `${summary.active_tasks} 个任务正在排队或生成`,
                  },
                  {
                    title: '成功出图',
                    value: summary.done,
                    before: previous.done,
                    suffix: '张',
                    icon: <FileImageOutlined />,
                    tone: 'green',
                    hint: `共计划生成 ${summary.images} 张图片`,
                  },
                  {
                    title: '出图成功率',
                    value: summary.success_rate,
                    before: previous.success_rate,
                    suffix: '%',
                    icon: <CheckCircleOutlined />,
                    tone: 'purple',
                    hint: '成功 ÷（成功 + 失败），不含待生成及取消',
                  },
                  {
                    title: '失败待处理',
                    value: summary.failed,
                    before: previous.failed,
                    suffix: '张',
                    icon: <ClockCircleOutlined />,
                    tone: 'orange',
                    hint: `${summary.retried_tasks} 个任务触发过自动重试`,
                  },
                ].map((metric) => (
                  <Col xs={24} sm={12} xl={6} key={metric.title}>
                    <Card className="metric-card">
                      <div className="metric-header">
                        <Typography.Text type="secondary">{metric.title}</Typography.Text>
                        <span className={`metric-icon metric-${metric.tone}`}>{metric.icon}</span>
                      </div>
                      <Statistic
                        value={metric.value ?? '—'}
                        suffix={metric.value === null ? undefined : metric.suffix}
                        precision={metric.title === '出图成功率' && metric.value !== null ? 1 : 0}
                      />
                      <Tooltip
                        title={`上一周期：${data.previous_start_date} — ${data.previous_end_date}`}
                      >
                        <div>
                          {metric.value !== null && metric.before !== null ? (
                            <Comparison
                              value={metric.value}
                              previous={metric.before}
                              unit={metric.title === '出图成功率' ? ' 个百分点' : ''}
                            />
                          ) : (
                            <span className="metric-comparison">暂无可比较的已结束图片</span>
                          )}
                        </div>
                      </Tooltip>
                      <div className="metric-hint">{metric.hint}</div>
                    </Card>
                  </Col>
                ))}
              </Row>

              <Row gutter={[18, 18]}>
                <Col xs={24} xl={16}>
                  <Card
                    className="panel-card dashboard-chart-card"
                    title="生成趋势"
                    extra={<Tag bordered={false}>按{period === 'day' ? '小时' : '天'}统计</Tag>}
                  >
                    <Chart
                      option={trendOption}
                      label="成功、失败、待生成图片数量柱状图及任务数折线图"
                    />
                  </Card>
                </Col>
                <Col xs={24} xl={8}>
                  <Card
                    className="panel-card dashboard-chart-card"
                    title="出图结果分布"
                    extra={<Tag bordered={false}>{summary.images} 张</Tag>}
                  >
                    {summary.images ? (
                      <Chart
                        option={distributionOption}
                        label={`成功 ${summary.done} 张，失败 ${summary.failed} 张，待生成 ${summary.active} 张，取消 ${summary.cancelled} 张`}
                      />
                    ) : (
                      <div className="dashboard-empty">
                        <Empty description="本周期暂无生成图片" />
                      </div>
                    )}
                  </Card>
                </Col>
                {isAdmin && <Col xs={24} xl={12}>
                  <Card
                    className="panel-card"
                    title="渠道出图排行"
                    extra={
                      <Link to="/channels">
                        管理渠道 <ArrowRightOutlined />
                      </Link>
                    }
                  >
                    {data.channels.length ? (
                      <Chart
                        option={channelOption}
                        label="渠道出图排行，按成功图片数排序，最多显示前八个渠道"
                        height={300}
                      />
                    ) : (
                      <div className="dashboard-empty">
                        <Empty description="本周期暂无渠道数据" />
                      </div>
                    )}
                    <Typography.Text type="secondary" className="dashboard-footnote">
                      按成功出图数排名，最多显示 8 个渠道；重试转移后归属最终执行渠道。
                    </Typography.Text>
                  </Card>
                </Col>}
                <Col xs={24} xl={12}>
                  <Card
                    className="panel-card"
                    title="任务状态"
                    extra={
                      <Link to="/tasks">
                        全部任务 <ArrowRightOutlined />
                      </Link>
                    }
                  >
                    <div className="dashboard-status-grid">
                      {Object.entries(statusLabels).map(([key, label]) => (
                        <div className="dashboard-status-item" key={key}>
                          <Tag color={statusColors[key]}>{label}</Tag>
                          <strong>
                            {data.task_statuses[key] ?? 0}
                            <small> 个</small>
                          </strong>
                        </div>
                      ))}
                    </div>
                    {isAdmin && <div className="dashboard-cost">
                      <div>
                        <Typography.Text type="secondary">本周期基础预估费用</Typography.Text>
                        <div>
                          <Link to="/admin">查看调用成本统计</Link>
                        </div>
                      </div>
                      <Typography.Text type="secondary">
                        按渠道配置单价估算
                        <br />实际成本无账单来源时为未知
                      </Typography.Text>
                    </div>}
                  </Card>
                </Col>
              </Row>

              <Card
                className="panel-card"
                title="最近任务"
                extra={
                  <Link to="/workspace">
                    前往工作台 <ArrowRightOutlined />
                  </Link>
                }
              >
                <Table
                  rowKey="id"
                  pagination={false}
                  dataSource={data.recent_tasks}
                  scroll={{ x: 760 }}
                  locale={{
                    emptyText: <Empty description="本周期暂无任务，开始你的第一次创作吧" />,
                  }}
                  columns={[
                    {
                      title: '任务',
                      dataIndex: 'id',
                      ellipsis: true,
                      render: (id: string) => <Link to={`/tasks/${id}`}>{id}</Link>,
                    },
                    {
                      title: '状态',
                      dataIndex: 'status',
                      width: 110,
                      render: (status: string) => (
                        <Tag color={statusColors[status]}>{statusLabels[status] ?? status}</Tag>
                      ),
                    },
                    {
                      title: '出图',
                      width: 100,
                      render: (_, item) => `${item.done} / ${item.images}`,
                    },
                    { title: '失败', dataIndex: 'failed', width: 75 },
                    {
                      title: '自动重试',
                      width: 100,
                      render: (_, item) => `${item.auto_retry_count} / 3`,
                    },
                    {
                      title: '创建时间',
                      dataIndex: 'created_at',
                      width: 170,
                      render: (value: string) => dayjs(value).format('MM-DD HH:mm:ss'),
                    },
                  ]}
                />
              </Card>
              <Typography.Paragraph type="secondary" className="dashboard-footnote">
                统计口径：按任务创建时间归属本周期，展示这些任务的当前结果；最终出图不含 OCR 及 Logo
                中间步骤。周为周一至周日，日期按浏览器时区计算。上一周期为紧邻的等长时间段。
              </Typography.Paragraph>
            </>
          )
        )}
      </Layout.Content>
    </Layout>
  )
}
