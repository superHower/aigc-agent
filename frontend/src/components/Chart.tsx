import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { AriaComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  AriaComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

export function Chart({
  option,
  label,
  height = 320,
}: {
  option: EChartsCoreOption
  label: string
  height?: number
}) {
  const element = useRef<HTMLDivElement>(null)
  const instance = useRef<echarts.EChartsType>()

  useEffect(() => {
    if (!element.current) return
    const chart = echarts.init(element.current, 'dark')
    instance.current = chart
    const resize = new ResizeObserver(() => chart.resize())
    resize.observe(element.current)
    return () => {
      resize.disconnect()
      chart.dispose()
      instance.current = undefined
    }
  }, [])

  useEffect(() => {
    instance.current?.setOption(
      { backgroundColor: 'transparent', ...option, aria: { enabled: true, label: { description: label } }, textStyle: { fontFamily: 'inherit' } },
      true,
    )
  }, [option, label])

  return <div ref={element} role="img" aria-label={label} style={{ height, width: '100%' }} />
}
