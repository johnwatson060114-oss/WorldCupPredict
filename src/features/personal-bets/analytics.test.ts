import { describe, expect, it } from 'vitest'
import type { Portfolio } from '../../types'
import { actualStrategyPerformance, buildFairComparison, personalSummary, projectToFinal } from './analytics'
import type { PersonalBetLedger, StrategyHistory } from './types'

const ledger: PersonalBetLedger = {
  schemaVersion: 1,
  initialBankroll: 200,
  modelSnapshots: [],
  bets: [
    { id: 'a', createdAt: 'now', targetDate: '2026-06-15', matchLabel: 'A vs B', market: '胜平负', selection: '胜', odds: 2, stake: 10, decisionSource: 'subjective', status: 'settled', payout: 20 },
    { id: 'b', createdAt: 'now', targetDate: '2026-06-16', matchLabel: 'C vs D', market: '胜平负', selection: '负', odds: 2, stake: 10, decisionSource: 'balanced', status: 'settled', payout: 0 },
  ],
}

const history: StrategyHistory = {
  generatedAt: 'now',
  finalDate: '2026-07-19',
  days: [{
    targetDate: '2026-06-15',
    generatedAt: 'before-match',
    coverage: 0.9,
    strategies: [{ key: 'balanced', name: '均衡', stake: 20, payout: 24, profit: 4, roi: 0.2, status: 'settled' }],
  }],
}

describe('personal betting analytics', () => {
  it('starts the personal summary from the manually provided baseline', () => {
    const result = personalSummary({
      schemaVersion: 1,
      initialBankroll: 0,
      baselineStake: 985,
      baselineProfit: 153.54,
      modelSnapshots: [],
      bets: [],
    })
    expect(result.totalStaked).toBe(985)
    expect(result.realizedProfit).toBe(153.54)
    expect(result.pendingExposure).toBe(0)
  })

  it('compares only the intersection of settled betting days by default', () => {
    const result = buildFairComparison(ledger, history, 'matched')
    expect(result.matchedDays).toBe(1)
    expect(result.userDays).toBe(1)
    expect(result.userRoi).toBe(1)
    expect(result.modelRoi).toBe(0.2)
  })

  it('stops every strategy path once the balance falls below one ticket', () => {
    const portfolio = (key: Portfolio['key']): Portfolio => ({
      key, name: key, subtitle: '', stake: 200, retainedCash: 0, expectedProfit: -200,
      profitProbability: 0, lossProbability: 1, worstCase95: 0, p05: 0, median: 0, p95: 0,
      maxPayout: 0, tickets: [], distribution: [{ bankroll: 0, probability: 1 }],
    })
    const result = projectToFinal([portfolio('conservative'), portfolio('balanced'), portfolio('aggressive')], null, { ...ledger, bets: [] }, '2026-07-18', 20)
    expect(result.summaries.every((item) => item.stopProbability === 1)).toBe(true)
    expect(result.summaries.every((item) => item.median === 0)).toBe(true)
  })

  it('shows actual strategy profit only from settled days and rolls the balance', () => {
    const actual = actualStrategyPerformance(history)
    const balanced = actual.summaries.find((item) => item.key === 'balanced')!
    expect(balanced.settledDays).toBe(1)
    expect(balanced.balance).toBe(204)
    expect(balanced.profit).toBe(4)
    expect(actual.pendingDays).toBe(0)
  })
})
