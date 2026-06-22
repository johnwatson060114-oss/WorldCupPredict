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

export const settlePersonalBetManually = (ledger: PersonalBetLedger, id: string, profit: number) => {
  const bets = ledger.bets.map((bet) => bet.id === id
    ? {
        ...bet,
        status: 'settled' as const,
        payout: Math.round((bet.stake + profit) * 100) / 100,
        settledAt: new Date().toISOString(),
        settlementMode: 'manual' as const,
      }
    : bet)
  const next = { ...ledger, bets }
  savePersonalLedger(next)
  return next
}

export const reopenPersonalBet = (ledger: PersonalBetLedger, id: string) => {
  const bets = ledger.bets.map((bet) => {
    if (bet.id !== id) return bet
    const { payout: _payout, settledAt: _settledAt, settlementMode: _settlementMode, ...pending } = bet
    return { ...pending, status: 'pending' as const }
  })
  const next = { ...ledger, bets }
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
  const effectiveSelection = leg.settlementSelection ?? leg.selection
  if (leg.market === '比分') {
    const score = `${result.homeScore}:${result.awayScore}`
    if (effectiveSelection === score || effectiveSelection === score.replace(':', '-')) return true
    if (standardScores.has(score)) return false
    const outcome = result.homeScore > result.awayScore ? '胜其它' : result.homeScore === result.awayScore ? '平其它' : '负其它'
    return effectiveSelection === outcome
  }
  if (leg.market === '总进球数') {
    const total = result.homeScore + result.awayScore
    return effectiveSelection === (total >= 7 ? '7+' : String(total))
  }
  if (leg.market === '半全场') {
    if (result.halfTimeHomeScore === null || result.halfTimeHomeScore === undefined || result.halfTimeAwayScore === null || result.halfTimeAwayScore === undefined) return null
    const half = result.halfTimeHomeScore > result.halfTimeAwayScore ? '胜' : result.halfTimeHomeScore === result.halfTimeAwayScore ? '平' : '负'
    const full = result.homeScore > result.awayScore ? '胜' : result.homeScore === result.awayScore ? '平' : '负'
    return effectiveSelection === `${half}${full}`
  }
  const handicapMatch = effectiveSelection.match(/^([+-]\d+)\s+(胜|平|负)$/)
  const handicap = handicapMatch ? Number(handicapMatch[1]) : 0
  const selection = handicapMatch?.[2] ?? effectiveSelection
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
      if (won) winningOdds += leg.settlementOdds ?? leg.odds
    }
    winningOddsByMatch.push(winningOdds)
  }
  const passType = bet.passType ?? inferPassType(groups.length)
  const multiple = bet.multiple ?? Math.max(1, Math.round(bet.stake / 2))
  const standardStake = bet.standardStake ?? Math.max(2, (bet.ticketCount ?? 1) * 2 * multiple)
  const payout = payoutForWinningOdds(winningOddsByMatch, passType, multiple)
  return Math.round(payout * bet.stake / standardStake * 100) / 100
}

export const settlePersonalLedger = (ledger: PersonalBetLedger, settlementFile: SettlementFile) => {
  const results = new Map<string, MatchSettlement>()
  const registerResult = (key: string, match: MatchSettlement) => {
    const existing = results.get(key)
    if (!existing || (!existing.closingOdds && match.closingOdds)) results.set(key, match)
  }
  for (const match of settlementFile.matches) {
    registerResult(match.matchId, match)
    if (match.matchLabel) registerResult(match.matchLabel, match)
  }
  let changed = false
  const bets = ledger.bets.map((bet) => {
    if (bet.status === 'void' || bet.settlementMode === 'manual' || (bet.status === 'settled' && bet.oddsVerifiedAt)) return bet
    const verifiedLegs = bet.legs?.map((leg) => {
      const result = results.get(leg.matchId)
      const marketOdds = result?.closingOdds?.[leg.market]
      const verifiedOdds = marketOdds?.[leg.selection]
      if (verifiedOdds) return { ...leg, settlementOdds: verifiedOdds }
      if (leg.market !== '让球胜平负' || !marketOdds) return leg
      const handicap = leg.selection.match(/^([+-]\d+)\s+(胜|平|负)$/)
      if (!handicap) return leg
      const correctedSelection = `${-Number(handicap[1]) >= 0 ? '+' : ''}${-Number(handicap[1])} ${handicap[2]}`
      const correctedOdds = marketOdds[correctedSelection]
      return correctedOdds
        ? { ...leg, settlementSelection: correctedSelection, settlementOdds: correctedOdds }
        : leg
    })
    const hasVerifiedOdds = verifiedLegs?.some((leg) => leg.settlementOdds !== undefined) ?? false
    if (bet.status === 'settled' && !hasVerifiedOdds) return bet
    const verifiedBet = verifiedLegs ? { ...bet, legs: verifiedLegs } : bet
    const payout = calculateBetPayout(verifiedBet, results)
    if (payout === null) return bet
    const matchIds = bet.legs?.map((leg) => leg.matchId) ?? (bet.matchId ? [bet.matchId] : [])
    const settledAt = matchIds.map((matchId) => results.get(matchId)?.settledAt).filter(Boolean).sort().at(-1)
    changed = true
    return {
      ...verifiedBet,
      status: 'settled' as const,
      payout,
      settledAt,
      oddsVerifiedAt: hasVerifiedOdds
        ? matchIds.map((matchId) => results.get(matchId)?.closingOddsCheckedAt).filter(Boolean).sort().at(-1)
        : undefined,
      oddsSource: hasVerifiedOdds && matchIds.some((matchId) => results.get(matchId)?.closingOddsSource === 'zgzcw.com')
        ? 'zgzcw.com'
        : undefined,
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
