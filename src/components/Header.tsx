import { Activity, Clock3, Database, Trophy } from 'lucide-react'
import { shortDateTime } from '../lib/format'
import type { DailyForecast } from '../types'

export type NavKey = 'today' | 'analysis' | 'personal' | 'ledger' | 'backtest' | 'method'

interface HeaderProps {
  forecast: DailyForecast
  active: NavKey
  onNavigate: (key: NavKey) => void
}

const navItems: Array<{ key: NavKey; label: string }> = [
  { key: 'today', label: '今日方案' },
  { key: 'analysis', label: '比赛分析' },
  { key: 'personal', label: '我的投注' },
  { key: 'ledger', label: '资金记录' },
  { key: 'backtest', label: '回测' },
  { key: 'method', label: '模型方法' },
]

export function Header({ forecast, active, onNavigate }: HeaderProps) {
  return (
    <header className="topbar">
      <button className="brand" onClick={() => onNavigate('today')} aria-label="返回今日方案">
        <span className="brand-mark"><Trophy size={20} /></span>
        <span>世界杯比赛推演</span>
      </button>
      <nav className="primary-nav" aria-label="主导航">
        {navItems.map((item) => (
          <button
            key={item.key}
            className={active === item.key ? 'nav-item active' : 'nav-item'}
            onClick={() => onNavigate(item.key)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <div className="top-status">
        <span><Clock3 size={14} />赔率快照 {shortDateTime(forecast.generatedAt)}</span>
        <span className={forecast.oddsFreshMinutes <= 45 ? 'ok' : 'warning'}>
          <Activity size={14} />新鲜度 {forecast.oddsFreshMinutes} 分钟
        </span>
        <span><Database size={14} />覆盖 {Math.round(forecast.overallCoverage * 100)}%</span>
      </div>
    </header>
  )
}
