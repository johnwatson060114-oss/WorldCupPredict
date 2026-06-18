import { describe, expect, it } from 'vitest'
import type { DailyForecast, MatchForecast } from '../../types'
import { embeddedMatchDates, embeddedMatchesForDate, selectableMatchDates, ticketMatchDates } from './cross-day'
import type { PersonalBetLeg } from './types'

const match = (id: string, date: string): MatchForecast => ({
  id,
  lotteryCode: id,
  kickoff: `${date}T03:00:00+08:00`,
  kickoffBeijing: `${date}T03:00:00+08:00`,
  venue: '',
  homeTeam: `${id}主`,
  awayTeam: `${id}客`,
  homeFlag: '',
  awayFlag: '',
  expectedGoals: { home: 1, away: 1 },
  outcomeProbabilities: { home: .4, draw: .3, away: .3 },
  likelyScore: '1-1',
  scoreStars: 0,
  scoreProbabilities: [],
  coverage: .8,
  weather: '',
  altitude: 0,
  missingData: [],
  factors: [],
  quotes: [],
})

const forecast = {
  targetDate: '2026-06-18',
  matches: [match('a', '2026-06-18')],
  parlayMatches: [match('b', '2026-06-19'), match('c', '2026-06-20')],
} as DailyForecast

describe('cross-day personal tickets', () => {
  it('exposes embedded future match dates for manual selection', () => {
    expect(embeddedMatchDates(forecast)).toEqual(['2026-06-18', '2026-06-19', '2026-06-20'])
    expect(embeddedMatchesForDate(forecast, '2026-06-19').map((item) => item.id)).toEqual(['b'])
  })

  it('combines archived and embedded dates for backward and forward parlays', () => {
    expect(selectableMatchDates(forecast, ['2026-06-16', '2026-06-17', '2026-06-18']))
      .toEqual(['2026-06-16', '2026-06-17', '2026-06-18', '2026-06-19', '2026-06-20'])
  })

  it('derives every date represented on one ticket', () => {
    const legs: PersonalBetLeg[] = [
      { matchId: 'a', matchLabel: 'A', matchDate: '2026-06-18', market: '胜平负', selection: '胜', odds: 2 },
      { matchId: 'b', matchLabel: 'B', kickoffBeijing: '2026-06-20T03:00:00+08:00', market: '胜平负', selection: '负', odds: 3 },
    ]
    expect(ticketMatchDates(legs)).toEqual(['2026-06-18', '2026-06-20'])
  })
})
