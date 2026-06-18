import type { DailyForecast, MatchForecast } from '../../types'
import type { PersonalBetLeg } from './types'

export const matchDate = (match: Pick<MatchForecast, 'kickoffBeijing'>) =>
  match.kickoffBeijing.slice(0, 10)

export const legMatchDate = (leg: PersonalBetLeg) =>
  leg.matchDate ?? leg.kickoffBeijing?.slice(0, 10)

export const embeddedMatches = (forecast: DailyForecast) => {
  const matches = new Map<string, MatchForecast>()
  for (const match of [...forecast.matches, ...(forecast.parlayMatches ?? [])]) {
    matches.set(match.id, match)
  }
  return [...matches.values()]
}

export const embeddedMatchDates = (forecast: DailyForecast) =>
  [...new Set(embeddedMatches(forecast).map(matchDate))].sort()

export const embeddedMatchesForDate = (forecast: DailyForecast, targetDate: string) =>
  embeddedMatches(forecast).filter((match) => matchDate(match) === targetDate)

export const ticketMatchDates = (legs: PersonalBetLeg[]) =>
  [...new Set(legs.map(legMatchDate).filter((date): date is string => Boolean(date)))].sort()

