import type { Portfolio } from '../types'

const roundTicket = (value: number) => Math.max(0, Math.floor(value / 2) * 2)

export const scalePortfolio = (portfolio: Portfolio, bankroll: number, baseBankroll = 200): Portfolio => {
  if (bankroll === baseBankroll) return portfolio
  const ratio = bankroll / baseBankroll
  const tickets = portfolio.tickets.map((ticket) => {
    const stake = roundTicket(ticket.stake * ratio)
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
