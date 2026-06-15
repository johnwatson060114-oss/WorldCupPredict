import { AlertTriangle, DatabaseZap } from 'lucide-react'
import { shortDateTime } from '../lib/format'
import type { DailyForecast } from '../types'

interface StatusBarProps {
  forecast: DailyForecast
  bankroll: number
  onOpenDetails: () => void
}

export function StatusBar({ forecast, bankroll, onOpenDetails }: StatusBarProps) {
  const actualPaths = forecast.simulationQuality?.actualPaths ?? forecast.simulations
  const snapshot = forecast.dataSnapshot?.id.slice(0, 8) ?? '旧格式'
  return (
    <footer className="status-bar">
      <div><strong>当前本金 {bankroll}元</strong></div>
      <div><DatabaseZap size={14} />实际 {actualPaths.toLocaleString()} 条路径</div>
      <div>模型 {forecast.modelVersion} · 快照 {snapshot}</div>
      <div>本页数据更新：{shortDateTime(forecast.generatedAt)}</div>
      <button onClick={onOpenDetails}>查看投注明细</button>
      <div className="disclaimer"><AlertTriangle size={14} />情报不直接改概率、不代购；彩票有风险，不保证盈利</div>
    </footer>
  )
}
