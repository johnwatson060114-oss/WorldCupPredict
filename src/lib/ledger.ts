import type { BankrollLedger, LedgerEntry, MatchSettlement, SettlementFile, TicketLeg } from '../types'

const STORAGE_KEY = 'world-cup-predict-bankroll-ledger-v1'

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
  if (leg.market === '比分') return leg.selection === `${result.homeScore}:${result.awayScore}`
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
    const payout = entry.tickets.reduce((sum, ticket) => {
      const won = ticket.legs.every((leg) => legWon(leg, results.get(leg.matchId)!))
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
