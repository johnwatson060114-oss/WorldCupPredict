import { describe, expect, it } from 'vitest'
import type { MarketQuote, MatchForecast } from '../types'
import { summarizeTotalGoals } from './TotalGoalsPage'

const probabilities = [0.08, 0.2, 0.25, 0.22, 0.14, 0.07, 0.03, 0.01]
const lowCoreTailProbabilities = [0.1514, 0.28176, 0.26837, 0.17098, 0.0821, 0.03146, 0.01007, 0.00386]
const selections = ['0', '1', '2', '3', '4', '5', '6', '7+']

const quote = (selection: string, index: number, available = false, sourceProbabilities = probabilities): MarketQuote => ({
  id: `m-总进球数-${selection}`,
  matchId: 'm',
  market: '总进球数',
  selection,
  odds: available ? 4 : null,
  modelProbability: sourceProbabilities[index],
  marketProbability: available ? 0.2 : null,
  rawExpectedReturn: available ? sourceProbabilities[index] * 4 - 1 : null,
  robustExpectedReturn: available ? sourceProbabilities[index] * 3.8 - 1 : null,
  singleEligible: available,
  available,
  recommendation: available ? '小注可选' : '未开售',
  reason: available ? '测试赔率' : '官方固定奖金未开售',
  observedAt: '2026-06-15T22:00:00+08:00',
})

const match = (available = false, sourceProbabilities = probabilities) => ({
  id: 'm',
  expectedGoals: { home: 2.4, away: 0.15 },
  knockoutContext: { round: 'round_of_16' },
  quotes: selections.map((selection, index) => quote(selection, index, available, sourceProbabilities)),
}) as unknown as MatchForecast

describe('summarizeTotalGoals', () => {
  it('finds the peak, strongest adjacent interval, and fixed risk zones', () => {
    const summary = summarizeTotalGoals(match())

    expect(summary.peak.selection).toBe('2')
    expect(summary.core).toEqual({ label: '2–3球', selections: ['2', '3'], probability: 0.47 })
    expect(summary.boundaryRisk.triggered).toBe(true)
    expect(summary.boundaryRisk.adjacentSelection).toBe('1')
    expect(summary.zones.map((zone) => zone.probability)).toEqual([0.28, 0.47, 0.25])
    expect(summary.marketAvailable).toBe(false)
    expect(summary.bestValue).toBeNull()
  })

  it('uses the generated two-bucket core interval when present', () => {
    const summary = summarizeTotalGoals({
      ...match(),
      totalGoalsCore: {
        policy: 'strongest_adjacent_two_bucket_v1',
        label: '1-2',
        selections: ['1', '2'],
        probability: 0.51,
      },
    })

    expect(summary.core).toEqual({ label: '1-2', selections: ['1', '2'], probability: 0.51 })
  })

  it('uses the generated boundary risk when present', () => {
    const summary = summarizeTotalGoals({
      ...match(),
      totalGoalsBoundaryRisk: {
        policy: 'two_bucket_boundary_watch_v1',
        triggered: true,
        level: 'watch',
        coreProbability: 0.51,
        adjacentSelection: '3',
        adjacentProbability: 0.2,
        thresholds: {
          maxCoreProbability: 0.52,
          minAdjacentProbability: 0.18,
        },
        reason: 'adjacent_bucket_near_low_confidence_core',
      },
    })

    expect(summary.boundaryRisk.triggered).toBe(true)
    expect(summary.boundaryRisk.adjacentSelection).toBe('3')
    expect(summary.boundaryRisk.adjacentProbability).toBe(0.2)
  })

  it('uses the generated tail risk when present', () => {
    const summary = summarizeTotalGoals({
      ...match(),
      totalGoalsTailRisk: {
        policy: 'low_core_far_tail_watch_v1',
        triggered: true,
        level: 'tail_watch',
        coreProbability: 0.55,
        threeProbability: 0.17,
        fourPlusProbability: 0.13,
        watchSelections: ['4', '5', '6', '7+'],
        thresholds: {
          maxLowCoreProbability: 0.56,
          minThreeProbability: 0.17,
          minFourPlusProbability: 0.12,
        },
        reason: 'low_core_with_near_three_and_tail_mass',
      },
    })

    expect(summary.tailRisk.triggered).toBe(true)
    expect(summary.tailRisk.level).toBe('tail_watch')
    expect(summary.tailRisk.fourPlusProbability).toBe(0.13)
  })

  it('locally marks a low-core far-tail watch for older forecast payloads', () => {
    const summary = summarizeTotalGoals(match(false, lowCoreTailProbabilities))

    expect(summary.core.selections).toEqual(['1', '2'])
    expect(summary.core.probability).toBe(0.55013)
    expect(summary.tailRisk.triggered).toBe(true)
    expect(summary.tailRisk.threeProbability).toBe(0.17098)
    expect(summary.tailRisk.fourPlusProbability).toBeCloseTo(0.12749)
  })

  it('only enables market evaluation when usable odds and market probability exist', () => {
    const summary = summarizeTotalGoals(match(true))

    expect(summary.marketAvailable).toBe(true)
    expect(summary.bestValue?.selection).toBe('2')
  })
})
