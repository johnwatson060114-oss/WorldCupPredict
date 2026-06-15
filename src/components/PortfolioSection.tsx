import { Check, ChevronRight, CircleGauge, Shield, Sparkles, Zap } from 'lucide-react'
import { money, percent } from '../lib/format'
import type { Portfolio, StrategyKey } from '../types'

interface PortfolioSectionProps {
  bankroll: number
  portfolios: Portfolio[]
  emptyReason: string
  selected: StrategyKey
  onSelect: (key: StrategyKey) => void
  onOpenDetails: () => void
}

const icons = { conservative: Shield, balanced: CircleGauge, aggressive: Zap }

export function PortfolioSection({ bankroll, portfolios, emptyReason, selected, onSelect, onOpenDetails }: PortfolioSectionProps) {
  return (
    <section className="portfolio-section panel">
      <div className="section-heading portfolio-heading">
        <div>
          <h2>{bankroll}元滚动本金 · 三套方案</h2>
          <p>金额按 2 元离散化；可以保留现金，不要求每天花完</p>
        </div>
        <button className="text-button" onClick={onOpenDetails}>查看投注明细 <ChevronRight size={15} /></button>
      </div>
      <div className="portfolio-grid">
        {portfolios.map((portfolio) => {
          const Icon = icons[portfolio.key]
          const active = selected === portfolio.key
          return (
            <button
              className={`portfolio-card ${portfolio.key} ${active ? 'selected' : ''}`}
              onClick={() => onSelect(portfolio.key)}
              key={portfolio.key}
            >
              <div className="portfolio-title">
                <span><Icon size={17} /></span>
                <div><h3>{portfolio.name}</h3><small>{portfolio.subtitle}</small></div>
                {active && <Check size={16} />}
              </div>
              <div className="portfolio-metrics">
                <div><span>本次投入</span><strong>{money(portfolio.stake)}</strong></div>
                <div><span>保留现金</span><strong>{money(portfolio.retainedCash)}</strong></div>
                <div><span>模型期望盈利</span><strong className="positive-text">{money(portfolio.expectedProfit)}</strong></div>
                <div><span>盈利概率</span><strong>{percent(portfolio.profitProbability)}</strong></div>
                <div><span>95%最差情景</span><strong className="negative-text">{money(portfolio.worstCase95)}</strong></div>
              </div>
              <div className="ticket-list">
                {!!portfolio.strategyRules?.length && (
                  <div className="strategy-rules">
                    {portfolio.strategyRules.map((rule) => <span key={rule}>{rule}</span>)}
                  </div>
                )}
                {portfolio.tickets.slice(0, 4).map((ticket) => (
                  <div key={ticket.id}>
                    <span>{ticket.type}</span>
                    <p>{ticket.legs.map((leg) => leg.label).join(' × ')}</p>
                    <strong>{ticket.stake}元</strong>
                  </div>
                ))}
                {portfolio.tickets.length === 0 && (
                  <div className="empty-ticket"><Sparkles size={14} /><span><b>当前没有正式下注</b><small>{emptyReason}</small></span></div>
                )}
              </div>
            </button>
          )
        })}
      </div>
    </section>
  )
}
