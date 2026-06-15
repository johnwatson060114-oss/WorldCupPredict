import type { DailyForecast, MatchSettlement, SettlementFile } from '../../types'
import type { ModelDaySnapshot, PersonalBet, PersonalBetLedger, PersonalBetLeg } from './types'
import { groupLegsByMatch, inferPassType, payoutForWinningOdds } from './pass-types'

const STORAGE_KEY = 'world-cup-predict-personal-bets-v1'
const standardScores = new Set(['1:0', '2:0', '2:1', '3:0', '3:1', '3:2', '4:0', '4:1', '4:2', '5:0', '5:1', '5:2', '0:0', '1:1', '2:2', '3:3', '0:1', '0:2', '1:2', '0:3', '1:3', '2:3', '0:4', '1:4', '2:4', '0:5', '1:5', '2:5'])

export const emptyPersonalLedger = (): PersonalBetLedger => ({
  schemaVersion: 1,
  initialBankroll: 200,
  bets: [],
  modelSnapshots: [],
})

export const loadPersonalLedger = (): PersonalBetLedger => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return emptyPersonalLedger()
    const parsed = JSON.parse(raw) as PersonalBetLedger
    return parsed.schemaVersion === 1 && Array.isArray(parsed.bets) && Array.isArray(parsed.modelSnapshots)
      ? parsed
      : emptyPersonalLedger()
  } catch {
    return emptyPersonalLedger()
  }
}

export const savePersonalLedger = (ledger: PersonalBetLedger) => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(ledger))
}

export const upsertPersonalBet = (ledger: PersonalBetLedger, bet: PersonalBet) => {
  const exists = ledger.bets.some((item) => item.id === bet.id)
  const bets = exists
    ? ledger.bets.map((item) => item.id === bet.id ? bet : item)
    : [bet, ...ledger.bets]
  const next = { ...ledger, bets }
  savePersonalLedger(next)
  return next
}

export const deletePersonalBet = (ledger: PersonalBetLedger, id: string) => {
  const next = { ...ledger, bets: ledger.bets.filter((item) => item.id !== id) }
  savePersonalLedger(next)
  return next
}

export const captureModelSnapshot = (ledger: PersonalBetLedger, forecast: DailyForecast) => {
  if (ledger.modelSnapshots.some((item) => item.targetDate === forecast.targetDate)) return ledger
  const snapshot: ModelDaySnapshot = {
    targetDate: forecast.targetDate,
    generatedAt: forecast.generatedAt,
    coverage: forecast.overallCoverage,
    portfolios: forecast.portfolios,
  }
  const next = { ...ledger, modelSnapshots: [...ledger.modelSnapshots, snapshot] }
  savePersonalLedger(next)
  return next
}

const legWon = (leg: PersonalBetLeg, result: MatchSettlement) => {
  if (leg.market === '比分') {
    const score = `${result.homeScore}:${result.awayScore}`
    if (leg.selection === score || leg.selection === score.replace(':', '-')) return true
    if (standardScores.has(score)) return false
    const outcome = result.homeScore > result.awayScore ? '胜其它' : result.homeScore === result.awayScore ? '平其它' : '负其它'
    return leg.selection === outcome
  }
  if (leg.market === '总进球数') {
    const total = result.homeScore + result.awayScore
    return leg.selection === (total >= 7 ? '7+' : String(total))
  }
  if (leg.market === '半全场') {
    if (result.halfTimeHomeScore === null || result.halfTimeHomeScore === undefined || result.halfTimeAwayScore === null || result.halfTimeAwayScore === undefined) return null
    const half = result.halfTimeHomeScore > result.halfTimeAwayScore ? '胜' : result.halfTimeHomeScore === result.halfTimeAwayScore ? '平' : '负'
    const full = result.homeScore > result.awayScore ? '胜' : result.homeScore === result.awayScore ? '平' : '负'
    return leg.selection === `${half}${full}`
  }
  const handicapMatch = leg.selection.match(/^([+-]\d+)\s+(胜|平|负)$/)
  const handicap = handicapMatch ? Number(handicapMatch[1]) : 0
  const selection = handicapMatch?.[2] ?? leg.selection
  const adjustedHome = result.homeScore + handicap
  const outcome = adjustedHome > result.awayScore ? '胜' : adjustedHome === result.awayScore ? '平' : '负'
  return selection === outcome
}

const calculateBetPayout = (bet: PersonalBet, results: Map<string, MatchSettlement>) => {
  const legs = bet.legs?.length ? bet.legs : bet.matchId && bet.market !== '自定义' && bet.market !== '混合过关'
    ? [{ matchId: bet.matchId, matchLabel: bet.matchLabel, market: bet.market, selection: bet.selection, odds: bet.odds }]
    : []
  if (!legs.length) return null
  const groups = groupLegsByMatch(legs)
  const winningOddsByMatch: number[] = []
  for (const group of groups) {
    const result = results.get(group.matchId)
    if (!result) return null
    let winningOdds = 0
    for (const leg of group.legs) {
      const won = legWon(leg, result)
      if (won === null) return null
      if (won) winningOdds += leg.odds
    }
    winningOddsByMatch.push(winningOdds)
  }
  const passType = bet.passType ?? inferPassType(groups.length)
  const multiple = bet.multiple ?? Math.max(1, Math.round(bet.stake / 2))
  return payoutForWinningOdds(winningOddsByMatch, passType, multiple)
}

export const settlePersonalLedger = (ledger: PersonalBetLedger, settlementFile: SettlementFile) => {
  const results = new Map(settlementFile.matches.map((match) => [match.matchId, match]))
  let changed = false
  const bets = ledger.bets.map((bet) => {
    if (bet.status !== 'pending') return bet
    const payout = calculateBetPayout(bet, results)
    if (payout === null) return bet
    const matchIds = bet.legs?.map((leg) => leg.matchId) ?? (bet.matchId ? [bet.matchId] : [])
    const settledAt = matchIds.map((matchId) => results.get(matchId)?.settledAt).filter(Boolean).sort().at(-1)
    changed = true
    return {
      ...bet,
      status: 'settled' as const,
      payout,
      settledAt,
    }
  })
  if (!changed) return ledger
  const next = { ...ledger, bets }
  savePersonalLedger(next)
  return next
}

export const personalBalance = (ledger: PersonalBetLedger) => {
  const settledNet = ledger.bets.reduce((sum, bet) => bet.status === 'settled' ? sum + (bet.payout ?? 0) - bet.stake : sum, 0)
  const pending = ledger.bets.reduce((sum, bet) => bet.status === 'pending' ? sum + bet.stake : sum, 0)
  return Math.max(0, ledger.initialBankroll + settledNet - pending)
}

export const exportPersonalLedger = (ledger: PersonalBetLedger) => {
  const blob = new Blob([JSON.stringify(ledger, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'world-cup-personal-bets.json'
  anchor.click()
  URL.revokeObjectURL(url)
}
