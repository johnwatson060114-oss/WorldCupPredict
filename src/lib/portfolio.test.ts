import { describe, expect, it } from 'vitest'
import type { StrategyHistory } from '../features/personal-bets/types'
import type { Portfolio } from '../types'
import { filterCrossDayRecommendations, scalePortfolio, strategyRollingBankrolls } from './portfolio'

const portfolio = (stake: number): Portfolio => ({
  key: 'aggressive',
  name: '激进',
  subtitle: '',
  stake,
  retainedCash: 200 - stake,
  expectedProfit: 20,
  profitProbability: 0.4,
  lossProbability: 0.6,
  worstCase95: -stake,
  p05: 200 - stake,
  median: 200,
  p95: 240,
  maxPayout: 300,
  tickets: [{
    id: 'ticket',
    type: '3串1',
    stake,
    combinedOdds: 10,
    modelProbability: 0.1,
    robustExpectedReturn: 0.2,
    potentialPayout: stake * 10,
    legs: [{ matchId: 'm1', label: 'A vs B', market: '胜平负', selection: '胜', odds: 2 }],
  }],
  distribution: [{ bankroll: 200 - stake, probability: 1 }],
})

const singlePortfolio = (stake: number, combo = false): Portfolio => ({
  ...portfolio(stake),
  tickets: [{
    ...portfolio(stake).tickets[0],
    type: '单关',
    stake,
    legs: [portfolio(stake).tickets[0].legs[0]],
    comboGroup: combo ? {
      matchId: 'm1',
      market: portfolio(stake).tickets[0].legs[0].market,
      size: 2,
      coveragePct: 70,
    } : undefined,
  }],
})

describe('portfolio scaling', () => {
  it('removes a parlay made entirely from future matches', () => {
    const base = portfolio(12)
    base.tickets = [
      {
        ...base.tickets[0],
        id: 'future-only',
        stake: 10,
        legs: [
          { ...base.tickets[0].legs[0], matchId: 'm1', matchDate: '2026-06-20' },
          { ...base.tickets[0].legs[0], matchId: 'm2', matchDate: '2026-06-21' },
        ],
      },
      {
        ...base.tickets[0],
        id: 'current-day-anchor',
        stake: 2,
        legs: [
          { ...base.tickets[0].legs[0], matchId: 'm3', matchDate: '2026-06-19' },
          { ...base.tickets[0].legs[0], matchId: 'm4', matchDate: '2026-06-20' },
        ],
      },
    ]

    const filtered = filterCrossDayRecommendations(base, '2026-06-19')

    expect(filtered.tickets.map((ticket) => ticket.id)).toEqual(['current-day-anchor'])
    expect(filtered.stake).toBe(2)
    expect(filtered.retainedCash).toBe(198)
  })

  it('uses settled strategy performance to reduce the next stake', () => {
    const history: StrategyHistory = {
      generatedAt: 'now',
      finalDate: '2026-07-19',
      days: [{
        targetDate: '2026-06-17',
        generatedAt: 'before-match',
        coverage: 0.9,
        strategies: [{ key: 'aggressive', name: '激进', stake: 50, payout: 0, profit: -50, roi: -1, status: 'settled' }],
      }],
    }

    const bankrolls = strategyRollingBankrolls(history, '2026-06-18')
    const scaled = scalePortfolio(portfolio(42), bankrolls.aggressive)

    expect(bankrolls.aggressive).toBe(150)
    // Quadratic scaling: dr=0.75, stakeMult=0.5625
    // ticket stake = roundTicket(42 * 0.5625) = roundTicket(23.625) = 22
    expect(scaled.stake).toBe(22)
    expect(scaled.tickets[0].stake).toBe(22)
  })

  it('does not double-subtract the current target date', () => {
    const history: StrategyHistory = {
      generatedAt: 'now',
      finalDate: '2026-07-19',
      days: [{
        targetDate: '2026-06-18',
        generatedAt: 'before-match',
        coverage: 0.9,
        strategies: [{ key: 'aggressive', name: '激进', stake: 42, payout: null, profit: null, roi: null, status: 'pending' }],
      }],
    }

    expect(strategyRollingBankrolls(history, '2026-06-18').aggressive).toBe(200)
  })

  it('removes tickets once a strategy balance falls below one base stake', () => {
    const scaled = scalePortfolio(portfolio(42), 1.8)

    expect(scaled.stake).toBe(0)
    expect(scaled.tickets).toHaveLength(0)
  })

  it('drops an ordinary single when drawdown scaling puts it below ten yuan', () => {
    const scaled = scalePortfolio(singlePortfolio(10), 150)

    expect(scaled.stake).toBe(0)
    expect(scaled.tickets).toHaveLength(0)
  })

  it('applies minimum stakes even before any bankroll drawdown', () => {
    expect(scalePortfolio(singlePortfolio(8), 200).tickets).toHaveLength(0)
  })

  it('keeps a parlay at four yuan but drops it below four yuan', () => {
    expect(scalePortfolio(portfolio(8), 150).tickets[0].stake).toBe(4)
    expect(scalePortfolio(portfolio(6), 150).tickets).toHaveLength(0)
  })

  it('drops an incomplete same-match multi-result single as one atomic group', () => {
    const base = singlePortfolio(12, true)
    base.tickets = [
      { ...base.tickets[0], id: 'combo-a', stake: 12 },
      { ...base.tickets[0], id: 'combo-b', stake: 6 },
    ]

    const scaled = scalePortfolio(base, 150)

    expect(scaled.stake).toBe(0)
    expect(scaled.tickets).toHaveLength(0)
  })
})
