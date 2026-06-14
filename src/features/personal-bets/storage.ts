import type { DailyForecast, MatchSettlement, SettlementFile } from '../../types'
import type { ModelDaySnapshot, PersonalBet, PersonalBetLedger } from './types'

const STORAGE_KEY = 'world-cup-predict-personal-bets-v1'

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

const betWon = (bet: PersonalBet, result: MatchSettlement) => {
  if (bet.market === '比分') return bet.selection === `${result.homeScore}:${result.awayScore}` || bet.selection === `${result.homeScore}-${result.awayScore}`
  if (bet.market === '自定义') return null
  const handicapMatch = bet.selection.match(/^([+-]\d+)\s+(胜|平|负)$/)
  const handicap = handicapMatch ? Number(handicapMatch[1]) : 0
  const selection = handicapMatch?.[2] ?? bet.selection
  const adjustedHome = result.homeScore + handicap
  const outcome = adjustedHome > result.awayScore ? '胜' : adjustedHome === result.awayScore ? '平' : '负'
  return selection === outcome
}

export const settlePersonalLedger = (ledger: PersonalBetLedger, settlementFile: SettlementFile) => {
  const results = new Map(settlementFile.matches.map((match) => [match.matchId, match]))
  let changed = false
  const bets = ledger.bets.map((bet) => {
    if (bet.status !== 'pending' || !bet.matchId) return bet
    const result = results.get(bet.matchId)
    if (!result) return bet
    const won = betWon(bet, result)
    if (won === null) return bet
    changed = true
    return {
      ...bet,
      status: 'settled' as const,
      payout: won ? Math.round(bet.stake * bet.odds * 100) / 100 : 0,
      settledAt: result.settledAt,
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
