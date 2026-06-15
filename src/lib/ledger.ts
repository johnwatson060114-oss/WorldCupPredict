import type { BankrollLedger, LedgerEntry, MatchSettlement, SettlementFile, TicketLeg } from '../types'
import { personalBalance } from '../features/personal-bets/storage'
import type { PersonalBetLedger } from '../features/personal-bets/types'

const STORAGE_KEY = 'world-cup-predict-bankroll-ledger-v1'
const standardScores = new Set(['1:0', '2:0', '2:1', '3:0', '3:1', '3:2', '4:0', '4:1', '4:2', '5:0', '5:1', '5:2', '0:0', '1:1', '2:2', '3:3', '0:1', '0:2', '1:2', '0:3', '1:3', '2:3', '0:4', '1:4', '2:4', '0:5', '1:5', '2:5'])

export const emptyLedger = (): BankrollLedger => ({
  schemaVersion: 1,
  initialBankroll: 200,
  entries: [],
})

export const loadLedger = (): BankrollLedger => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return emptyLedger()
    const parsed = JSON.parse(raw) as BankrollLedger
    return parsed.schemaVersion === 1 ? parsed : emptyLedger()
  } catch {
    return emptyLedger()
  }
}

export const saveLedger = (ledger: BankrollLedger) => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(ledger))
}

export const appendLedgerEntry = (ledger: BankrollLedger, entry: LedgerEntry) => {
  const next = { ...ledger, entries: [entry, ...ledger.entries] }
  saveLedger(next)
  return next
}

export const currentBalance = (ledger: BankrollLedger) =>
  ledger.entries.reduce((balance, entry) => {
    if (entry.status === 'settled' && typeof entry.closingBalance === 'number') return entry.closingBalance
    if (entry.status === 'pending') return balance - entry.stake
    return balance
  }, ledger.initialBankroll)

export const combinedAvailableBalance = (ledger: BankrollLedger, personalLedger: PersonalBetLedger) => Math.max(
  0,
  currentBalance(ledger) + personalBalance(personalLedger) - personalLedger.initialBankroll,
)

export const downloadLedger = (ledger: BankrollLedger) => {
  const blob = new Blob([JSON.stringify(ledger, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'world-cup-bankroll-ledger.json'
  anchor.click()
  URL.revokeObjectURL(url)
}

const legWon = (leg: TicketLeg, result: MatchSettlement) => {
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

export const settleLedger = (ledger: BankrollLedger, settlementFile: SettlementFile) => {
  const results = new Map(settlementFile.matches.map((match) => [match.matchId, match]))
  let changed = false
  const entries = ledger.entries.map((entry) => {
    if (entry.status !== 'pending') return entry
    const allMatchIds = new Set(entry.tickets.flatMap((ticket) => ticket.legs.map((leg) => leg.matchId)))
    if ([...allMatchIds].some((matchId) => !results.has(matchId))) return entry
    const outcomes = entry.tickets.flatMap((ticket) => ticket.legs.map((leg) => legWon(leg, results.get(leg.matchId)!)))
    if (outcomes.some((outcome) => outcome === null)) return entry
    const payout = entry.tickets.reduce((sum, ticket) => {
      const won = ticket.legs.every((leg) => legWon(leg, results.get(leg.matchId)!) === true)
      return sum + (won ? ticket.potentialPayout : 0)
    }, 0)
    changed = true
    return {
      ...entry,
      status: 'settled' as const,
      closingBalance: Math.round((entry.openingBalance - entry.stake + payout) * 100) / 100,
      note: `自动结算于 ${settlementFile.generatedAt}`,
    }
  })
  return changed ? { ...ledger, entries } : ledger
}
