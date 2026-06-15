import { describe, expect, it } from 'vitest'
import { payoutForWinningOdds, stakeForPass, theoreticalMaxPayout, ticketCountForPass } from './pass-types'
import type { PersonalBetLeg } from './types'

const leg = (matchId: string, odds = 2, selection = '胜'): PersonalBetLeg => ({
  matchId,
  matchLabel: `${matchId} 主队 vs 客队`,
  market: '胜平负',
  selection,
  odds,
})

describe('official football pass types', () => {
  it('keeps 4串1 as one four-match base ticket', () => {
    const legs = ['a', 'b', 'c', 'd'].map((id) => leg(id))
    expect(ticketCountForPass(legs, '4串1')).toBe(1)
    expect(stakeForPass(legs, '4串1', 3)).toBe(6)
    expect(theoreticalMaxPayout(legs, '4串1', 1)).toBe(32)
  })

  it('splits 4串11 into six doubles, four triples and one fourfold', () => {
    const legs = ['a', 'b', 'c', 'd'].map((id) => leg(id))
    expect(ticketCountForPass(legs, '4串11')).toBe(11)
    expect(stakeForPass(legs, '4串11', 1)).toBe(22)
  })

  it('counts multiple selections in one match as separate base tickets', () => {
    const legs = [leg('a'), leg('a', 3, '平'), leg('b'), leg('c'), leg('d')]
    expect(ticketCountForPass(legs, '4串11')).toBe(18)
  })

  it('pays the winning child tickets even when one leg of 4串11 loses', () => {
    expect(payoutForWinningOdds([2, 2, 2, 0], '4串11', 1)).toBe(40)
  })
})
