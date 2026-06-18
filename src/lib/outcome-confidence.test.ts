import { describe, expect, it } from 'vitest'
import { effectiveRecommendation, getOutcomeDecision, isFormalCandidate } from './outcome-confidence'
import type { MarketQuote, MatchForecast } from '../types'

const match = (home: number, draw: number, away: number) => ({
  outcomeProbabilities: { home, draw, away },
} as MatchForecast)

const quote = {
  market: '胜平负',
  available: true,
  recommendation: '重点推荐',
} as MarketQuote

describe('outcome confidence gate', () => {
  it('recommends only when the highest outcome probability reaches 60%', () => {
    expect(getOutcomeDecision(match(0.60, 0.25, 0.15)).recommended).toBe(true)
    expect(getOutcomeDecision(match(0.59, 0.26, 0.15)).recommended).toBe(false)
  })

  it('downgrades low-confidence win-draw-loss quotes to watch', () => {
    expect(effectiveRecommendation(match(0.59, 0.26, 0.15), quote)).toBe('观察')
    expect(effectiveRecommendation(match(0.61, 0.24, 0.15), quote)).toBe('重点推荐')
  })

  it('respects backend formal eligibility and market-conflict blocks', () => {
    expect(isFormalCandidate(match(0.65, 0.20, 0.15), {
      ...quote,
      formalEligible: false,
      robustExpectedReturn: 0.5,
      marketConflict: {
        status: 'conflict',
        blocked: true,
        maxGap: 0.2,
        modelFavorite: '胜',
        marketFavorite: '负',
        reason: 'conflict',
      },
    })).toBe(false)
  })
})
