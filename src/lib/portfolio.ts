import type { Portfolio } from '../types'
import type { StrategyHistory } from '../features/personal-bets/types'

const roundTicket = (value: number) => Math.max(0, Math.floor(value / 2) * 2)
const strategyKeys = ['conservative', 'balanced', 'aggressive'] as const
const roundMoney = (value: number) => Math.round(value * 100) / 100
const MIN_SINGLE_STAKE = 10
const MIN_COMBO_SELECTION_STAKE = 6
const MIN_COMBO_TOTAL_STAKE = 10
const MIN_PARLAY_STAKE = 4

const minimumTicketStake = (ticket: Portfolio['tickets'][number]) => {
  if (ticket.comboGroup && ticket.comboGroup.size > 1) return MIN_COMBO_SELECTION_STAKE
  if (ticket.legs.length > 1 || ticket.type.includes('串')) return MIN_PARLAY_STAKE
  return MIN_SINGLE_STAKE
}

const keepCompleteComboGroups = (tickets: Portfolio['tickets']) => {
  const grouped = new Map<string, Portfolio['tickets']>()
  for (const ticket of tickets) {
    if (!ticket.comboGroup || ticket.comboGroup.size <= 1) continue
    const key = `${ticket.comboGroup.matchId}:${ticket.comboGroup.market}`
    grouped.set(key, [...(grouped.get(key) ?? []), ticket])
  }

  const invalidGroups = new Set(
    [...grouped.entries()]
      .filter(([, group]) =>
        group.length !== group[0].comboGroup?.size
        || group.reduce((sum, ticket) => sum + ticket.stake, 0) < MIN_COMBO_TOTAL_STAKE,
      )
      .map(([key]) => key),
  )

  return tickets.filter((ticket) => {
    if (!ticket.comboGroup || ticket.comboGroup.size <= 1) return true
    return !invalidGroups.has(`${ticket.comboGroup.matchId}:${ticket.comboGroup.market}`)
  })
}

export const filterCrossDayRecommendations = (
  portfolio: Portfolio,
  targetDate: string,
  bankroll = 200,
): Portfolio => {
  const tickets = portfolio.tickets.filter((ticket) =>
    ticket.legs.length < 2 || ticket.legs.some((leg) => leg.matchDate === targetDate),
  )
  if (tickets.length === portfolio.tickets.length) return portfolio

  const stake = tickets.reduce((sum, ticket) => sum + ticket.stake, 0)
  return {
    ...portfolio,
    tickets,
    stake,
    retainedCash: Math.max(0, bankroll - stake),
    maxPayout: tickets.reduce((maximum, ticket) => Math.max(maximum, ticket.potentialPayout), 0),
  }
}

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
  const dr = drawdownRatio(bankroll, baseBankroll)
  const stakeMult = stakeMultiplier(dr)       // quadratic: bet sizing
  const ratio = dr                             // linear: outcome/payout scaling

  const scaledTickets = portfolio.tickets.map((ticket) => {
    const stake = roundTicket(ticket.stake * stakeMult)
    return { ...ticket, stake, potentialPayout: Math.round(stake * ticket.combinedOdds * 100) / 100 }
  }).filter((ticket) => ticket.stake >= minimumTicketStake(ticket))
  const tickets = keepCompleteComboGroups(scaledTickets)
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
