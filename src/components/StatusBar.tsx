import { AlertTriangle, DatabaseZap } from 'lucide-react'
import { shortDateTime } from '../lib/format'
import type { DailyForecast } from '../types'

interface StatusBarProps {
  forecast: DailyForecast
  bankroll: number
  onOpenDetails: () => void
}

export function StatusBar({ forecast, bankroll, onOpenDetails }: StatusBarProps) {
  return (
    <footer className="status-bar">
      <div><strong>当前本金 {bankroll}元</strong></div>
      <div><DatabaseZap size={14} />{forecast.simulations.toLocaleString()} 次联合模拟</div>
      <div>赔率超过 45 分钟需重算</div>
      <div>本页数据更新：{shortDateTime(forecast.generatedAt)}</div>
      <button onClick={onOpenDetails}>查看投注明细</button>
      <div className="disclaimer"><AlertTriangle size={14} />不调用大模型、不代购；彩票有风险，不保证盈利</div>
    </footer>
  )
}
