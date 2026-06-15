import { useEffect, useMemo, useRef } from 'react'
import type { FairComparison } from './analytics'
import type { ActualStrategySummary, ProjectionSummary } from './types'

let echartsRuntime: Promise<typeof import('echarts/core')> | null = null

function loadECharts() {
  if (!echartsRuntime) {
    echartsRuntime = Promise.all([
      import('echarts/core'),
      import('echarts/charts'),
      import('echarts/components'),
      import('echarts/renderers'),
    ]).then(([core, charts, components, renderers]) => {
      core.use([
        charts.LineChart,
        components.GridComponent,
        components.LegendComponent,
        components.TooltipComponent,
        renderers.CanvasRenderer,
      ])
      return core
    })
  }
  return echartsRuntime
}

function useChart(option: object) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    let disposed = false
    let chart: { setOption: (value: unknown) => void; resize: () => void; dispose: () => void } | undefined
    const resize = () => chart?.resize()
    void loadECharts().then((echarts) => {
      if (disposed || !ref.current) return
      chart = echarts.init(ref.current)
      chart.setOption(option)
    })
    window.addEventListener('resize', resize)
    return () => {
      disposed = true
      window.removeEventListener('resize', resize)
      chart?.dispose()
    }
  }, [option])
  return ref
}

const baseAxis = {
  axisLine: { lineStyle: { color: '#29445b' } },
  axisLabel: { color: '#7890a4', fontSize: 10 },
  splitLine: { lineStyle: { color: '#132a3d' } },
}

export function FairComparisonChart({ comparison }: { comparison: FairComparison }) {
  const option = useMemo(() => ({
    animationDuration: 450,
    grid: { left: 48, right: 18, top: 36, bottom: 34 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#071827',
      borderColor: '#2b4c65',
      textStyle: { color: '#dce8f1' },
      valueFormatter: (value: number) => `${(value * 100).toFixed(1)}%`,
    },
    legend: { top: 5, right: 8, textStyle: { color: '#8ca2b5' } },
    xAxis: { type: 'category', data: comparison.points.map((point) => point.date.slice(5)), ...baseAxis },
    yAxis: { type: 'value', axisLabel: { color: '#7890a4', formatter: (value: number) => `${Math.round(value * 100)}%` }, splitLine: baseAxis.splitLine },
    series: [
      { name: '我的实际', type: 'line', connectNulls: true, smooth: 0.25, symbolSize: 5, data: comparison.points.map((point) => point.userRoi), lineStyle: { width: 2, color: '#48d17b' }, itemStyle: { color: '#48d17b' }, areaStyle: { color: 'rgba(72,209,123,.08)' } },
      { name: '模型均衡', type: 'line', connectNulls: true, smooth: 0.25, symbolSize: 5, data: comparison.points.map((point) => point.modelRoi), lineStyle: { width: 2, color: '#429cff' }, itemStyle: { color: '#429cff' } },
    ],
  }), [comparison])
  const ref = useChart(option)
  return <div ref={ref} className="personal-comparison-chart" aria-label="我的投注与模型均衡策略累计回报率对比图" />
}

export function StrategyProjectionChart({ dates, summaries }: { dates: string[]; summaries: ProjectionSummary[] }) {
  const option = useMemo(() => ({
    animationDuration: 500,
    grid: { left: 50, right: 22, top: 42, bottom: 38 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#071827',
      borderColor: '#2b4c65',
      textStyle: { color: '#dce8f1' },
      valueFormatter: (value: number) => `${Math.round(value)}元`,
    },
    legend: { top: 6, right: 8, textStyle: { color: '#8ca2b5' } },
    xAxis: { type: 'category', data: dates.map((date) => date === '已结算' ? date : date.slice(5)), ...baseAxis, axisLabel: { color: '#7890a4', interval: Math.max(0, Math.floor(dates.length / 8)) } },
    yAxis: { type: 'value', min: 0, ...baseAxis },
    series: summaries.map((summary) => ({
      name: summary.name,
      type: 'line',
      smooth: 0.2,
      showSymbol: false,
      data: summary.medianPath,
      lineStyle: { width: summary.key === 'mixed' ? 3 : 2, color: summary.color, type: summary.key === 'mixed' ? 'dashed' : 'solid' },
      itemStyle: { color: summary.color },
    })),
  }), [dates, summaries])
  const ref = useChart(option)
  return <div ref={ref} className="strategy-projection-chart" aria-label="三种模型策略及我的混合策略直到世界杯决赛的本金中位数轨迹" />
}

export function StrategyActualChart({ dates, summaries }: { dates: string[]; summaries: ActualStrategySummary[] }) {
  const option = useMemo(() => ({
    animationDuration: 450,
    grid: { left: 50, right: 22, top: 42, bottom: 38 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#071827',
      borderColor: '#2b4c65',
      textStyle: { color: '#dce8f1' },
      valueFormatter: (value: number) => `${value.toFixed(2)}元`,
    },
    legend: { top: 6, right: 8, textStyle: { color: '#8ca2b5' } },
    xAxis: { type: 'category', data: dates.map((date) => date === '起始' ? date : date.slice(5)), ...baseAxis },
    yAxis: { type: 'value', min: 0, ...baseAxis },
    series: summaries.map((summary) => ({
      name: summary.name,
      type: 'line',
      smooth: 0.18,
      symbolSize: 5,
      data: summary.path,
      lineStyle: { width: 2.5, color: summary.color },
      itemStyle: { color: summary.color },
    })),
  }), [dates, summaries])
  const ref = useChart(option)
  return <div ref={ref} className="strategy-actual-chart" aria-label="三种策略根据真实结算赛果形成的本金曲线" />
}
