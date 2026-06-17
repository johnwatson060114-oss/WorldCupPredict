import { describe, expect, it } from 'vitest'
import type { StrategyHistory } from '../features/personal-bets/types'
import type { Portfolio } from '../types'
import { scalePortfolio, strategyRollingBankrolls } from './portfolio'

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

describe('portfolio scaling', () => {
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
    expect(scaled.stake).toBe(30)
    expect(scaled.tickets[0].stake).toBe(30)
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
})
