import type { Portfolio } from '../types'
import type { StrategyHistory } from '../features/personal-bets/types'

const roundTicket = (value: number) => Math.max(0, Math.floor(value / 2) * 2)
const strategyKeys = ['conservative', 'balanced', 'aggressive'] as const
const roundMoney = (value: number) => Math.round(value * 100) / 100

// --- Drawdown-aware scaling ---
// When a strategy is underwater (bankroll < initial), risk-of-ruin
// increases non-linearly.  Ticket stakes shrink quadratically (dr²)
// while portfolio-level metrics (p05, median, p95) still scale linearly
// because they represent absolute ending bankroll values.

const drawdownRatio = (bankroll: number, baseBankroll: number): number =>
  Math.max(0.001, bankroll / Math.max(baseBankroll, 1))

const stakeMultiplier = (dr: number): number =>
  Math.max(0.01, Math.min(1.0, dr * dr))

export const scalePortfolio = (portfolio: Portfolio, bankroll: number, baseBankroll = 200): Portfolio => {
  if (bankroll === baseBankroll) return portfolio
  const dr = drawdownRatio(bankroll, baseBankroll)
  const stakeMult = stakeMultiplier(dr)       // quadratic: bet sizing
  const ratio = dr                             // linear: outcome/payout scaling

  const tickets = portfolio.tickets.map((ticket) => {
    const stake = roundTicket(ticket.stake * stakeMult)
    return { ...ticket, stake, potentialPayout: Math.round(stake * ticket.combinedOdds * 100) / 100 }
  }).filter((ticket) => ticket.stake >= 2)
  const stake = tickets.reduce((sum, ticket) => sum + ticket.stake, 0)
  return {
    ...portfolio,
    tickets,
    stake,
    retainedCash: Math.max(0, bankroll - stake),
    expectedProfit: Math.round(portfolio.expectedProfit * ratio * 10) / 10,
    worstCase95: Math.round(portfolio.worstCase95 * ratio),
    p05: Math.round(portfolio.p05 * ratio),
    median: Math.round(portfolio.median * ratio),
    p95: Math.round(portfolio.p95 * ratio),
    maxPayout: Math.round(portfolio.maxPayout * ratio),
    distribution: portfolio.distribution.map((point) => ({
      bankroll: Math.round(point.bankroll * ratio),
      probability: point.probability,
    })),
  }
}

export const strategyRollingBankrolls = (
  history: StrategyHistory | null,
  targetDate: string,
  initialBankroll = 200,
): Record<Portfolio['key'], number> => {
  const balances = Object.fromEntries(strategyKeys.map((key) => [key, initialBankroll])) as Record<Portfolio['key'], number>
  const days = (history?.days ?? [])
    .filter((day) => day.targetDate < targetDate)
    .sort((left, right) => left.targetDate.localeCompare(right.targetDate))

  for (const day of days) {
    for (const key of strategyKeys) {
      const balance = balances[key]
      if (balance < 2) continue
      const strategy = day.strategies.find((item) => item.key === key)
      if (!strategy) continue
      const scale = balance / initialBankroll
      if (strategy.status === 'settled' && strategy.profit !== null) {
        balances[key] = Math.max(0, balance + strategy.profit * scale)
      } else if (strategy.status === 'pending') {
        balances[key] = Math.max(0, balance - strategy.stake * scale)
      }
      balances[key] = roundMoney(balances[key])
    }
  }

  return balances
}
