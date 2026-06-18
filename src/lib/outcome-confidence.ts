import type { MarketQuote, MatchForecast, Outcome, Recommendation } from '../types'

export const OUTCOME_RECOMMENDATION_THRESHOLD = 0.60

const outcomeLabels: Record<Outcome, string> = {
  home: '胜',
  draw: '平',
  away: '负',
}

export interface OutcomeDecision {
  threshold: number
  probability: number
  outcome: Outcome
  label: string
  recommended: boolean
}

export const getOutcomeDecision = (match: MatchForecast): OutcomeDecision => {
  const entries = Object.entries(match.outcomeProbabilities) as Array<[Outcome, number]>
  const [outcome, probability] = entries.reduce((best, current) => current[1] > best[1] ? current : best)
  const threshold = match.outcomeDecision?.threshold ?? OUTCOME_RECOMMENDATION_THRESHOLD

  return {
    threshold,
    probability,
    outcome,
    label: outcomeLabels[outcome],
    recommended: probability >= threshold,
  }
}

export const effectiveRecommendation = (match: MatchForecast, quote: MarketQuote): Recommendation => {
  if (quote.market === '胜平负' && quote.available && !getOutcomeDecision(match).recommended) return '观察'
  return quote.recommendation
}

export const isFormalCandidate = (match: MatchForecast, quote: MarketQuote) => {
  if (typeof quote.formalEligible === 'boolean') return quote.formalEligible
  const recommendation = effectiveRecommendation(match, quote)
  return quote.available
    && quote.robustExpectedReturn !== null
    && quote.robustExpectedReturn > 0
    && (recommendation === '重点推荐' || recommendation === '小注可选')
}
