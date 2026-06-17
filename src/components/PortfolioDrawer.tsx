import { CheckCircle2, X } from 'lucide-react'
import { money, percent, shortDateTime, signedPercent } from '../lib/format'
import type { Portfolio } from '../types'

interface PortfolioDrawerProps {
  open: boolean
  portfolio: Portfolio
  onClose: () => void
  onConfirm: () => void
}

export function PortfolioDrawer({ open, portfolio, onClose, onConfirm }: PortfolioDrawerProps) {
  if (!open) return null
  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside className="portfolio-drawer" onMouseDown={(event) => event.stopPropagation()}>
        <div className="drawer-head"><div><span>{portfolio.name}方案</span><h2>投注明细与风险</h2></div><button onClick={onClose} aria-label="关闭"><X /></button></div>
        <div className="drawer-summary"><div><span>投入</span><strong>{money(portfolio.stake)}</strong></div><div><span>期望盈利</span><strong className="positive-text">{money(portfolio.expectedProfit)}</strong></div><div><span>盈利概率</span><strong>{percent(portfolio.profitProbability)}</strong></div><div><span>5%分位</span><strong>{portfolio.p05}元</strong></div></div>
        <div className="drawer-tickets">
          {portfolio.tickets.map((ticket) => <article key={ticket.id}><div><span>{ticket.type}</span><strong>{ticket.stake}元</strong></div>{ticket.legs.map((leg) => {
            const kickoff = leg.kickoffBeijing ? shortDateTime(leg.kickoffBeijing) : ''
            const prefix = [leg.lotteryCode, kickoff].filter(Boolean).join(' · ')
            return <p key={`${ticket.id}-${leg.matchId}-${leg.selection}`}>{prefix ? `${prefix} · ` : ''}{leg.label} · {leg.market} {leg.selection} @{leg.odds.toFixed(2)}</p>
          })}<footer><span>组合奖金 {ticket.combinedOdds.toFixed(2)}</span><span>稳健期望 {signedPercent(ticket.robustExpectedReturn)}</span><span>最高返还 {ticket.potentialPayout.toFixed(0)}元</span></footer></article>)}
        </div>
        <div className="drawer-warning">确认只会把本方案写入本机资金流水，不会向体彩网站发送数据或完成购买。</div>
        <button className="confirm-button" onClick={onConfirm}><CheckCircle2 size={17} />确认我实际购买了此方案</button>
      </aside>
    </div>
  )
}
