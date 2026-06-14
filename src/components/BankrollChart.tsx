import { useEffect, useMemo, useRef } from 'react'
import { percent } from '../lib/format'
import type { Portfolio } from '../types'

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
        charts.BarChart,
        components.GridComponent,
        components.MarkLineComponent,
        components.TooltipComponent,
        renderers.CanvasRenderer,
      ])
      return core
    })
  }
  return echartsRuntime
}

interface BankrollChartProps {
  portfolio: Portfolio
  onSelect: (key: Portfolio['key']) => void
  portfolios: Portfolio[]
}

export function BankrollChart({ portfolio, portfolios, onSelect }: BankrollChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const startingBankroll = portfolio.stake + portfolio.retainedCash
  const option = useMemo(() => ({
    animationDuration: 500,
    grid: { left: 46, right: 20, top: 34, bottom: 42 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#0b1a29',
      borderColor: '#29425b',
      textStyle: { color: '#d9e7f2' },
      formatter: (items: Array<{ axisValue: number; data: number }>) =>
        `赛后本金 ${items[0].axisValue}元<br/>概率密度 ${Number(items[0].data).toFixed(4)}`,
    },
    xAxis: {
      type: 'category',
      name: '赛后本金（元）',
      nameTextStyle: { color: '#71879b' },
      axisLabel: { color: '#71879b', interval: Math.max(0, Math.floor(portfolio.distribution.length / 8)) },
      axisLine: { lineStyle: { color: '#263c51' } },
      data: portfolio.distribution.map((point) => point.bankroll),
    },
    yAxis: {
      type: 'value',
      name: '概率密度',
      nameTextStyle: { color: '#71879b' },
      axisLabel: { color: '#71879b' },
      splitLine: { lineStyle: { color: '#15283a' } },
    },
    series: [{
      type: 'bar',
      data: portfolio.distribution.map((point) => point.probability),
      barWidth: '82%',
      itemStyle: { color: '#3fc6b2' },
      markLine: {
        symbol: 'none',
        label: { color: '#a6bacb', formatter: '{b}' },
        lineStyle: { width: 1, type: 'dashed' },
        data: [
          { name: '5%分位', xAxis: portfolio.p05, lineStyle: { color: '#f06d72' } },
          { name: `初始${startingBankroll}`, xAxis: startingBankroll, lineStyle: { color: '#d8e2eb' } },
          { name: '中位数', xAxis: portfolio.median, lineStyle: { color: '#52d7c1' } },
          { name: '95%分位', xAxis: portfolio.p95, lineStyle: { color: '#a781ef' } },
        ],
      },
    }],
  }), [portfolio, startingBankroll])

  useEffect(() => {
    if (!chartRef.current) return
    let disposed = false
    let chart: { setOption: (value: unknown) => void; resize: () => void; dispose: () => void } | undefined
    const resize = () => chart?.resize()
    void loadECharts().then((echarts) => {
      if (disposed || !chartRef.current) return
      chart = echarts.init(chartRef.current)
      chart.setOption(option)
    })
    window.addEventListener('resize', resize)
    return () => {
      disposed = true
      window.removeEventListener('resize', resize)
      chart?.dispose()
    }
  }, [option])

  return (
    <section className="chart-panel panel">
      <div className="section-heading chart-heading">
        <div><h2>本金分布</h2><p>基于 100,000 次联合模拟</p></div>
        <div className="chart-summary">
          <span>盈利概率 <b>{percent(portfolio.profitProbability)}</b></span>
          <span>中位数 <b>{portfolio.median}元</b></span>
          <span>95%分位 <b>{portfolio.p95}元</b></span>
        </div>
      </div>
      <div ref={chartRef} className="bankroll-chart" />
      <div className="strategy-switch" aria-label="切换策略">
        {portfolios.map((item) => (
          <button className={item.key === portfolio.key ? 'active' : ''} onClick={() => onSelect(item.key)} key={item.key}>
            {item.name}
          </button>
        ))}
      </div>
    </section>
  )
}
