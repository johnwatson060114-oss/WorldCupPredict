import { useEffect, useRef, useState } from 'react'
import { CircleGauge, Crosshair, Download, Landmark, RefreshCw, Shield, Target, TrendingDown, TrendingUp, Upload, Zap } from 'lucide-react'
import { downloadLedger, currentBalance } from '../lib/ledger'
import { personalBalance } from '../features/personal-bets/storage'
import { money, percent, shortDateTime } from '../lib/format'
import type { BankrollLedger, StrategyKey } from '../types'
import type { PersonalBetLedger } from '../features/personal-bets/types'
import type { StrategyHistory } from '../features/personal-bets/types'

interface LedgerPageProps {
  ledger: BankrollLedger
  personalLedger: PersonalBetLedger
  onReset: () => void
  onImport: (ledger: BankrollLedger) => void
}

const STRATEGY_META: Record<StrategyKey, { name: string; color: string; icon: typeof Shield }> = {
  conservative: { name: '稳健', color: '#2a9fd9', icon: Shield },
  balanced: { name: '均衡', color: '#f0a030', icon: CircleGauge },
  aggressive: { name: '激进', color: '#e0556a', icon: Zap },
}

let echartsRuntime: Promise<typeof import('echarts/core')> | null = null
function loadECharts() {
  if (!echartsRuntime) {
    echartsRuntime = Promise.all([
      import('echarts/core'),
      import('echarts/charts'),
      import('echarts/components'),
      import('echarts/renderers'),
    ]).then(([core, charts, components, renderers]) => {
      core.use([charts.LineChart, components.GridComponent, components.LegendComponent, components.TooltipComponent, renderers.CanvasRenderer])
      return core
    })
  }
  return echartsRuntime
}

export function LedgerPage({ ledger, personalLedger, onReset, onImport }: LedgerPageProps) {
  const strategyBalance = currentBalance(ledger)
  const personalBalanceValue = personalBalance(personalLedger)
  const [history, setHistory] = useState<StrategyHistory | null>(null)
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<any>(null)

  useEffect(() => {
    fetch('./data/strategy-history.json', { cache: 'no-store' })
      .then((r) => r.ok ? r.json() as Promise<StrategyHistory> : null)
      .then(setHistory)
      .catch(() => setHistory(null))
  }, [])

  // Aggregate strategy stats from history
  const strategyStats = (history?.days ?? []).reduce((acc, day) => {
    for (const s of day.strategies) {
      const key = s.key as StrategyKey
      if (!acc[key]) acc[key] = { totalStake: 0, totalProfit: 0, days: 0, settledDays: 0, noBetDays: 0 }
      acc[key].totalStake += s.stake
      acc[key].totalProfit += (s.profit ?? 0)
      acc[key].days += 1
      if (s.status === 'settled') acc[key].settledDays += 1
      if (s.status === 'no-bet') acc[key].noBetDays += 1
    }
    return acc
  }, {} as Record<string, { totalStake: number; totalProfit: number; days: number; settledDays: number; noBetDays: number }>)

  // Model accuracy from reviews
  const allReviews = (history?.days ?? []).filter((d) => d.review?.summary)
  const overallAccuracy = allReviews.length
    ? allReviews.reduce((sum, d) => sum + (d.review!.summary.outcomeAccuracy), 0) / allReviews.length
    : null
  const overallLogLoss = allReviews.length
    ? allReviews.reduce((sum, d) => sum + (d.review!.summary.logLoss), 0) / allReviews.length
    : null
  const totalMatchReviews = allReviews.reduce((sum, d) => sum + (d.review!.summary.matchCount), 0)
  const correctOutcomes = allReviews.reduce((sum, d) => sum + Math.round((d.review!.summary.outcomeAccuracy) * (d.review!.summary.matchCount)), 0)

  // Cumulative profit data for chart
  const chartData = useChartData(history)

  // ECharts init
  useEffect(() => {
    if (!chartRef.current || !chartData.dates.length) return
    let cancelled = false
    loadECharts().then((core) => {
      if (cancelled || !chartRef.current) return
      if (!chartInstance.current) {
        chartInstance.current = core.init(chartRef.current, undefined, { renderer: 'canvas' })
      }
      const c = chartInstance.current
      c.setOption({
        tooltip: { trigger: 'axis' },
        legend: { bottom: 0, textStyle: { color: '#8899aa', fontSize: 12 } },
        grid: { left: 55, right: 20, top: 15, bottom: 35 },
        xAxis: { type: 'category', data: chartData.dates, axisLabel: { color: '#8899aa', fontSize: 11, rotate: 30 } },
        yAxis: { type: 'value', axisLabel: { color: '#8899aa', fontSize: 11, formatter: (v: number) => `${v}元` }, splitLine: { lineStyle: { color: '#1a3045' } } },
        series: (['conservative', 'balanced', 'aggressive'] as const).map((key) => ({
          name: STRATEGY_META[key].name,
          type: 'line',
          data: chartData.series[key],
          smooth: true,
          symbol: 'circle',
          symbolSize: 6,
          lineStyle: { color: STRATEGY_META[key].color, width: 2 },
          itemStyle: { color: STRATEGY_META[key].color },
        })),
      }, true)
    })
    return () => { cancelled = true }
  }, [chartData])

  const importFile = async (file: File | undefined) => {
    if (!file) return
    const parsed = JSON.parse(await file.text()) as BankrollLedger
    if (parsed.schemaVersion !== 1 || !Array.isArray(parsed.entries) || typeof parsed.initialBankroll !== 'number') {
      throw new Error('不支持的资金流水格式')
    }
    onImport(parsed)
  }

  return (
    <main className="content-page strategy-dashboard">
      <div className="page-title"><div><span>策略分析与资金看板</span><h1>三策略追踪</h1></div></div>

      {/* Strategy bankroll cards */}
      <section className="strategy-cards-grid">
        {(Object.entries(STRATEGY_META) as [StrategyKey, typeof STRATEGY_META['conservative']][]).map(([key, meta]) => {
          const Icon = meta.icon
          const stats = strategyStats[key] ?? { totalStake: 0, totalProfit: 0, days: 0, settledDays: 0, noBetDays: 0 }
          const roi = stats.totalStake > 0 ? stats.totalProfit / stats.totalStake : null
          const balance = 200 + stats.totalProfit
          return (
            <div className={`strategy-card ${key}`} key={key}>
              <div className="strategy-card-head">
                <Icon size={20} style={{ color: meta.color }} />
                <div><h3>{meta.name}</h3><small>{stats.noBetDays > 0 ? `${stats.noBetDays}天未投` : '每日投注'}</small></div>
              </div>
              <div className="strategy-card-body">
                <div><span>当前余额</span><strong style={{ color: balance >= 200 ? '#63d2b3' : '#e0556a' }}>{money(balance)}</strong></div>
                <div><span>累计盈亏</span><strong className={stats.totalProfit >= 0 ? 'positive-text' : 'negative-text'}>
                  {stats.totalProfit >= 0 ? '+' : ''}{money(stats.totalProfit)}
                  {stats.totalProfit < 0 ? <TrendingDown size={13} /> : stats.totalProfit > 0 ? <TrendingUp size={13} /> : null}
                </strong></div>
                <div><span>累计投入</span><strong>{money(stats.totalStake)}</strong></div>
                <div><span>ROI</span><strong>{roi !== null ? (roi >= 0 ? '+' : '') + (roi * 100).toFixed(1) + '%' : '--'}</strong></div>
                <div><span>记录天数</span><strong>{stats.days}天</strong></div>
              </div>
            </div>
          )
        })}
      </section>

      {/* Profit trend chart */}
      <section className="panel chart-panel">
        <div className="section-heading"><div><h2>累计盈亏趋势</h2><p>初始本金 200 元 · 按已结算赛果更新</p></div></div>
        <div className="chart-container" ref={chartRef} style={{ height: chartData.dates.length ? 260 : 80 }} />
        {!chartData.dates.length && <div className="chart-empty">暂无已结算数据。比赛结束后自动更新盈亏曲线。</div>}
      </section>

      {/* Model accuracy stats */}
      <section className="panel accuracy-panel">
        <div className="section-heading"><div><h2>模型准确率</h2><p>赛果方向预测 · 滚动累计</p></div><Crosshair size={18} /></div>
        <div className="accuracy-grid">
          <div><Target size={20} /><span>方向准确率</span><strong>{overallAccuracy !== null ? percent(overallAccuracy) : '--'}</strong><small>{correctOutcomes}/{totalMatchReviews} 场正确</small></div>
          <div><span>Log Loss</span><strong>{overallLogLoss !== null ? overallLogLoss.toFixed(4) : '--'}</strong><small>越低越好</small></div>
          <div><span>已结算场次</span><strong>{totalMatchReviews}</strong><small>含小组赛</small></div>
          <div><span>数据覆盖</span><strong>{(allReviews.length ? allReviews.reduce((s, d) => s + d.coverage, 0) / allReviews.length * 100 : 0).toFixed(0)}%</strong><small>阵容/赔率/天气</small></div>
        </div>
      </section>

      {/* Per-match review breakdown */}
      {allReviews.length > 0 && (
        <section className="panel review-panel">
          <div className="section-heading"><div><h2>每日复盘</h2><p>预测比分 vs 实际比分</p></div></div>
          {allReviews.map((day) => (
            <details className="review-day" key={day.targetDate}>
              <summary>
                <span>{day.targetDate}</span>
                <strong className={day.review!.summary.outcomeAccuracy >= 0.5 ? 'positive-text' : 'negative-text'}>
                  准确率 {percent(day.review!.summary.outcomeAccuracy)}
                </strong>
                <small>Log Loss {day.review!.summary.logLoss.toFixed(3)}</small>
              </summary>
              <div className="review-matches">
                {day.review!.matches.map((m) => (
                  <div className={`review-match ${m.outcomeCorrect ? 'correct' : 'wrong'}`} key={m.matchId}>
                    <span>{m.label}</span>
                    <em>预测 {m.predictedScore}</em>
                    <strong>实际 {m.actualScore}</strong>
                    <small>{m.diagnosis}</small>
                  </div>
                ))}
              </div>
            </details>
          ))}
        </section>
      )}

      {/* Personal + ledger info */}
      <section className="panel ledger-info-panel">
        <div className="section-heading"><div><h2>资金明细</h2><p>策略与个人投注本金独立管理</p></div></div>
        <div className="ledger-info-grid">
          <div><Landmark size={16} /><span>策略本金</span><strong>{money(strategyBalance)}</strong></div>
          <div><span>个人本金</span><strong>{money(personalBalanceValue)}</strong></div>
          <div><span>策略购买记录</span><strong>{ledger.entries.length} 次</strong></div>
          <div><span>个人投注记录</span><strong>{personalLedger.bets.length} 张</strong></div>
          <div className="ledger-actions">
            <button onClick={() => downloadLedger(ledger)}><Download size={14} />导出</button>
            <label className="file-button"><Upload size={14} />导入<input type="file" accept="application/json" onChange={(e) => void importFile(e.target.files?.[0])} /></label>
            <button onClick={onReset}><RefreshCw size={14} />清空</button>
          </div>
        </div>
        {ledger.entries.length > 0 && (
          <table className="ledger-table compact">
            <thead><tr><th>时间</th><th>日期</th><th>策略</th><th>投入</th><th>状态</th><th>余额</th></tr></thead>
            <tbody>
              {ledger.entries.slice(0, 10).map((entry) => (
                <tr key={entry.id}><td>{shortDateTime(entry.createdAt)}</td><td>{entry.targetDate}</td><td>{entry.strategy}</td><td>{entry.stake}元</td><td>{entry.status === 'settled' ? '✓ 已结算' : entry.status === 'pending' ? '⏳ 待结算' : entry.status}</td><td>{entry.closingBalance ?? '--'}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  )
}

function useChartData(history: StrategyHistory | null) {
  if (!history) return { dates: [] as string[], series: {} as Record<string, number[]> }
  const settled = history.days.filter((d) => d.strategies.some((s) => s.status === 'settled'))
  const dates = settled.map((d) => d.targetDate.slice(5))
  const series: Record<string, number[]> = { conservative: [], balanced: [], aggressive: [] }
  let balances: Record<string, number> = { conservative: 200, balanced: 200, aggressive: 200 }
  for (const day of settled) {
    for (const s of day.strategies) {
      if (s.status === 'settled') balances[s.key] = balances[s.key] + (s.profit ?? 0)
      series[s.key].push(balances[s.key])
    }
  }
  return { dates, series }
}
